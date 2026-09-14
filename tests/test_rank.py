"""Tests for the deterministic core. No I/O, no server, no LLM."""

from __future__ import annotations

import pytest

from cyborg.models import Candidate, Project, parse_candidates
from cyborg.rank import MIN_DENOM, rank, score_candidate
from cyborg.store import Config


def make_config(**overrides) -> Config:
    base = dict(daily_review_budget=45.0, lam=0.1, max_per_project=2, high_blast_penalty=0.7)
    base.update(overrides)
    return Config(**base)


def make_project(project_id="alpha", priority=3, active=True) -> Project:
    return Project(
        id=project_id,
        path=f"/code/{project_id}",
        goal="ship it",
        priority=priority,
        active=active,
    )


def make_candidate(
    project_id="alpha",
    title="do the thing",
    value=3,
    confidence=0.8,
    agent_minutes=20.0,
    review_minutes=10.0,
    blast_radius="low",
) -> Candidate:
    return Candidate(
        project_id=project_id,
        title=title,
        rationale="because",
        scope="in: this. out: that.",
        acceptance=["it works"],
        value=value,
        confidence=confidence,
        agent_minutes=agent_minutes,
        review_minutes=review_minutes,
        blast_radius=blast_radius,
    )


def registry(*projects: Project) -> dict[str, Project]:
    return {p.id: p for p in projects}


class TestScoring:
    def test_matches_the_formula(self):
        config = make_config()
        candidate = make_candidate(value=4, confidence=0.5, agent_minutes=20, review_minutes=10)
        # (4 * 0.5 * 1.0) / (10 + 0.1 * 20) = 2 / 12
        assert score_candidate(candidate, 3, config) == pytest.approx(2 / 12)

    def test_priority_five_doubles_and_one_halves(self):
        config = make_config()
        candidate = make_candidate()
        neutral = score_candidate(candidate, 3, config)
        assert score_candidate(candidate, 5, config) == pytest.approx(neutral * 5 / 3)
        assert score_candidate(candidate, 1, config) == pytest.approx(neutral * 1 / 3)

    def test_cheap_review_beats_expensive_review_at_equal_value(self):
        config = make_config()
        cheap = make_candidate(review_minutes=2)
        dear = make_candidate(review_minutes=30)
        assert score_candidate(cheap, 3, config) > score_candidate(dear, 3, config)

    def test_agent_time_barely_matters(self):
        """Lambda is deliberately small: agent time should only break ties."""
        config = make_config()
        quick = make_candidate(agent_minutes=5, review_minutes=10)
        slow = make_candidate(agent_minutes=60, review_minutes=10)
        assert score_candidate(quick, 3, config) > score_candidate(slow, 3, config)
        assert score_candidate(quick, 3, config) < score_candidate(slow, 3, config) * 1.6

    def test_high_blast_radius_is_penalised(self):
        config = make_config()
        safe = make_candidate(blast_radius="low")
        risky = make_candidate(blast_radius="high")
        assert score_candidate(risky, 3, config) == pytest.approx(
            score_candidate(safe, 3, config) * 0.7
        )

    def test_zero_cost_item_does_not_divide_by_zero(self):
        config = make_config()
        free = make_candidate(agent_minutes=0, review_minutes=0)
        assert score_candidate(free, 3, config) == pytest.approx((3 * 0.8 * 1.0) / MIN_DENOM)


class TestSelection:
    def test_orders_by_score_descending(self):
        result = rank(
            [
                make_candidate(title="low value", value=1, review_minutes=10),
                make_candidate(title="high value", value=5, review_minutes=10),
            ],
            registry(make_project()),
            make_config(max_per_project=5),
        )
        assert [item["title"] for item in result["selected"]] == ["high value", "low value"]
        assert result["selected"][0]["rank"] == 1

    def test_stops_at_the_review_budget(self):
        result = rank(
            [make_candidate(title=f"item {i}", review_minutes=20) for i in range(4)],
            registry(make_project()),
            make_config(daily_review_budget=45, max_per_project=10),
        )
        assert result["totals"]["review_minutes"] == 40
        assert result["totals"]["selected_count"] == 2
        assert all("review budget" in item["reason"] for item in result["deferred"])

    def test_keeps_scanning_for_something_that_fits(self):
        """A cheap item below the cut should still make the slate."""
        result = rank(
            [
                make_candidate(title="expensive", value=5, confidence=1.0, review_minutes=40),
                make_candidate(title="also expensive", value=5, confidence=0.9, review_minutes=40),
                make_candidate(title="cheap filler", value=1, confidence=0.5, review_minutes=3),
            ],
            registry(make_project()),
            make_config(daily_review_budget=45, max_per_project=10),
        )
        titles = [item["title"] for item in result["selected"]]
        assert titles == ["expensive", "cheap filler"]

    def test_caps_items_per_project(self):
        result = rank(
            [make_candidate(title=f"item {i}", review_minutes=1) for i in range(5)],
            registry(make_project()),
            make_config(max_per_project=2),
        )
        assert result["totals"]["selected_count"] == 2
        assert "already has 2 item(s)" in result["deferred"][0]["reason"]

    def test_one_project_cannot_monopolise_the_slate(self):
        result = rank(
            [
                make_candidate(project_id="alpha", title=f"alpha {i}", value=5, review_minutes=5)
                for i in range(4)
            ]
            + [make_candidate(project_id="beta", title="beta work", value=2, review_minutes=5)],
            registry(make_project("alpha"), make_project("beta")),
            make_config(max_per_project=2),
        )
        assert [item["project_id"] for item in result["selected"]] == ["alpha", "alpha", "beta"]

    def test_defers_unknown_and_inactive_projects(self):
        result = rank(
            [
                make_candidate(project_id="ghost", title="from nowhere"),
                make_candidate(project_id="retired", title="from the past"),
                make_candidate(project_id="alpha", title="real work"),
            ],
            registry(make_project("alpha"), make_project("retired", active=False)),
            make_config(),
        )
        assert [item["title"] for item in result["selected"]] == ["real work"]
        reasons = {item["title"]: item["reason"] for item in result["deferred"]}
        assert "unknown project_id" in reasons["from nowhere"]
        assert "not active" in reasons["from the past"]

    def test_ties_break_deterministically(self):
        candidates = [
            make_candidate(title="b same score"),
            make_candidate(title="a same score"),
        ]
        config, projects = make_config(max_per_project=5), registry(make_project())
        first = rank(candidates, projects, config)
        second = rank(list(reversed(candidates)), projects, config)
        assert [i["title"] for i in first["selected"]] == [i["title"] for i in second["selected"]]

    def test_budget_override_wins(self):
        result = rank(
            [make_candidate(title=f"item {i}", review_minutes=10) for i in range(4)],
            registry(make_project()),
            make_config(daily_review_budget=45, max_per_project=10),
            budget_override=20,
        )
        assert result["totals"]["selected_count"] == 2
        assert result["totals"]["review_budget"] == 20

    def test_empty_input_is_not_an_error(self):
        result = rank([], registry(make_project()), make_config())
        assert result["selected"] == []
        assert result["totals"]["review_budget_remaining"] == 45


class TestValidation:
    def test_good_item_parses(self):
        candidates, rejections = parse_candidates([make_candidate().to_dict()])
        assert len(candidates) == 1 and rejections == []

    @pytest.mark.parametrize(
        "field,bad_value,fragment",
        [
            ("value", 9, "between 1 and 5"),
            ("confidence", 1.5, "between 0 and 1"),
            ("blast_radius", "nuclear", "blast_radius"),
            ("review_minutes", -5, "must not be negative"),
            ("review_minutes", "soon", "must be a number"),
            ("title", "", "title"),
            ("acceptance", [], "acceptance"),
        ],
    )
    def test_bad_fields_are_rejected_with_a_reason(self, field, bad_value, fragment):
        item = make_candidate().to_dict()
        item[field] = bad_value
        candidates, rejections = parse_candidates([item])
        assert candidates == []
        assert fragment in rejections[0].reason

    def test_one_bad_item_does_not_sink_the_batch(self):
        good = make_candidate(title="fine").to_dict()
        bad = make_candidate(title="broken").to_dict()
        bad["value"] = 99
        candidates, rejections = parse_candidates([good, bad])
        assert [c.title for c in candidates] == ["fine"]
        assert rejections[0].title == "broken" and rejections[0].index == 1

    def test_missing_field_is_named(self):
        item = make_candidate().to_dict()
        del item["agent_minutes"]
        _, rejections = parse_candidates([item])
        assert "agent_minutes" in rejections[0].reason
