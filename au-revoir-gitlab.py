#!/usr/bin/env python3
"""
Au Revoir Gitlab - Migrate/sync all repositories from a GitLab namespace
to a GitHub organization.

This tool discovers all projects in a GitLab namespace (including subgroups)
and imports them into a GitHub organization using git clone and push.
It is a one-way sync intended to assist org migrations from GitLab to GitHub.

Copyright (c) 2025 Michele Tavella <meeghele@proton.me>
Licensed under the MIT License. See LICENSE file for details.

Author: Michele Tavella <meeghele@proton.me>
License: MIT
"""

from __future__ import annotations

import sys
from typing import NoReturn

from argument_parser import parse_arguments
from sync_orchestrator import SyncOrchestrator

# Exit codes
EXIT_SUCCESS = 0
EXIT_EXECUTION_ERROR = 1


def main() -> NoReturn:
    if __name__ != "__main__":
        sys.exit(EXIT_EXECUTION_ERROR)

    cfg = parse_arguments()
    orchestrator = SyncOrchestrator(cfg)
    sys.exit(orchestrator.run())


if __name__ == "__main__":
    main()
