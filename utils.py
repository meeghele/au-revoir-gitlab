#!/usr/bin/env python3
"""Utility functions for au-revoir-gitlab."""

import re
import threading
import time
from typing import List, Optional

from logging_utils import Logger


class RateLimiter:
    """Rate limiter to prevent abuse and respect API limits."""

    def __init__(self, max_requests_per_minute: int = 60):
        self.max_requests = max_requests_per_minute
        self.requests: List[float] = []
        self.lock = threading.Lock()

    def wait_if_needed(self, operation_type: str = "API") -> None:
        """Wait if necessary to respect rate limits."""
        current_time = time.time()

        with self.lock:
            self._clean_old_requests(current_time)
            if len(self.requests) >= self.max_requests:
                wait_time = 60 - (current_time - self.requests[0])
                if wait_time > 0:
                    # Use Logger.security_event to maintain consistent formatting
                    Logger.security_event(
                        "RATE_LIMIT_HIT",
                        f"rate limit reached for {operation_type}, "
                        f"waiting {wait_time:.2f}s",
                    )
                    time.sleep(wait_time)
                    self._clean_old_requests(time.time())
            self.requests.append(current_time)

    def _clean_old_requests(self, current_time: float) -> None:
        """Remove requests older than 1 minute."""
        cutoff_time = current_time - 60
        self.requests = [
            req_time for req_time in self.requests if req_time > cutoff_time
        ]


def sanitize_repo_name(name: str) -> str:
    """Sanitize a string to a valid GitHub repository name."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-.")
    return name or "repo"


def map_gitlab_to_github_name(
    path_with_namespace: str,
    root_namespace: str,
    prefix: Optional[str],
    sep: str,
) -> str:
    """Map GitLab project full path to a GitHub repository name.

    Strategy: remove root namespace prefix, join remaining path segments with '_'.
    Example: 'preava/a/b/c/d/e' -> 'a_b_c_d_e'
    """
    parts = [p for p in path_with_namespace.split("/") if p]
    if parts and parts[0].lower() == root_namespace.lower():
        parts = parts[1:]
    candidate = sep.join(parts) if parts else path_with_namespace.replace("/", sep)
    if prefix:
        candidate = f"{prefix}{sep}{candidate}"
    return sanitize_repo_name(candidate)