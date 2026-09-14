"""MCP tool surface.

Six tools, each thin. Everything substantive lives in rank.py (the decision) and
store.py (the state). This file is wiring.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from . import brief as brief_mod
from . import store
from .models import Project, ValidationError, parse_candidates
from .rank import rank as rank_items

mcp = MCPServer(
    "cyborg",
    version=__version__,
    instructions=brief_mod.SERVER_INSTRUCTIONS,
)


@mcp.tool()
def list_projects(include_inactive: bool = True) -> dict[str, Any]:
    """List the project registry.

    Args:
        include_inactive: when False, return only projects marked active.
    """
    projects = store.load_projects()
    if not include_inactive:
        projects = [p for p in projects if p.active]
    return {
        "projects": [p.to_dict() for p in projects],
        "count": len(projects),
        "registry_path": str(store.projects_path()),
    }


@mcp.tool()
def add_project(
    project_id: str,
    path: str,
    goal: str,
    priority: int = 3,
    notes: str = "",
    active: bool = True,
) -> dict[str, Any]:
    """Add a project to the registry.

    Args:
        project_id: short stable slug, unique in the registry.
        path: absolute path to the project directory.
        goal: what the project is for, in one sentence.
        priority: 1-5, your weighting knob. 3 is neutral.
        notes: free text context, including standing instructions to the scout.
        active: whether the scout should consider it.
    """
    projects = store.load_projects()
    if any(p.id == project_id for p in projects):
        raise ValidationError(f"project '{project_id}' already exists; use update_project")

    project = Project.from_dict(
        {
            "id": project_id,
            "path": path,
            "goal": goal,
            "priority": priority,
            "active": active,
            "notes": notes,
        }
    )
    projects.append(project)
    store.save_projects(projects)
    return {"added": project.to_dict(), "count": len(projects)}


@mcp.tool()
def update_project(
    project_id: str,
    path: str | None = None,
    goal: str | None = None,
    priority: int | None = None,
    active: bool | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update fields on an existing project. Omitted fields are left alone.

    Args:
        project_id: the project to update.
        path: new absolute path.
        goal: new one-sentence goal.
        priority: new priority, 1-5.
        active: set False to retire a project without deleting its notes.
        notes: replacement notes text.
    """
    projects = store.load_projects()
    existing = next((p for p in projects if p.id == project_id), None)
    if existing is None:
        raise ValidationError(f"no project '{project_id}' in the registry")

    merged = existing.to_dict()
    for key, value in (
        ("path", path),
        ("goal", goal),
        ("priority", priority),
        ("active", active),
        ("notes", notes),
    ):
        if value is not None:
            merged[key] = value

    updated = Project.from_dict(merged)
    projects = [updated if p.id == project_id else p for p in projects]
    store.save_projects(projects)
    return {"updated": updated.to_dict()}


@mcp.tool()
def remove_project(project_id: str) -> dict[str, Any]:
    """Delete a project from the registry. Prefer update_project(active=False) to retire one.

    Args:
        project_id: the project to delete.
    """
    projects = store.load_projects()
    remaining = [p for p in projects if p.id != project_id]
    if len(remaining) == len(projects):
        raise ValidationError(f"no project '{project_id}' in the registry")
    store.save_projects(remaining)
    return {"removed": project_id, "count": len(remaining)}


@mcp.tool()
def scout_brief(project_ids: list[str] | None = None) -> dict[str, Any]:
    """Get the scouting job: instructions, the item contract, and the projects to explore.

    Call this first. Returns only active projects unless specific ids are named.

    Args:
        project_ids: restrict the brief to these projects; omit for all active ones.
    """
    projects = store.load_projects()
    if project_ids:
        wanted = set(project_ids)
        projects = [p for p in projects if p.id in wanted]
        missing = sorted(wanted - {p.id for p in projects})
        if missing:
            raise ValidationError(f"no project(s) in the registry: {', '.join(missing)}")
    else:
        projects = [p for p in projects if p.active]

    if not projects:
        return {
            "brief": "",
            "projects": [],
            "warning": (
                f"No active projects in {store.projects_path()}. "
                "Add one with add_project before scouting."
            ),
        }

    return brief_mod.build_brief(projects, store.load_config())


@mcp.tool()
def rank_candidates(
    items: list[dict[str, Any]],
    budget_override: float | None = None,
) -> dict[str, Any]:
    """Score, budget and order candidate work items. This is the decision step.

    Pass every candidate you found - do not pre-filter. Returns the selected slate,
    everything deferred with a reason, and the totals.

    Args:
        items: candidate objects in the shape given by scout_brief.
        budget_override: use this many review minutes instead of the configured budget.
    """
    candidates, rejections = parse_candidates(items)
    projects = {p.id: p for p in store.load_projects()}
    result = rank_items(candidates, projects, store.load_config(), budget_override)
    result["rejected"] = [r.to_dict() for r in rejections]
    result["totals"]["rejected_count"] = len(rejections)
    return result


def main() -> None:
    """Entry point for `cyborg-mcp`."""
    store.ensure_initialised()
    mcp.run()


if __name__ == "__main__":
    main()
