"""Tests for GitHubTarget helper functionality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import CloneMethod, GitHubTargetConfig
from github_target import GitHubTarget


def _make_target(tmp_path: Path, api_url: str, push_method: CloneMethod) -> GitHubTarget:
    config = GitHubTargetConfig(
        api_url=api_url,
        token='token-value',
        org_name='example-org',
        retry_delay_s=0.1,
        clone_temp_dir=str(tmp_path / 'clones'),
        push_method=push_method,
    )
    return GitHubTarget(config)


def test_get_github_url_resolves_enterprise_host(tmp_path: Path) -> None:
    """Enterprise API URLs should map to the git host without /api/v3."""
    target = _make_target(tmp_path, 'https://github.acme.com/api/v3', CloneMethod.HTTPS)
    expected = 'https://github.acme.com/example-org/sample.git'
    assert target._get_github_url('sample') == expected


def test_get_github_url_public_host(tmp_path: Path) -> None:
    """Public GitHub API should resolve to github.com for both HTTPS and SSH."""
    https_target = _make_target(tmp_path, 'https://api.github.com', CloneMethod.HTTPS)
    assert https_target._get_github_url('demo') == 'https://github.com/example-org/demo.git'

    ssh_target = _make_target(tmp_path, 'https://api.github.com', CloneMethod.SSH)
    assert ssh_target._get_github_url('demo') == 'git@github.com:example-org/demo.git'


@patch.object(GitHubTarget, '_cleanup_temp_dir')
@patch.object(GitHubTarget, '_push_to_github')
@patch.object(GitHubTarget, '_clone_from_gitlab')
@patch.object(GitHubTarget, '_create_secure_temp_dir')
@patch.object(GitHubTarget, 'wait_repo_available')
def test_start_import_no_wait_skips_check(
    mock_wait: MagicMock,
    mock_secure_dir: MagicMock,
    mock_clone: MagicMock,
    mock_push: MagicMock,
    mock_cleanup: MagicMock,
    tmp_path: Path,
) -> None:
    """start_import should honour wait_for_repo flag."""
    target = _make_target(tmp_path, 'https://api.github.com', CloneMethod.HTTPS)

    mock_wait.return_value = True
    mock_secure_dir.return_value = str(tmp_path / 'clone')

    target.start_import(
        'demo',
        'https://gitlab.com/example/demo.git',
        'gitlab-user',
        'glpat_token',
        wait_for_repo=False,
    )

    mock_wait.assert_not_called()
    mock_clone.assert_called_once()
    clone_args = mock_clone.call_args.args
    assert clone_args[0] == 'demo'
    assert clone_args[1] == 'https://gitlab.com/example/demo.git'
    assert clone_args[3] == 'gitlab-user'
    assert clone_args[4] == 'glpat_token'
    mock_push.assert_called_once()
    mock_cleanup.assert_called_once()
