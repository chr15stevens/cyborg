"""Data shapes and validation.

Nothing here does I/O. Validation is strict and returns reasons rather than
raising, because a scout run that produces one malformed item should still
surface the other nine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

BLAST_RADII = ("low", "medium", "high")


class ValidationError(ValueError):
    """Raised for bad input on the registry side, where there is no batch to salvage."""


@dataclass
class Project:
    id: str
    path: str
    goal: str
    priority: int = 3
    active: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Project":
        if not isinstance(raw, dict):
            raise ValidationError("project entry must be a mapping")
        missing = [k for k in ("id", "path", "goal") if not str(raw.get(k, "")).strip()]
        if missing:
            raise ValidationError(f"project is missing required field(s): {', '.join(missing)}")

        priority = raw.get("priority", 3)
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            raise ValidationError(f"priority must be an integer 1-5, got {priority!r}")
        if not 1 <= priority <= 5:
            raise ValidationError(f"priority must be between 1 and 5, got {priority}")

        return cls(
            id=str(raw["id"]).strip(),
            path=str(raw["path"]).strip(),
            goal=str(raw["goal"]).strip(),
            priority=priority,
            active=bool(raw.get("active", True)),
            notes=str(raw.get("notes", "") or ""),
        )


@dataclass
class Candidate:
    """One proposed piece of work, as emitted by the scouting LLM."""

    project_id: str
    title: str
    rationale: str
    scope: str
    acceptance: list[str]
    value: int
    confidence: float
    agent_minutes: float
    review_minutes: float
    blast_radius: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Rejection:
    """A candidate that failed validation, kept so the client can see why."""

    index: int
    title: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(raw: dict[str, Any], key: str) -> float:
    if key not in raw:
        raise ValueError(f"missing required field '{key}'")
    try:
        return float(raw[key])
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' must be a number, got {raw[key]!r}")


def parse_candidate(raw: Any, index: int) -> Candidate:
    """Parse one candidate or raise ValueError with a human-readable reason."""
    if not isinstance(raw, dict):
        raise ValueError("item must be a mapping")

    for key in ("project_id", "title", "rationale", "scope"):
        if not str(raw.get(key, "")).strip():
            raise ValueError(f"missing required field '{key}'")

    acceptance = raw.get("acceptance", [])
    if isinstance(acceptance, str):
        acceptance = [acceptance]
    if not isinstance(acceptance, list) or not acceptance:
        raise ValueError("'acceptance' must be a non-empty list of checkable criteria")
    acceptance = [str(a).strip() for a in acceptance if str(a).strip()]
    if not acceptance:
        raise ValueError("'acceptance' must contain at least one non-empty criterion")

    value = _number(raw, "value")
    if not 1 <= value <= 5:
        raise ValueError(f"'value' must be between 1 and 5, got {value}")

    confidence = _number(raw, "confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"'confidence' must be between 0 and 1, got {confidence}")

    agent_minutes = _number(raw, "agent_minutes")
    review_minutes = _number(raw, "review_minutes")
    if agent_minutes < 0 or review_minutes < 0:
        raise ValueError("'agent_minutes' and 'review_minutes' must not be negative")

    blast_radius = str(raw.get("blast_radius", "low")).strip().lower()
    if blast_radius not in BLAST_RADII:
        raise ValueError(f"'blast_radius' must be one of {', '.join(BLAST_RADII)}, got {blast_radius!r}")

    return Candidate(
        project_id=str(raw["project_id"]).strip(),
        title=str(raw["title"]).strip(),
        rationale=str(raw["rationale"]).strip(),
        scope=str(raw["scope"]).strip(),
        acceptance=acceptance,
        value=int(value),
        confidence=confidence,
        agent_minutes=agent_minutes,
        review_minutes=review_minutes,
        blast_radius=blast_radius,
    )


def parse_candidates(raw_items: Any) -> tuple[list[Candidate], list[Rejection]]:
    """Parse a batch, partitioning into accepted candidates and rejections."""
    if not isinstance(raw_items, list):
        raise ValidationError("items must be a list of candidate objects")

    candidates: list[Candidate] = []
    rejections: list[Rejection] = []
    for i, raw in enumerate(raw_items):
        title = str(raw.get("title", "")).strip() if isinstance(raw, dict) else ""
        try:
            candidates.append(parse_candidate(raw, i))
        except ValueError as exc:
            rejections.append(Rejection(index=i, title=title or "<untitled>", reason=str(exc)))
    return candidates, rejections
