# Cyborg

An MCP server that owns your project registry and the ranking math. The client LLM does the exploring and estimating; cyborg decides what surfaces and in what order. No LLM calls inside the server — it never talks to a model, it's called *by* one.

The scarce resource is your review time, not agent time. Agent time is cheap and parallel; your attention is serial and capped. So the objective isn't "most valuable work" — it's **merged value per minute of your attention**.

## Division of labour

| Cyborg (deterministic) | Client LLM (judgment) |
|---|---|
| Registry storage + mutation | Exploring repos for signals |
| The scout brief + item contract | Proposing candidate work |
| Schema validation | Estimating value/confidence/minutes |
| Scoring, budget, selection | Presenting the slate |

## Install and register

Python, managed by `uv` — no global interpreter needed. Built against MCP Python SDK 2.x, where the server class is `MCPServer` (formerly `FastMCP` in 1.x); `pyproject.toml` pins `mcp>=2.2` accordingly.

The repository ships a `.mcp.json` at its root, so any client that reads project-local MCP config (Claude Code does) registers it automatically when the project is opened:

```json
{
  "mcpServers": {
    "cyborg": {
      "command": "uv",
      "args": ["run", "--directory", ".", "cyborg-mcp"]
    }
  }
}
```

To register it anywhere else, point the client at the entry point:

```bash
claude mcp add cyborg -s user -- uv run --directory C:\Users\chr15\Documents\code\cyborg cyborg-mcp
```

On first run the server initialises `~/.cyborg/` if it is missing.

## The tool surface

1. `list_projects(include_inactive?)` → all registry entries
2. `add_project(project_id, path, goal, priority, notes?, active?)`
3. `update_project(project_id, **fields)` — including `active: false` to retire
4. `remove_project(project_id)`
5. `scout_brief(project_ids?)` → the instructions *and* the item contract *and* the project records to scout. Self-describing: the client calls this first and learns the whole job.
6. `rank_candidates(items, budget_override?)` → the ranked slate

Server-level MCP `instructions` tell any client the flow: `scout_brief` → explore → `rank_candidates`.

### A worked `rank_candidates` call

The client passes *every* candidate it found — cyborg never pre-filters. Given the registry project `demo` (priority 3, active) and two candidates:

```json
[
  {
    "project_id": "demo",
    "title": "Fix flaky login test",
    "rationale": "It fails ~1 in 10 runs and blocks CI confidence.",
    "scope": "Make the test deterministic; out: anything beyond the test file.",
    "acceptance": ["CI green three runs in a row"],
    "value": 3, "confidence": 0.8,
    "agent_minutes": 10, "review_minutes": 5, "blast_radius": "low"
  },
  {
    "project_id": "demo",
    "title": "Add rate limiting to the public API",
    "rationale": "One tenant can starve the rest.",
    "scope": "Token bucket on the ingress; out: per-tenant plans.",
    "acceptance": ["Bursts over 100 r/min return 429"],
    "value": 4, "confidence": 0.6,
    "agent_minutes": 45, "review_minutes": 15, "blast_radius": "high"
  }
]
```

`rank_candidates` returns (trimmed for readability):

```json
{
  "selected": [
    { "title": "Fix flaky login test", "score": 0.4, "rank": 1 },
    { "title": "Add rate limiting to the public API", "score": 0.086, "rank": 2 }
  ],
  "deferred": [],
  "rejected": [],
  "totals": {
    "selected_count": 2,
    "review_minutes": 20.0,
    "agent_minutes": 55.0,
    "review_budget": 45.0,
    "review_budget_remaining": 25.0
  }
}
```

Read the output like this:

- `selected[]` — the slate, in the order to review, each carrying its own score and rank.
- `deferred[]` — everything passed over, *with a cut reason* (budget exhausted, per-project cap, unknown or inactive project). You can always see what was skipped and why.
- `rejected[]` — candidates that failed schema validation, with the validation reason, kept so one malformed item never hides the rest.
- `totals` — what the slate costs against the budget.

## Ranking

```
score = (value × confidence × priority_weight) / (review_minutes + λ × agent_minutes)
priority_weight = project.priority / 3          # 3 is neutral
if blast_radius == "high": score ×= high_blast_penalty
```

`priority_weight` is the term worth noting: it's **your** knob, from the registry, weighting the LLM's soft `value` by a number you control. When the estimates drift optimistic, that's the dial you turn.

Selection: sort desc, greedily add while cumulative `review_minutes ≤ daily_review_budget`, capped at `max_per_project`. Ties break toward the cheaper review, then title, so runs are reproducible.

## Configuration

`~/.cyborg/config.yaml`:

```yaml
daily_review_budget: 45    # minutes of review per slate
lambda: 0.1                # agent minutes converted to review-equivalent minutes
max_per_project: 2         # slate entries from one project
high_blast_penalty: 0.7    # multiplier for auth/data/deploy/money work
```

`rank_candidates` also accepts a `budget_override` for a one-off different budget without touching the file.

## Layout

```
~/.cyborg/projects.yaml     # your data, server-owned, atomic writes
~/.cyborg/config.yaml

code/cyborg/
  pyproject.toml
  .mcp.json                # project-local registration
  src/cyborg/
    server.py    # MCP tool definitions
    store.py     # registry + config I/O   ← the seam future state grows into
    models.py    # dataclasses + validation
    rank.py      # pure functions, zero I/O
    brief.py     # scout instructions + contract
  tests/test_rank.py
```

`rank.py` stays pure and I/O-free — it's the piece we'll tune most, and pure means tests are trivial.

## Verification

Unit tests on the scoring and selection (budget exhaustion, project cap, blast penalty, malformed input rejection), plus a live round trip: `scout_brief` against a real registry, then `rank_candidates` with real candidates, confirming the slate matches hand-computed scores.

```bash
uv run pytest -q
```

## Deferred to v1

Backlog persistence, declined-item memory, verdict capture, estimate-vs-actual calibration, execution, review packets, scheduling. All of it lands behind `store.py` without touching the tool surface.

**The known weakness:** `value` and `confidence` are the numerator and they come from the LLM, so a deterministic prioritiser over soft numbers is still soft. Estimate-vs-actual capture is the fix, one version later.
