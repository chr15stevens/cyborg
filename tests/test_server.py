"""Tests for the tool surface.

Unlike test_rank.py these touch the filesystem, so every one of them runs against
a CYBORG_HOME under tmp_path and never sees the real registry.
"""

from __future__ import annotations

import pytest

from cyborg import server, store


@pytest.fixture
def registry_home(tmp_path, monkeypatch):
    """Point cyborg at an empty data directory for the duration of one test.

    A freshly initialised registry holds only the seeded template project, which
    is inactive - so this is also the "no active projects" case.
    """
    monkeypatch.setenv("CYBORG_HOME", str(tmp_path))
    return tmp_path


class TestScoutBriefShape:
    def test_an_empty_registry_returns_the_same_keys_as_a_populated_one(self, registry_home):
        empty = server.scout_brief()
        server.add_project("alpha", str(registry_home / "alpha"), "ship it")
        populated = server.scout_brief()

        assert set(populated) <= set(empty)
        assert set(empty) - set(populated) == {"warning"}

    def test_next_step_and_config_are_readable_without_checking_the_branch(self, registry_home):
        empty = server.scout_brief()

        assert empty["next_step"]
        assert empty["config"] == store.load_config().to_dict()

    def test_the_empty_response_still_warns_and_names_the_registry(self, registry_home):
        result = server.scout_brief()

        assert str(store.projects_path()) in result["warning"]
        assert "add_project" in result["warning"]

    def test_a_populated_registry_carries_no_warning(self, registry_home):
        server.add_project("alpha", str(registry_home / "alpha"), "ship it")

        assert "warning" not in server.scout_brief()
