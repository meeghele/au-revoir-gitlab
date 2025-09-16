#!/usr/bin/env python3
"""Command line argument parsing and configuration building."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Tuple

from config import (CloneMethod, Config, GitHubConfig, GitLabConfig,
                    GitOperationConfig, ImportConfig, NamingConfig,
                    SyncBehaviorConfig, Visibility)
from logging_utils import Logger
from security import SecurityValidator

# Exit codes
EXIT_AUTH_ERROR = 40
EXIT_MISSING_ARGUMENTS = 2


def _create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Sync GitLab namespace to GitHub organization via API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --gl-namespace preava --gh-org preava
  %(prog)s --gl-namespace preava --gh-org preava --dry-run
  %(prog)s --gl-namespace preava --gh-org preava --exclude archived --name-prefix gl
  %(prog)s --gl-namespace preava --gh-org preava --clone-method ssh --push-method ssh
  %(prog)s --gl-url https://gitlab.company.com \\
           --gh-api https://github.company.com/api/v3 \\
           --gl-namespace team --gh-org team --gl-username yourname \\
           --clone-method https
        """,
    )
    return parser


def _add_gitlab_arguments(parser: argparse.ArgumentParser) -> None:
    """Add GitLab-related arguments to parser."""
    parser.add_argument(
        "--gl-url",
        dest="gl_url",
        default="https://gitlab.com",
        help="Base URL of the GitLab instance",
    )
    parser.add_argument(
        "--gl-token",
        dest="gl_token",
        help="GitLab API token (or set GITLAB_TOKEN env var)",
    )
    parser.add_argument(
        "--gl-namespace",
        dest="gl_namespace",
        required=True,
        help="GitLab root namespace (group) to sync",
    )
    parser.add_argument(
        "--gl-username",
        dest="gl_username",
        help="GitLab username for HTTPS git auth (required for private repos)",
    )


def _add_github_arguments(parser: argparse.ArgumentParser) -> None:
    """Add GitHub-related arguments to parser."""
    parser.add_argument(
        "--gh-api",
        dest="gh_api_url",
        default="https://api.github.com",
        help="Base URL of the GitHub API",
    )
    parser.add_argument(
        "--gh-token",
        dest="gh_token",
        help="GitHub API token (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--gh-org",
        dest="gh_org",
        required=True,
        help="GitHub organization to import into",
    )


def _add_behavior_arguments(parser: argparse.ArgumentParser) -> None:
    """Add behavior and configuration arguments to parser."""
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="List actions without doing them",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        dest="exclude",
        help="Pattern to exclude from subgroups and projects",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        dest="include_archived",
        help="Include archived GitLab projects",
    )
    parser.add_argument(
        "--force-reimport",
        action="store_true",
        dest="force_reimport",
        help="Delete existing GitHub repo if present and re-import",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        dest="no_wait",
        help="Do not wait for import completion",
    )
    parser.add_argument(
        "--name-prefix",
        dest="name_prefix",
        help="Optional prefix to add to every GitHub repo name",
    )
    parser.add_argument(
        "--flatten-sep",
        dest="flatten_sep",
        default="-",
        help="Separator used when flattening subgroup path (default: '-')",
    )
    parser.add_argument(
        "--visibility",
        dest="target_visibility",
        choices=[
            visibility.value
            for visibility in Visibility
            if visibility != Visibility.INTERNAL
        ],
        default=Visibility.PRIVATE.value,
        help="Visibility for created GitHub repos (default: private)",
    )
    parser.add_argument(
        "--retry-delay",
        dest="retry_delay_s",
        type=float,
        default=3.0,
        help="Seconds to wait between retry attempts (default: 3.0)",
    )
    parser.add_argument(
        "--clone-temp-dir",
        dest="clone_temp_dir",
        default="/tmp/au-revoir-gitlab",
        help="Temporary directory for git clones (default: /tmp/au-revoir-gitlab)",
    )
    parser.add_argument(
        "--clone-method",
        dest="clone_method",
        choices=[method.value for method in CloneMethod],
        default=CloneMethod.HTTPS.value,
        help="Clone method for GitLab source: https or ssh (default: https)",
    )
    parser.add_argument(
        "--push-method",
        dest="push_method",
        choices=[method.value for method in CloneMethod],
        default=CloneMethod.HTTPS.value,
        help="Push method for GitHub target: https or ssh (default: https)",
    )


def _validate_parsed_arguments(
    args,
) -> Tuple[str, str, str, str, str, Optional[str], Optional[str]]:
    """Validate and sanitize parsed arguments for security."""
    try:
        # Validate URLs
        validated_gl_url = SecurityValidator.validate_url(
            args.gl_url, ["https", "http"]
        )
        validated_gh_api_url = SecurityValidator.validate_url(
            args.gh_api_url, ["https"]
        )

        # Validate namespace and organization names
        validated_gl_namespace = SecurityValidator.validate_namespace(args.gl_namespace)
        validated_gh_org = SecurityValidator.validate_username(args.gh_org)

        # Validate file paths
        validated_clone_temp_dir = SecurityValidator.validate_file_path(
            args.clone_temp_dir
        )

        # Validate numeric inputs
        if args.retry_delay_s < 0 or args.retry_delay_s > 300:
            raise ValueError("retry delay must be between 0 and 300 seconds")

        # Validate string inputs if provided
        validated_exclude = None
        if args.exclude:
            if len(args.exclude) > 100:
                raise ValueError("exclude pattern too long (max 100 characters)")
            validated_exclude = args.exclude

        validated_name_prefix = None
        if args.name_prefix:
            validated_name_prefix = SecurityValidator.validate_repo_name(
                args.name_prefix
            )

        if len(args.flatten_sep) > 5:
            raise ValueError("flatten separator too long (max 5 characters)")

        Logger.security_event(
            "CONFIG_VALIDATION", "successfully validated all configuration inputs"
        )

        return (
            validated_gl_url,
            validated_gh_api_url,
            validated_gl_namespace,
            validated_gh_org,
            validated_clone_temp_dir,
            validated_exclude,
            validated_name_prefix,
        )

    except ValueError as e:
        Logger.security_event(
            "CONFIG_VALIDATION_FAILED", f"configuration validation failed: {e}"
        )
        Logger.error(f"configuration validation error: {e}")
        sys.exit(EXIT_MISSING_ARGUMENTS)


def _get_and_validate_tokens(args) -> Tuple[str, str, str]:
    """Get and validate authentication tokens."""
    gl_token = args.gl_token or os.getenv("GITLAB_TOKEN")
    gh_token = args.gh_token or os.getenv("GITHUB_TOKEN")
    if not gl_token:
        Logger.error(
            "error: gitlab token not provided (use --gl-token or GITLAB_TOKEN)"
        )
        sys.exit(EXIT_AUTH_ERROR)
    if not gh_token:
        Logger.error(
            "error: github token not provided (use --gh-token or GITHUB_TOKEN)"
        )
        sys.exit(EXIT_AUTH_ERROR)

    # GitLab username for HTTPS git auth
    gl_username = args.gl_username or os.getenv("GITLAB_USERNAME")
    validated_gl_username = ""
    if gl_username:
        try:
            validated_gl_username = SecurityValidator.validate_username(gl_username)
        except ValueError as e:
            Logger.security_event(
                "USERNAME_VALIDATION_FAILED", f"GitLab username validation failed: {e}"
            )
            Logger.error(f"GitLab username validation error: {e}")
            sys.exit(EXIT_AUTH_ERROR)
    else:
        Logger.warn(
            "warning: --gl-username (or GITLAB_USERNAME) not set; private "
            "imports will likely fail"
        )

    return gl_token, gh_token, validated_gl_username


def parse_arguments() -> Config:
    """Parse command line arguments and return configuration object."""
    parser = _create_argument_parser()
    _add_gitlab_arguments(parser)
    _add_github_arguments(parser)
    _add_behavior_arguments(parser)

    args = parser.parse_args()

    # Validate parsed arguments
    (
        validated_gl_url,
        validated_gh_api_url,
        validated_gl_namespace,
        validated_gh_org,
        validated_clone_temp_dir,
        validated_exclude,
        validated_name_prefix,
    ) = _validate_parsed_arguments(args)

    # Get and validate tokens
    gl_token, gh_token, validated_gl_username = _get_and_validate_tokens(args)

    return Config(
        gitlab=GitLabConfig(
            url=validated_gl_url,
            token=gl_token,
            namespace=validated_gl_namespace,
            username=validated_gl_username,
        ),
        github=GitHubConfig(
            api_url=validated_gh_api_url,
            token=gh_token,
            org=validated_gh_org,
        ),
        behavior=SyncBehaviorConfig(
            import_config=ImportConfig(
                dry_run=args.dry_run,
                exclude=validated_exclude,
                include_archived=args.include_archived,
                force_reimport=args.force_reimport,
                wait=not args.no_wait,
            ),
            naming_config=NamingConfig(
                name_prefix=validated_name_prefix,
                flatten_sep=args.flatten_sep,
                target_visibility=Visibility(args.target_visibility),
            ),
            git_config=GitOperationConfig(
                retry_delay_s=float(args.retry_delay_s),
                clone_temp_dir=validated_clone_temp_dir,
                clone_method=CloneMethod(args.clone_method),
                push_method=CloneMethod(args.push_method),
            ),
        ),
    )