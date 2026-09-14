"""The deterministic core: scoring and selection.

Pure functions, no I/O, no LLM. This is the piece that decides what reaches you,
and the piece we expect to tune most, so it stays trivially testable.
"""

from __future__ import annotations

from typing import Any

from .models import Candidate
from .store import Config

# Floor on the denominator so a zero-cost item cannot divide by zero and take
# an unbounded score. Six seconds of attention is the cheapest work we model.
MIN_DENOM = 0.1

NEUTRAL_PRIORITY = 3.0


def priority_weight(priority: int) -> float:
    """Your registry priority as a multiplier. 3 is neutral, 5 doubles, 1 halves."""
    return priority / NEUTRAL_PRIORITY


def score_candidate(candidate: Candidate, priority: int, config: Config) -> float:
    """Expected value per minute of attention, with agent time as a tiebreaker.

        score = (value x confidence x priority_weight) / (review + lambda x agent)

    priority_weight is the human-owned term: it weights the LLM's soft `value`
    by a number you control, so drifting estimates stay correctable without
    re-prompting anything.
    """
    denominator = max(
        candidate.review_minutes + config.lam * candidate.agent_minutes,
        MIN_DENOM,
    )
    score = (candidate.value * candidate.confidence * priority_weight(priority)) / denominator
    if candidate.blast_radius == "high":
        score *= config.high_blast_penalty
    return score


def _entry(candidate: Candidate, score: float, **extra: Any) -> dict[str, Any]:
    return {**candidate.to_dict(), "score": round(score, 3), **extra}


def rank(
    candidates: list[Candidate],
    projects: dict[str, Any],
    config: Config,
    budget_override: float | None = None,
) -> dict[str, Any]:
    """Score every candidate, then greedily fill the review budget.

    Returns the selected slate and everything it passed over with a reason, so
    the cut is always visible rather than implied.
    """
    budget = float(budget_override) if budget_override is not None else config.daily_review_budget

    scored: list[tuple[float, Candidate]] = []
    deferred: list[dict[str, Any]] = []

    for candidate in candidates:
        project = projects.get(candidate.project_id)
        if project is None:
            deferred.append(
                _entry(candidate, 0.0, reason=f"unknown project_id '{candidate.project_id}'")
            )
            continue
        if not project.active:
            deferred.append(
                _entry(candidate, 0.0, reason=f"project '{project.id}' is not active")
            )
            continue
        scored.append((score_candidate(candidate, project.priority, config), candidate))

    # Ties break toward the cheaper review, then title, so runs are reproducible.
    scored.sort(key=lambda pair: (-pair[0], pair[1].review_minutes, pair[1].title))

    selected: list[dict[str, Any]] = []
    per_project: dict[str, int] = {}
    review_used = 0.0
    agent_used = 0.0

    for score, candidate in scored:
        taken = per_project.get(candidate.project_id, 0)
        if taken >= config.max_per_project:
            deferred.append(
                _entry(
                    candidate,
                    score,
                    reason=(
                        f"project '{candidate.project_id}' already has "
                        f"{config.max_per_project} item(s) on the slate"
                    ),
                )
            )
            continue

        # Keep scanning after a miss: a cheaper item further down may still fit.
        if review_used + candidate.review_minutes > budget:
            deferred.append(
                _entry(
                    candidate,
                    score,
                    reason=(
                        f"would exceed the {budget:g} min review budget "
                        f"({review_used:g} min already committed)"
                    ),
                )
            )
            continue

        per_project[candidate.project_id] = taken + 1
        review_used += candidate.review_minutes
        agent_used += candidate.agent_minutes
        selected.append(_entry(candidate, score, rank=len(selected) + 1))

    return {
        "selected": selected,
        "deferred": deferred,
        "totals": {
            "selected_count": len(selected),
            "deferred_count": len(deferred),
            "review_minutes": round(review_used, 1),
            "agent_minutes": round(agent_used, 1),
            "review_budget": budget,
            "review_budget_remaining": round(budget - review_used, 1),
        },
    }
