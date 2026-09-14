# Cyborg — v0 Build Plan

## What it is

An MCP server that owns your project registry and the ranking math. The client LLM does the exploring and estimating; cyborg decides what surfaces and in what order. No LLM calls inside the server — it never talks to a model, it's called *by* one.

The scarce resource is your review time, not agent time. Agent time is cheap and parallel; your attention is serial and capped. So the objective isn't "most valuable work" — it's **merged value per minute of your attention**.

## Division of labour

| Cyborg (deterministic) | Client LLM (judgment) |
|---|---|
| Registry storage + mutation | Exploring repos for signals |
| The scout brief + item contract | Proposing candidate work |
| Schema validation | Estimating value/confidence/minutes |
| Scoring, budget, selection | Presenting the slate |

## Tool surface

1. `list_projects()` → all registry entries
2. `add_project(project_id, path, goal, priority, notes?, active?)`
3. `update_project(project_id, **fields)` — including `active: false` to retire
4. `remove_project(project_id)`
5. `scout_brief(project_ids?)` → the instructions *and* the item contract *and* the project records to scout. Self-describing: the client calls this first and learns the whole job.
6. `rank_candidates(items, budget_override?)` → the ranked slate

Server-level MCP `instructions` tell any client the flow: `scout_brief` → explore → `rank_candidates`.

## Item contract

```json
{
  "project_id": "cyborg",
  "title": "imperative, one line",
  "rationale": "why now, 1-2 sentences",
  "scope": "what's in, what's explicitly out",
  "acceptance": ["checkable criteria"],
  "value": 4,
  "confidence": 0.7,
  "agent_minutes": 25,
  "review_minutes": 10,
  "blast_radius": "low"
}
```

## Ranking

```
score = (value × confidence × priority_weight) / (review_minutes + λ × agent_minutes)
priority_weight = project.priority / 3          # 3 is neutral
if blast_radius == "high": score ×= high_blast_penalty
```

`priority_weight` is the term worth noting: it's **your** knob, from the registry, weighting the LLM's soft `value` by a number you control. When the estimates drift optimistic, that's the dial you turn.

Selection: sort desc, greedily add while cumulative `review_minutes ≤ daily_review_budget`, capped at `max_per_project`. Returns `selected[]` *and* `deferred[]` with a cut reason — so you can always see what it passed over and why.

Config at `~/.cyborg/config.yaml`: `daily_review_budget: 45`, `lambda: 0.1`, `max_per_project: 2`, `high_blast_penalty: 0.7`.

## Layout

```
~/.cyborg/projects.yaml     # your data, server-owned, atomic writes
~/.cyborg/config.yaml

code/cyborg/
  pyproject.toml
  src/cyborg/
    server.py    # MCP tool definitions
    store.py     # registry + config I/O   ← the seam future state grows into
    models.py    # dataclasses + validation
    rank.py      # pure functions, zero I/O
    brief.py     # scout instructions + contract
  tests/test_rank.py
```

`rank.py` stays pure and I/O-free — it's the piece we'll tune most, and pure means tests are trivial.

## Build order

1. **Core** — models, store, rank, unit tests. Reviewable standalone, no server needed.
2. **Server** — the six tools and the brief.
3. **Register + smoke test** — one real project end to end.
4. **Seed** — populate `projects.yaml` with your actual projects.

Registration, once built:

```bash
claude mcp add cyborg -s user -- uv run --directory C:\Users\chr15\Documents\code\cyborg cyborg-mcp
```

## Verification

Unit tests on the scoring and selection (budget exhaustion, project cap, blast penalty, malformed input rejection). Then a live call against one real repo to confirm the round trip produces a sane slate.

```bash
uv run pytest -q
```

## Deferred to v1

Backlog persistence, declined-item memory, verdict capture, estimate-vs-actual calibration, execution, review packets, scheduling. All of it lands behind `store.py` without touching the tool surface.

**The known weakness:** `value` and `confidence` are the numerator and they come from the LLM, so a deterministic prioritiser over soft numbers is still soft. Estimate-vs-actual capture is the fix, one version later.

## Stack

Python, managed by `uv` — no global interpreter needed. Built against MCP Python SDK 2.x, where the server class is `MCPServer` (formerly `FastMCP` in 1.x); `pyproject.toml` pins `mcp>=2.2` accordingly.
