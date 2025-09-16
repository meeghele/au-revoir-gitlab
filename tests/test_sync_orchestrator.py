"""Tests for SyncOrchestrator helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from config import (
    CloneMethod,
    Config,
    GitHubConfig,
    GitLabConfig,
    GitOperationConfig,
    ImportConfig,
    NamingConfig,
    SyncBehaviorConfig,
    Visibility,
)
from sync_orchestrator import SyncOrchestrator


def _make_config(tmp_path) -> Config:
    return Config(
        gitlab=GitLabConfig(
            url='https://gitlab.com',
            token='gl-token',
            namespace='example',
            username='gitlab-user',
        ),
        github=GitHubConfig(
            api_url='https://api.github.com',
            token='gh-token',
            org='example-org',
        ),
        behavior=SyncBehaviorConfig(
            import_config=ImportConfig(
                dry_run=True,
                exclude=None,
                include_archived=False,
                force_reimport=False,
                wait=True,
            ),
            naming_config=NamingConfig(
                name_prefix=None,
                flatten_sep='-',
                target_visibility=Visibility.PRIVATE,
            ),
            git_config=GitOperationConfig(
                retry_delay_s=0.1,
                clone_temp_dir=str(tmp_path / 'clones'),
                clone_method=CloneMethod.HTTPS,
                push_method=CloneMethod.HTTPS,
            ),
        ),
    )


def test_repo_exists_is_cached(tmp_path) -> None:
    """Repeated repo existence checks should hit the API only once."""
    orchestrator = SyncOrchestrator(_make_config(tmp_path))
    orchestrator.gh.repo_exists = MagicMock(return_value=True)

    assert orchestrator._repo_exists('demo') is True
    assert orchestrator._repo_exists('demo') is True
    orchestrator.gh.repo_exists.assert_called_once_with('demo')


def test_plan_names_uses_cache_for_collisions(tmp_path) -> None:
    """_plan_names should de-duplicate names using cached repo lookups."""
    orchestrator = SyncOrchestrator(_make_config(tmp_path))
    orchestrator._repo_exists_cache.clear()
    orchestrator._repo_exists = MagicMock(side_effect=[False, True, False])

    project_a = SimpleNamespace(path_with_namespace='example/repo', id=1001)
    project_b = SimpleNamespace(path_with_namespace='example/repo', id=1002)

    plan = orchestrator._plan_names([project_a, project_b])

    assert plan[0][1] == 'repo'
    assert plan[1][1].startswith('repo_gl1002')
    assert orchestrator._repo_exists.call_count >= 2
