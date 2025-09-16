"""Tests for GitLabSource discovery helpers."""

from __future__ import annotations

from unittest.mock import Mock

from gitlab_source import GitLabSource


def test_list_projects_includes_nested_subgroups() -> None:
    """All subgroup projects should be returned without owned filters."""
    source = GitLabSource('https://gitlab.com', 'gl-token')

    mock_api = Mock()
    mock_groups = Mock()
    mock_api.groups = mock_groups
    source.api = mock_api
    source.rate_limiter.wait_if_needed = lambda *_args, **_kwargs: None

    root_project = Mock()
    root_project.path_with_namespace = 'example/root'
    root_project.archived = False

    subgroup_project = Mock()
    subgroup_project.path_with_namespace = 'example/sub/repo'
    subgroup_project.archived = False

    subgroup_stub = Mock()
    subgroup_stub.id = 42
    subgroup_stub.full_path = 'example/sub'

    root_group = Mock()
    root_group.projects.list.return_value = [root_project]
    root_group.subgroups = Mock()
    root_group.subgroups.list.return_value = [subgroup_stub]

    subgroup_group = Mock()
    subgroup_group.projects.list.return_value = [subgroup_project]
    subgroup_group.subgroups = Mock()
    subgroup_group.subgroups.list.return_value = []

    def get_side_effect(identifier, **_kwargs):
        if identifier == 'example':
            return root_group
        if identifier == 42:
            return subgroup_group
        raise AssertionError('unexpected group lookup')

    mock_groups.get.side_effect = get_side_effect

    projects = source.list_projects('example', exclude=None, include_archived=False)

    assert root_project in projects
    assert subgroup_project in projects
    assert len(projects) == 2
