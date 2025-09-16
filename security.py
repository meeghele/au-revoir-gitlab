#!/usr/bin/env python3
"""Security validation utilities for au-revoir-gitlab."""

import os
import re
from typing import List, Optional


class SecurityValidator:
    """Security validation utilities for input sanitization and validation."""

    # Maximum lengths to prevent buffer overflow attacks
    MAX_REPO_NAME_LENGTH = 100
    MAX_URL_LENGTH = 2048
    MAX_USERNAME_LENGTH = 100
    MAX_NAMESPACE_LENGTH = 255
    MAX_PATH_LENGTH = 500

    # Allowed characters for various inputs
    SAFE_REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
    SAFE_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
    SAFE_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")

    @classmethod
    def validate_repo_name(cls, name: str) -> str:
        """Validate and sanitize repository name for security."""
        if not name or not isinstance(name, str):
            raise ValueError("Repository name must be a non-empty string")

        if len(name) > cls.MAX_REPO_NAME_LENGTH:
            raise ValueError(
                f"Repository name exceeds maximum length of {cls.MAX_REPO_NAME_LENGTH}"
            )

        # Check for path traversal attempts
        if ".." in name or "/" in name or "\\" in name:
            raise ValueError("Repository name contains invalid path characters")

        # Check for null bytes and control characters
        if "\x00" in name or any(ord(c) < 32 for c in name):
            raise ValueError(
                "Repository name contains null bytes or control characters"
            )

        # Sanitize to safe characters only
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "-", name)
        sanitized = re.sub(r"-+", "-", sanitized).strip("-.")

        if not sanitized:
            raise ValueError("Repository name contains no valid characters")

        return sanitized

    @classmethod
    def validate_url(cls, url: str, allowed_schemes: Optional[List[str]] = None) -> str:
        """Validate URL for security."""
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string")

        if len(url) > cls.MAX_URL_LENGTH:
            raise ValueError(f"URL exceeds maximum length of {cls.MAX_URL_LENGTH}")

        # Check for null bytes and control characters
        if "\x00" in url or any(ord(c) < 32 for c in url if c not in "\t\n\r"):
            raise ValueError("URL contains null bytes or control characters")

        # Basic URL format validation (allow SSH URLs too)
        if not (url.startswith(("http://", "https://")) or url.startswith("git@")):
            raise ValueError("URL must use http, https, or SSH (git@) scheme")

        if allowed_schemes:
            if url.startswith("git@"):
                scheme = "ssh"
            else:
                scheme = url.split("://")[0].lower()
            if scheme not in allowed_schemes:
                raise ValueError(
                    f"URL scheme '{scheme}' not in allowed schemes: {allowed_schemes}"
                )

        # Check for suspicious patterns
        suspicious_patterns = [
            "javascript:",
            "data:",
            "file:",
            "ftp:",
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "169.254.",
            "10.",
            "192.168.",
            "172.",
        ]

        url_lower = url.lower()
        for pattern in suspicious_patterns:
            if pattern in url_lower:
                # Use print here to avoid circular dependency
                print(
                    f"WARNING: potentially suspicious URL pattern detected: {pattern}"
                )

        return url

    @classmethod
    def validate_username(cls, username: str) -> str:
        """Validate username for security."""
        if not username or not isinstance(username, str):
            raise ValueError("Username must be a non-empty string")

        if len(username) > cls.MAX_USERNAME_LENGTH:
            raise ValueError(
                f"Username exceeds maximum length of {cls.MAX_USERNAME_LENGTH}"
            )

        # Check for null bytes and control characters
        if "\x00" in username or any(ord(c) < 32 for c in username):
            raise ValueError("Username contains null bytes or control characters")

        # Basic username validation
        if not cls.SAFE_USERNAME_PATTERN.match(username):
            raise ValueError("Username contains invalid characters")

        return username

    @classmethod
    def validate_namespace(cls, namespace: str) -> str:
        """Validate namespace for security."""
        if not namespace or not isinstance(namespace, str):
            raise ValueError("Namespace must be a non-empty string")

        if len(namespace) > cls.MAX_NAMESPACE_LENGTH:
            raise ValueError(
                f"Namespace exceeds maximum length of {cls.MAX_NAMESPACE_LENGTH}"
            )

        # Check for null bytes and control characters
        if "\x00" in namespace or any(ord(c) < 32 for c in namespace):
            raise ValueError("Namespace contains null bytes or control characters")

        # Check for path traversal attempts
        if ".." in namespace:
            raise ValueError("Namespace contains path traversal sequences")

        # Basic namespace validation
        if not cls.SAFE_NAMESPACE_PATTERN.match(namespace):
            raise ValueError("Namespace contains invalid characters")

        return namespace

    @classmethod
    def validate_file_path(cls, path: str) -> str:
        """Validate file path for security."""
        if not path or not isinstance(path, str):
            raise ValueError("File path must be a non-empty string")

        if len(path) > cls.MAX_PATH_LENGTH:
            raise ValueError(
                f"File path exceeds maximum length of {cls.MAX_PATH_LENGTH}"
            )

        # Check for null bytes
        if "\x00" in path:
            raise ValueError("File path contains null bytes")

        # Check for path traversal attempts
        if ".." in path:
            raise ValueError("File path contains path traversal sequences")

        # Normalize path to prevent bypass attempts
        normalized = os.path.normpath(path)
        if normalized != path:
            # Use print here to avoid circular dependency
            print(f"WARNING: path normalization changed input: {path} -> {normalized}")

        return normalized

    @classmethod
    def sanitize_for_logging(cls, message: str) -> str:
        """Sanitize message for safe logging by removing potential credentials."""
        if not message:
            return message

        # Patterns to redact
        patterns = [
            (r"https://[^:/@]+:[^@]+@", "https://[REDACTED]@"),  # URLs with credentials
            (r"token[=:\s]+[^\s]+", "token=[REDACTED]"),  # Token assignments
            (r"password[=:\s]+[^\s]+", "password=[REDACTED]"),  # Password assignments
            (r"glpat_[A-Za-z0-9_-]+", "[GITLAB_TOKEN_REDACTED]"),  # GitLab tokens
            (r"ghp_[A-Za-z0-9_]+", "[GITHUB_TOKEN_REDACTED]"),  # GitHub tokens
            (r"gho_[A-Za-z0-9_]+", "[GITHUB_TOKEN_REDACTED]"),  # GitHub OAuth tokens
            (r"ghu_[A-Za-z0-9_]+", "[GITHUB_TOKEN_REDACTED]"),  # GitHub user tokens
            (r"ghs_[A-Za-z0-9_]+", "[GITHUB_TOKEN_REDACTED]"),  # GitHub server tokens
            (r"ghr_[A-Za-z0-9_]+", "[GITHUB_TOKEN_REDACTED]"),  # GitHub refresh tokens
        ]

        sanitized = message
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

        return sanitized