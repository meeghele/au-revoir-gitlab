#!/usr/bin/env python3
"""Main orchestrator for synchronizing GitLab namespace to GitHub organization."""

from __future__ import annotations

import sys
from typing import Dict, List, Set, Tuple

from config import CloneMethod, Config, GitHubTargetConfig, Visibility
from gitlab_source import GitLabSource
from github_target import GitHubTarget
from logging_utils import Logger
from utils import map_gitlab_to_github_name, sanitize_repo_name

# Exit codes
EXIT_SUCCESS = 0
EXIT_EXECUTION_ERROR = 1
EXIT_AUTH_ERROR = 40


class SyncOrchestrator:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.gl = GitLabSource(cfg.gitlab.url, cfg.gitlab.token)
        gh_config = GitHubTargetConfig(
            api_url=cfg.github.api_url.rstrip("/"),
            token=cfg.github.token,
            org_name=cfg.github.org,
            retry_delay_s=cfg.behavior.git_config.retry_delay_s,
            clone_temp_dir=cfg.behavior.git_config.clone_temp_dir,
            push_method=cfg.behavior.git_config.push_method,
        )
        self.gh = GitHubTarget(gh_config)
        self._repo_exists_cache: Dict[str, bool] = {}

    def run(self) -> int:
        try:
            self.gl.connect()
            self.gh.connect()

            projects = self.gl.list_projects(
                namespace=self.cfg.gitlab.namespace,
                exclude=self.cfg.behavior.import_config.exclude,
                include_archived=self.cfg.behavior.import_config.include_archived,
            )

            # Plan names with collision handling
            plan = self._plan_names(projects)

            if self.cfg.behavior.import_config.dry_run:
                total = len(plan)
                for idx, (project, gh_name) in enumerate(plan, start=1):
                    src_path = getattr(project, "path_with_namespace", "")
                    Logger.info(
                        f"[{idx}/{total}] would import: {src_path} -> "
                        f"{self.cfg.github.org}/{gh_name}"
                    )
                Logger.info("dry-run completed")
                return EXIT_SUCCESS

            total = len(plan)
            for idx, (project, gh_name) in enumerate(plan, start=1):
                self._process_single_project(project, gh_name, idx, total)

            Logger.info("mission accomplished")
            return EXIT_SUCCESS
        except SystemExit as e:
            return int(e.code) if isinstance(e.code, int) else EXIT_EXECUTION_ERROR
        except Exception as e:
            Logger.error(f"unexpected error: {e}")
            return EXIT_EXECUTION_ERROR

    def _plan_names(self, projects: List[object]) -> List[Tuple[object, str]]:
        """Return list of (project, unique_gh_name) preserving order.

        Ensures names are unique across this batch and do not conflict with
        existing GitHub repos unless --force-reimport is set.
        """
        used: Set[str] = set()
        plan: List[Tuple[object, str]] = []

        total = len(projects)
        for i, project in enumerate(projects, start=1):
            src = getattr(project, "path_with_namespace", "")
            base = map_gitlab_to_github_name(
                src,
                self.cfg.gitlab.namespace,
                self.cfg.behavior.naming_config.name_prefix,
                self.cfg.behavior.naming_config.flatten_sep,
            )
            name = base

            # If already planned, make deterministic unique name using GitLab ID
            if name in used:
                pid = getattr(project, "id", None)
                suffix = f"_gl{pid}" if pid is not None else "_dup"
                name = sanitize_repo_name(f"{base}{suffix}")

            # If still conflicting with existing GitHub repo and not reimporting, adjust
            if name in used or (
                self._repo_exists(name)
                and not self.cfg.behavior.import_config.force_reimport
            ):
                pid = getattr(project, "id", None)
                suffix = f"_gl{pid}" if pid is not None else "_dup"
                cand = sanitize_repo_name(f"{base}{suffix}")
                counter = 2
                while cand in used or (
                    self._repo_exists(cand)
                    and not self.cfg.behavior.import_config.force_reimport
                ):
                    cand = sanitize_repo_name(f"{base}{suffix}_{counter}")
                    counter += 1
                name = cand

            used.add(name)
            plan.append((project, name))
            if i == total or i % 25 == 0:
                Logger.info(f"planning names: {i}/{total}")

        return plan

    def _repo_exists(self, name: str) -> bool:
        """Cached wrapper around GitHub repo existence check."""
        if name not in self._repo_exists_cache:
            self._repo_exists_cache[name] = self.gh.repo_exists(name)
        return self._repo_exists_cache[name]

    def _process_single_project(
        self, project: object, gh_name: str, idx: int, total: int
    ) -> None:
        path_ns = getattr(project, "path_with_namespace", "")
        description = getattr(project, "description", "")
        gl_visibility = getattr(
            project, "visibility", "private"
        )  # private | internal | public

        # Get repository URL based on clone method
        if self.cfg.behavior.git_config.clone_method == CloneMethod.SSH:
            source_url = getattr(project, "ssh_url_to_repo", "")
        else:
            source_url = getattr(project, "http_url_to_repo", "")

        Logger.info(
            f"[{idx}/{total}] sync: {path_ns} -> {self.cfg.github.org}/{gh_name}"
        )

        # Determine target repo visibility from CLI flag
        private = (
            self.cfg.behavior.naming_config.target_visibility == Visibility.PRIVATE
        )

        exists = self._repo_exists(gh_name)
        if exists and self.cfg.behavior.import_config.force_reimport:
            self.gh.delete_repo(gh_name)
            self._repo_exists_cache[gh_name] = False
            exists = False

        if not exists:
            self.gh.create_repo(gh_name, private=private, description=description)
            self._repo_exists_cache[gh_name] = True

        # Require GitLab username for non-public projects when using HTTPS
        if (
            self.cfg.behavior.git_config.clone_method == CloneMethod.HTTPS
            and gl_visibility != Visibility.PUBLIC.value
            and not self.cfg.gitlab.username
        ):
            Logger.error(
                "gitlab username required for private/internal project import "
                "with HTTPS clone method. Set --gl-username or GITLAB_USERNAME, "
                "or use --clone-method ssh."
            )
            sys.exit(EXIT_AUTH_ERROR)

        # Start import (synchronous with git clone/push)
        self.gh.start_import(
            gh_name,
            source_url,
            self.cfg.gitlab.username,
            self.cfg.gitlab.token,
            wait_for_repo=self.cfg.behavior.import_config.wait,
        )
