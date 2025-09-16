#!/usr/bin/env python3
"""GitHub API wrapper for creating repos and managing imports."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

import github
import requests

if TYPE_CHECKING:
    from github.Organization import Organization

from config import CloneMethod, GitHubTargetConfig
from logging_utils import Logger
from security import SecurityValidator
from utils import RateLimiter

# Exit codes
EXIT_AUTH_ERROR = 40
EXIT_GITHUB_ERROR = 31


class GitHubTarget:
    """Wrapper around GitHub API to create repos and trigger imports."""

    def __init__(self, config: GitHubTargetConfig) -> None:
        self.config = config
        self.api: Optional[github.Github] = None
        self.org: Optional["Organization"] = None
        self.rate_limiter = RateLimiter(
            max_requests_per_minute=50
        )  # GitHub's standard rate limit

    def connect(self) -> None:
        Logger.info(f"init github API: {self.config.api_url}")
        try:
            auth = github.Auth.Token(self.config.token)
            if self.config.api_url != "https://api.github.com":
                self.api = github.Github(base_url=self.config.api_url, auth=auth)
            else:
                self.api = github.Github(auth=auth)
            # Preflight: check org visibility and membership
            self._preflight_org_access()
            self.org = self.api.get_organization(self.config.org_name)
            Logger.debug(f"github org: {self.org.login}")
        except github.BadCredentialsException:
            Logger.error("authentication failed (github): invalid token")
            sys.exit(EXIT_AUTH_ERROR)
        except github.GithubException as e:
            Logger.error(f"github error: {e}")
            sys.exit(EXIT_GITHUB_ERROR)
        except Exception as e:
            Logger.error(f"failed to initialize github API: {e}")
            sys.exit(EXIT_GITHUB_ERROR)

    def _get_api_headers(self) -> dict:
        """Get standard API headers for GitHub requests."""
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.config.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _git_base_url(self) -> str:
        """Return base URL for Git operations derived from API endpoint."""
        parsed = urlparse(self.config.api_url)
        if parsed.netloc == "api.github.com":
            return "https://github.com"

        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/api/v3"):
            base_path = base_path[: -len("/api/v3")]
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base_path:
            base += base_path
        return base

    def _git_hostname(self) -> str:
        """Return hostname for SSH Git operations."""
        parsed = urlparse(self.config.api_url)
        if parsed.netloc == "api.github.com":
            return "github.com"
        return parsed.netloc

    def _get_github_url(self, validated_name: str) -> str:
        """Get GitHub remote URL based on push method."""
        if self.config.push_method == CloneMethod.SSH:
            hostname = self._git_hostname()
            return f"git@{hostname}:{self.config.org_name}/{validated_name}.git"
        base_url = self._git_base_url().rstrip("/")
        return f"{base_url}/{self.config.org_name}/{validated_name}.git"

    def _create_askpass_script(self, username: str, password: str) -> str:
        """Create a temporary askpass script for secure credential injection."""
        fd, path = tempfile.mkstemp(prefix="arg_askpass_", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as script:
                script.write("#!/bin/sh\n")
                script.write("case \"$1\" in\n")
                script.write(f"  *Username*) echo '{username}' ;;\n")
                script.write(f"  *Password*) echo '{password}' ;;\n")
                script.write("  *) exit 1 ;;\n")
                script.write("esac\n")
            os.chmod(path, 0o700)
        except Exception:
            os.close(fd)
            os.unlink(path)
            raise
        return path

    @staticmethod
    def _cleanup_askpass_script(path: Optional[str]) -> None:
        """Remove temporary askpass script if it exists."""
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as error:
            Logger.warn(
                f"failed to clean up temporary credential helper: {error}"
            )

    def _check_org_visibility(self, headers: dict) -> None:
        """Check if organization exists and is visible to the token."""
        org_url = f"{self.config.api_url}/orgs/{self.config.org_name}"
        try:
            self.rate_limiter.wait_if_needed("GitHub API")
            r_org = requests.get(org_url, headers=headers, timeout=30)
        except requests.RequestException as e:
            Logger.error(f"failed to contact github api: {e}")
            sys.exit(EXIT_GITHUB_ERROR)

        if r_org.status_code == 401:
            Logger.error(
                "unauthorized (401): token invalid or not authorized for GitHub API"
            )
            sys.exit(EXIT_AUTH_ERROR)
        if r_org.status_code == 403:
            Logger.error(
                "forbidden (403): token lacks permission to access the organization. "
                "Possible causes: missing read:org scope, "
                "fine‑grained token not granted to the org, "
                "or SAML SSO not authorized for this token."
            )
            sys.exit(EXIT_GITHUB_ERROR)
        if r_org.status_code == 404:
            Logger.error(
                f"not found (404): organization '{self.config.org_name}' does not "
                "exist or is not visible to this token (not a member)."
            )
            sys.exit(EXIT_GITHUB_ERROR)
        if r_org.status_code != 200:
            Logger.warn(
                f"unexpected response checking org visibility: {r_org.status_code}"
            )

    def _check_org_membership(self, headers: dict) -> None:
        """Check organization membership and role."""
        mem_url = f"{self.config.api_url}/user/memberships/orgs/{self.config.org_name}"
        try:
            self.rate_limiter.wait_if_needed("GitHub API")
            r_mem = requests.get(mem_url, headers=headers, timeout=30)
        except requests.RequestException:
            Logger.warn("could not check org membership (request error)")
            return

        if r_mem.status_code == 200:
            self._handle_membership_success(r_mem.json())
        else:
            self._handle_membership_error(r_mem.status_code)

    def _handle_membership_success(self, data: dict) -> None:
        """Handle successful membership check response."""
        state = data.get("state")  # active, pending
        role = data.get("role")  # admin, member
        Logger.info(f"org membership: state={state}, role={role}")

        if state != "active":
            Logger.error(
                "membership not active for target organization; access will fail"
            )
            sys.exit(EXIT_GITHUB_ERROR)
        if role != "admin":
            Logger.warn(
                "membership role is not admin; repo creation may be "
                "restricted by org settings"
            )

    def _handle_membership_error(self, status_code: int) -> None:
        """Handle membership check error responses."""
        if status_code == 401:
            Logger.warn(
                "membership check unauthorized (401): token not authorized "
                "to read org membership (missing scopes)."
            )
        elif status_code == 403:
            Logger.warn(
                "membership check forbidden (403): missing read:org scope, "
                "fine‑grained token not granted to org, or SAML SSO not "
                "authorized."
            )
        elif status_code == 404:
            Logger.warn(
                "membership not found (404): token user is not a member of "
                "the org or the org is private and not visible; operations "
                "may fail"
            )
        else:
            Logger.warn(f"unexpected response checking membership: {status_code}")

    def _preflight_org_access(self) -> None:
        """Check org exists/visible and report membership and role."""
        headers = self._get_api_headers()
        self._check_org_visibility(headers)
        self._check_org_membership(headers)

    def repo_exists(self, name: str) -> bool:
        if self.api is None or self.org is None:
            Logger.error("github API not initialized")
            sys.exit(EXIT_GITHUB_ERROR)
        try:
            self.rate_limiter.wait_if_needed("GitHub API")
            self.org.get_repo(name)
            return True
        except github.GithubException as e:
            if e.status == 404:
                return False
            raise

    def delete_repo(self, name: str) -> None:
        if self.api is None or self.org is None:
            Logger.error("github API not initialized")
            sys.exit(EXIT_GITHUB_ERROR)
        try:
            self.rate_limiter.wait_if_needed("GitHub API")
            repo = self.org.get_repo(name)
            self.rate_limiter.wait_if_needed("GitHub API")
            repo.delete()
            Logger.warn(f"deleted existing repo: {name}")
        except github.GithubException as e:
            Logger.error(f"failed to delete repo '{name}': {e}")
            sys.exit(EXIT_GITHUB_ERROR)

    def create_repo(self, name: str, private: bool, description: Optional[str]) -> None:
        if self.api is None or self.org is None:
            Logger.error("github API not initialized")
            sys.exit(EXIT_GITHUB_ERROR)
        try:
            self.rate_limiter.wait_if_needed("GitHub API")
            self.org.create_repo(
                name=name,
                description=description or "",
                private=private,
                has_issues=True,
                has_projects=False,
                has_wiki=False,
                auto_init=False,
            )
            Logger.info(f"created repo: {name}")
        except github.GithubException as e:
            Logger.error(f"failed to create repo '{name}': {e}")
            sys.exit(EXIT_GITHUB_ERROR)

    def wait_repo_available(self, name: str, attempts: int = 10) -> bool:
        """Wait until the repository is visible via REST (eventual consistency).

        Returns True if repository is available, False otherwise.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.config.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        url = f"{self.config.api_url}/repos/{self.config.org_name}/{name}"
        for i in range(1, attempts + 1):
            try:
                self.rate_limiter.wait_if_needed("GitHub API")
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code == 200:
                    Logger.info(f"repository '{name}' verified as accessible")
                    return True
                if r.status_code == 404:
                    Logger.debug(
                        f"repository '{name}' not yet visible (attempt {i}/{attempts})"
                    )
                else:
                    Logger.warn(
                        f"unexpected status {r.status_code} when checking "
                        f"repository '{name}'"
                    )
            except requests.RequestException as e:
                Logger.debug(f"request error checking repository '{name}': {e}")
            time.sleep(self.config.retry_delay_s)

        Logger.error(f"repository '{name}' not accessible after {attempts} attempts")
        return False

    def _validate_import_inputs(
        self, name: str, source_url: str, gl_username: str
    ) -> tuple[str, str, str, str]:
        """Validate and sanitize inputs for repository import."""
        try:
            validated_name = SecurityValidator.validate_repo_name(name)
            validated_source_url = SecurityValidator.validate_url(
                source_url, ["https", "ssh"]
            )
            validated_username = (
                SecurityValidator.validate_username(gl_username)
                if gl_username
                else gl_username
            )
            validated_temp_dir = SecurityValidator.validate_file_path(
                self.config.clone_temp_dir
            )

            Logger.security_event(
                "INPUT_VALIDATION",
                f"validated inputs for repository import: {validated_name}",
            )
            return (
                validated_name,
                validated_source_url,
                validated_username,
                validated_temp_dir,
            )
        except ValueError as e:
            Logger.security_event(
                "INPUT_VALIDATION_FAILED", f"input validation failed for {name}: {e}"
            )
            Logger.error(f"security validation failed for '{name}': {e}")
            sys.exit(EXIT_GITHUB_ERROR)

    def _create_secure_temp_dir(
        self, validated_name: str, validated_temp_dir: str
    ) -> str:
        """Create secure temporary directory for git operations."""
        # Ensure base temp directory exists with secure permissions (owner only)
        os.makedirs(validated_temp_dir, mode=0o700, exist_ok=True)

        # Verify directory permissions are secure
        stat_info = os.stat(validated_temp_dir)
        if stat_info.st_mode & 0o777 != 0o700:
            Logger.security_event(
                "INSECURE_PERMISSIONS",
                f"fixing insecure permissions on {validated_temp_dir}",
            )
            os.chmod(validated_temp_dir, 0o700)

        # Create unique temp directory for this repo with secure permissions
        clone_dir = tempfile.mkdtemp(
            prefix=f"{validated_name}_", dir=validated_temp_dir
        )
        os.chmod(clone_dir, 0o700)
        Logger.info(f"cloning '{validated_name}' to secure temporary directory")
        return clone_dir

    def _clone_from_gitlab(
        self,
        validated_name: str,
        source_url: str,
        clone_dir: str,
        validated_username: str,
        gl_token: str,
    ) -> None:
        """Clone repository from GitLab."""
        Logger.info(f"cloning from GitLab: {validated_name}")
        env = os.environ.copy()
        askpass_script: Optional[str] = None
        try:
            if source_url.startswith("https://") and gl_token:
                username = validated_username or "oauth2"
                askpass_script = self._create_askpass_script(username, gl_token)
                env.update(
                    {
                        "GIT_ASKPASS": askpass_script,
                        "GIT_TERMINAL_PROMPT": "0",
                    }
                )
            subprocess.run(
                ["git", "clone", "--mirror", source_url, clone_dir],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=env,
            )
            Logger.security_event(
                "GIT_CLONE_SUCCESS", f"successfully cloned repository {validated_name}"
            )
        except subprocess.TimeoutExpired:
            Logger.security_event(
                "GIT_CLONE_TIMEOUT", f"git clone timeout for {validated_name}"
            )
            raise
        except subprocess.CalledProcessError as e:
            Logger.security_event(
                "GIT_CLONE_FAILED", f"git clone failed for {validated_name}"
            )
            # Sanitize error output before logging
            safe_stderr = SecurityValidator.sanitize_for_logging(e.stderr or "")
            safe_stdout = SecurityValidator.sanitize_for_logging(e.stdout or "")
            raise subprocess.CalledProcessError(
                e.returncode, e.cmd, safe_stdout, safe_stderr
            )
        finally:
            self._cleanup_askpass_script(askpass_script)

    def _push_to_github(
        self, validated_name: str, github_url: str, clone_dir: str
    ) -> None:
        """Push repository to GitHub."""
        Logger.info(f"pushing to GitHub: {validated_name}")
        env = os.environ.copy()
        askpass_script: Optional[str] = None
        try:
            if self.config.push_method == CloneMethod.HTTPS:
                askpass_script = self._create_askpass_script(
                    "x-access-token", self.config.token
                )
                env.update(
                    {
                        "GIT_ASKPASS": askpass_script,
                        "GIT_TERMINAL_PROMPT": "0",
                    }
                )
            subprocess.run(
                ["git", "push", "--mirror", github_url],
                cwd=clone_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
                env=env,
            )
            Logger.security_event(
                "GIT_PUSH_SUCCESS", f"successfully pushed repository {validated_name}"
            )
        except subprocess.TimeoutExpired:
            Logger.security_event(
                "GIT_PUSH_TIMEOUT", f"git push timeout for {validated_name}"
            )
            raise
        except subprocess.CalledProcessError as e:
            Logger.security_event(
                "GIT_PUSH_FAILED", f"git push failed for {validated_name}"
            )
            # DEBUG: Show unsanitized error for troubleshooting
            # (remove in production)
            Logger.error(f"DEBUG - Raw git push error: {e.stderr or e.stdout}")
            # Sanitize error output before logging
            safe_stderr = SecurityValidator.sanitize_for_logging(e.stderr or "")
            safe_stdout = SecurityValidator.sanitize_for_logging(e.stdout or "")
            raise subprocess.CalledProcessError(
                e.returncode, e.cmd, safe_stdout, safe_stderr
            )
        finally:
            self._cleanup_askpass_script(askpass_script)

    def _cleanup_temp_dir(self, clone_dir: str, validated_name: str) -> None:
        """Securely clean up temporary directory."""
        if clone_dir and os.path.exists(clone_dir):
            try:
                # Ensure we can delete files by removing any read-only flags
                for root, dirs, files in os.walk(clone_dir):
                    for d in dirs:
                        os.chmod(os.path.join(root, d), 0o700)
                    for f in files:
                        os.chmod(os.path.join(root, f), 0o600)

                # Remove the directory
                shutil.rmtree(clone_dir, ignore_errors=False)
                Logger.debug("securely cleaned up temporary directory")
                Logger.security_event(
                    "CLEANUP_SUCCESS",
                    f"temporary directory cleaned up for {validated_name}",
                )
            except OSError:
                Logger.security_event(
                    "CLEANUP_FAILED",
                    f"failed to clean up temporary directory for {validated_name}",
                )
                # Try force removal as last resort
                try:
                    shutil.rmtree(clone_dir, ignore_errors=True)
                except Exception:
                    pass
                Logger.warn(
                    "failed to clean up temporary directory, attempted force removal"
                )
            except Exception as e:
                Logger.security_event(
                    "CLEANUP_EXCEPTION",
                    f"unexpected cleanup error for {validated_name}",
                )
                safe_error = SecurityValidator.sanitize_for_logging(str(e))
                Logger.warn(f"unexpected error during cleanup: {safe_error}")

    def start_import(
        self,
        name: str,
        source_url: str,
        gl_username: str,
        gl_token: str,
        *,
        wait_for_repo: bool = True,
    ) -> None:
        """Import repository using git clone and push (replaces deprecated
        GitHub import API)."""
        # Validate inputs
        validated_name, validated_source_url, validated_username, validated_temp_dir = (
            self._validate_import_inputs(name, source_url, gl_username)
        )

        # Verify repository is accessible before attempting import
        if wait_for_repo:
            if not self.wait_repo_available(validated_name):
                Logger.error(
                    f"cannot start import for '{validated_name}': repository not accessible"
                )
                sys.exit(EXIT_GITHUB_ERROR)
        else:
            Logger.warn(
                "skipping GitHub repository availability wait (--no-wait)"
            )

        clone_dir = None
        try:
            # Set up secure temporary directory
            clone_dir = self._create_secure_temp_dir(validated_name, validated_temp_dir)

            # Prepare authentication and clone from GitLab
            self._clone_from_gitlab(
                validated_name,
                validated_source_url,
                clone_dir,
                validated_username,
                gl_token,
            )

            # Push to GitHub
            github_url = self._get_github_url(validated_name)
            self._push_to_github(validated_name, github_url, clone_dir)

            Logger.info(f"import completed: {validated_name}")

        except subprocess.CalledProcessError:
            # Error already sanitized and logged above in the specific handlers
            Logger.security_event(
                "IMPORT_FAILED", f"import process failed for {validated_name or name}"
            )
            sys.exit(EXIT_GITHUB_ERROR)
        except Exception as e:
            Logger.security_event(
                "IMPORT_EXCEPTION",
                f"unexpected exception during import for {validated_name or name}",
            )
            # Sanitize error message before logging
            safe_error = SecurityValidator.sanitize_for_logging(str(e))
            Logger.error(f"import failed for '{validated_name or name}': {safe_error}")
            sys.exit(EXIT_GITHUB_ERROR)
        finally:
            # Secure cleanup of temporary directory
            if clone_dir:
                self._cleanup_temp_dir(clone_dir, validated_name or name)
