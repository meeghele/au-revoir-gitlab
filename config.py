#!/usr/bin/env python3
"""Configuration dataclasses for au-revoir-gitlab."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CloneMethod(Enum):
    """Enumeration for git clone/push methods."""
    HTTPS = "https"
    SSH = "ssh"


class Visibility(Enum):
    """Enumeration for repository visibility levels."""
    PRIVATE = "private"
    PUBLIC = "public"
    INTERNAL = "internal"


@dataclass
class GitLabConfig:
    """GitLab-specific configuration."""
    url: str
    token: str
    namespace: str
    username: str


@dataclass
class GitHubConfig:
    """GitHub-specific configuration."""
    api_url: str
    token: str
    org: str


@dataclass
class ImportConfig:
    """Import behavior configuration."""
    dry_run: bool
    exclude: Optional[str]
    include_archived: bool
    force_reimport: bool
    wait: bool


@dataclass
class NamingConfig:
    """Repository naming configuration."""
    name_prefix: Optional[str]
    flatten_sep: str
    target_visibility: Visibility


@dataclass
class GitOperationConfig:
    """Git operation configuration."""
    retry_delay_s: float
    clone_temp_dir: str
    clone_method: CloneMethod = CloneMethod.HTTPS
    push_method: CloneMethod = CloneMethod.HTTPS


@dataclass
class SyncBehaviorConfig:
    """Sync behavior configuration."""
    import_config: ImportConfig
    naming_config: NamingConfig
    git_config: GitOperationConfig


@dataclass
class GitHubTargetConfig:
    """Configuration for GitHub target operations."""
    api_url: str
    token: str
    org_name: str
    retry_delay_s: float
    clone_temp_dir: str
    push_method: CloneMethod


@dataclass
class Config:
    """Main configuration for GitLab-to-GitHub sync."""
    gitlab: GitLabConfig
    github: GitHubConfig
    behavior: SyncBehaviorConfig