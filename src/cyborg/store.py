"""Registry and config persistence.

This module is the seam. Today it is two YAML files; when the backlog, verdicts
and outcome history arrive in v1 they grow behind this interface without the MCP
tool surface changing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import Project, ValidationError

DEFAULT_CONFIG: dict[str, Any] = {
    "daily_review_budget": 45,
    "lambda": 0.1,
    "max_per_project": 2,
    "high_blast_penalty": 0.7,
}

_CONFIG_HEADER = """\
# Cyborg tuning knobs.
#   daily_review_budget: minutes of your attention the slate may consume
#   lambda:              weight on agent time relative to your time (agent time is cheap)
#   max_per_project:     stops one repo monopolising the slate
#   high_blast_penalty:  score multiplier applied to blast_radius: high
"""

_PROJECTS_HEADER = """\
# Cyborg project registry. The only data you own by hand.
# priority is your knob: 3 is neutral, 5 doubles a project's weight, 1 halves it.
"""

_TEMPLATE_PROJECTS: dict[str, Any] = {
    "projects": [
        {
            "id": "example",
            "path": str(Path.home() / "code" / "example"),
            "goal": "What this project is for, in one sentence.",
            "priority": 3,
            "active": False,
            "notes": "Free text. Also where you write 'stop suggesting X' - nothing else remembers.",
        }
    ]
}


def home() -> Path:
    """Cyborg's data directory. Overridable with CYBORG_HOME, which tests rely on."""
    return Path(os.environ.get("CYBORG_HOME") or (Path.home() / ".cyborg"))


def projects_path() -> Path:
    return home() / "projects.yaml"


def config_path() -> Path:
    return home() / "config.yaml"


@dataclass
class Config:
    daily_review_budget: float = 45.0
    lam: float = 0.1
    max_per_project: int = 2
    high_blast_penalty: float = 0.7

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        merged = {**DEFAULT_CONFIG, **(raw or {})}
        return cls(
            daily_review_budget=float(merged["daily_review_budget"]),
            lam=float(merged["lambda"]),
            max_per_project=int(merged["max_per_project"]),
            high_blast_penalty=float(merged["high_blast_penalty"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_review_budget": self.daily_review_budget,
            "lambda": self.lam,
            "max_per_project": self.max_per_project,
            "high_blast_penalty": self.high_blast_penalty,
        }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def ensure_initialised() -> list[str]:
    """Create the data directory and seed files if absent. Returns what was created."""
    created: list[str] = []
    if not config_path().exists():
        _atomic_write(config_path(), _CONFIG_HEADER + _dump(DEFAULT_CONFIG))
        created.append(str(config_path()))
    if not projects_path().exists():
        _atomic_write(projects_path(), _PROJECTS_HEADER + _dump(_TEMPLATE_PROJECTS))
        created.append(str(projects_path()))
    return created


def load_config() -> Config:
    ensure_initialised()
    raw = yaml.safe_load(config_path().read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValidationError(f"{config_path()} must contain a mapping of settings")
    return Config.from_dict(raw)


def load_projects() -> list[Project]:
    ensure_initialised()
    raw = yaml.safe_load(projects_path().read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or "projects" not in raw:
        raise ValidationError(f"{projects_path()} must contain a top-level 'projects' list")
    entries = raw.get("projects") or []
    if not isinstance(entries, list):
        raise ValidationError("'projects' must be a list")

    projects = [Project.from_dict(entry) for entry in entries]
    seen: set[str] = set()
    for project in projects:
        if project.id in seen:
            raise ValidationError(f"duplicate project id '{project.id}' in registry")
        seen.add(project.id)
    return projects


def save_projects(projects: list[Project]) -> None:
    payload = {"projects": [p.to_dict() for p in projects]}
    _atomic_write(projects_path(), _PROJECTS_HEADER + _dump(payload))


def get_project(project_id: str) -> Project | None:
    return next((p for p in load_projects() if p.id == project_id), None)
