#!/usr/bin/env python3
"""GitLab API wrapper for discovering projects in namespaces."""

from __future__ import annotations

import sys
from typing import List, Optional

import gitlab

from logging_utils import Logger
from utils import RateLimiter

# Exit codes
EXIT_AUTH_ERROR = 40
EXIT_GITLAB_ERROR = 30


class GitLabSource:
    """Wrapper around GitLab API to enumerate projects."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self.api: Optional[gitlab.Gitlab] = None
        self.rate_limiter = RateLimiter(
            max_requests_per_minute=30
        )  # Conservative GitLab rate limit

    def connect(self) -> None:
        Logger.info(f"init gitlab API: {self.url}")
        try:
            self.api = gitlab.Gitlab(url=self.url, private_token=self.token)
            self.api.auth()
        except gitlab.exceptions.GitlabAuthenticationError as e:
            Logger.error(f"authentication error (gitlab): {e}")
            sys.exit(EXIT_AUTH_ERROR)
        except Exception as e:
            Logger.error(f"failed to initialize gitlab API: {e}")
            sys.exit(EXIT_GITLAB_ERROR)

    def list_projects(
        self, namespace: str, exclude: Optional[str], include_archived: bool
    ) -> List[object]:
        if self.api is None:
            Logger.error("gitlab API not initialized")
            sys.exit(EXIT_GITLAB_ERROR)

        Logger.info(f"discovering projects under: {namespace}")
        projects: List[object] = []
        try:
            # Root group (lazy to avoid fetching all fields)
            self.rate_limiter.wait_if_needed("GitLab API")
            root_group = self.api.groups.get(
                namespace, lazy=False, include_subgroups=True
            )

            # Root projects
            Logger.info("getting root projects")
            self.rate_limiter.wait_if_needed("GitLab API")
            for project in getattr(root_group, "projects").list(all=True):
                if not include_archived and getattr(project, "archived", False):
                    continue
                path_ns = getattr(project, "path_with_namespace", "")
                if exclude and exclude in path_ns:
                    Logger.warn(f"excluding: {path_ns}")
                    continue
                projects.append(project)
                Logger.debug(f"found: {path_ns}")

            # Descendant groups
            Logger.info("getting sub-groups")
            subgroups_manager = getattr(root_group, "subgroups", None)
            if subgroups_manager is not None:
                to_visit = subgroups_manager.list(all=True, recursive=True)
            else:
                to_visit = []

            visited = set()
            for subgroup in to_visit:
                subgroup_id = getattr(subgroup, "id", None)
                if subgroup_id is None or subgroup_id in visited:
                    continue

                visited.add(subgroup_id)
                full_path = getattr(subgroup, "full_path", "")
                if exclude and exclude in full_path:
                    Logger.warn(f"excluding: {full_path}")
                    continue

                self.rate_limiter.wait_if_needed("GitLab API")
                full_group = self.api.groups.get(subgroup_id, lazy=False)
                for project in getattr(full_group, "projects").list(all=True):
                    if not include_archived and getattr(project, "archived", False):
                        continue
                    path_ns = getattr(project, "path_with_namespace", "")
                    if exclude and exclude in path_ns:
                        Logger.warn(f"excluding: {path_ns}")
                        continue
                    projects.append(project)
                    Logger.debug(f"found: {path_ns}")

        except gitlab.exceptions.GitlabGetError as e:
            Logger.error(f"failed to list projects under '{namespace}': {e}")
            sys.exit(EXIT_GITLAB_ERROR)
        except Exception as e:
            Logger.error(f"unexpected error while collecting projects: {e}")
            sys.exit(EXIT_GITLAB_ERROR)

        Logger.info(f"found {len(projects)} projects to process")
        return projects
