"""The scout brief: what cyborg tells a client LLM to go and do.

Cyborg makes no LLM calls. It hands out instructions and a contract, then ranks
whatever comes back. This module is the entirety of the prompt side.
"""

from __future__ import annotations

from typing import Any

from .models import Project
from .store import Config

SERVER_INSTRUCTIONS = """\
Cyborg decides what work is worth your human's attention next.

The flow is three calls:
  1. scout_brief()      - get the job, the contract, and the projects to scout
  2. (your own work)    - explore those repos and propose candidate work items
  3. rank_candidates()  - hand back every candidate; cyborg selects and orders

Cyborg owns the registry and the ranking. You own the exploring and estimating.
Do not filter or pre-rank candidates yourself - emit everything plausible and let
rank_candidates apply the budget. Cyborg stores nothing but the project registry,
so every run is cold: it cannot remember what was suggested or declined before.
"""

CONTRACT_EXAMPLE = """\
{
  "project_id": "cyborg",
  "title": "Imperative one-liner, no trailing period",
  "rationale": "Why this is worth doing now, in one or two sentences.",
  "scope": "What is in, and explicitly what is out.",
  "acceptance": ["A checkable criterion", "Another one"],
  "value": 4,
  "confidence": 0.7,
  "agent_minutes": 25,
  "review_minutes": 10,
  "blast_radius": "low"
}\
"""

FIELD_GUIDE = """\
value          1-5. Impact on that project's stated goal. 3 is ordinary useful work.
confidence     0-1. Probability the human accepts it roughly as proposed. Be honest:
               speculative refactors and anything touching unclear intent belong below 0.5.
agent_minutes  Wall-clock minutes for an agent to produce a reviewable change.
review_minutes Minutes for the HUMAN to review the finished work - not to read this
               proposal. This is the scarce resource and the denominator of the score,
               so a careless number here distorts everything.
blast_radius   low | medium | high. high = touches auth, data, deploy, money, or public
               surface area. Scored down automatically.
"""

ESTIMATE_ANCHORS = """\
review_minutes anchors:  2 = glance at a tiny, obviously-correct diff
                         5 = read one focused change with test evidence
                        15 = multi-file change that needs actual thought
                        30 = design-level judgment, or something risky
agent_minutes anchors:   5 = a rename, a doc fix, a one-line guard
                        25 = a small feature or a contained refactor with tests
                        60 = a module, a migration, or anything needing exploration first
"""

EXPLORATION_GUIDE = """\
For each project below, look at the repo at its `path` and find real signals. Cheap
and high-yield first: recent commits, uncommitted or stranded branches, failing or
missing tests, TODO/FIXME markers, README claims that no longer match the code,
dependency drift, and anything the `notes` field points at. Read `notes` carefully -
it is the only memory in the system, and it is where the human parks standing
instructions like "stop suggesting X".

Timebox the looking. You are sampling for signal, not auditing. If more than about
three projects are active, explore them one at a time or fan out a subagent per
project and collect the JSON, rather than pulling every repo into one context.
"""

OUTPUT_RULES = """\
Propose 2-5 candidates per active project. Each must be independently shippable and
bounded - if you cannot say what is out of scope, it is too big to propose. Prefer
work that is cheap to verify over work that is merely valuable; the whole system
optimises for merged value per minute of human review.

Then call rank_candidates with the full list, and present the returned slate:
one line per selected item with its estimates, the detail underneath, the totals,
and a short note on what was deferred and why.
"""


def build_brief(projects: list[Project], config: Config) -> dict[str, Any]:
    """Assemble the brief for the given projects."""
    body = f"""# Cyborg scout brief

## Your job
{EXPLORATION_GUIDE}
## What to emit
Return a JSON list of candidate objects in exactly this shape:

{CONTRACT_EXAMPLE}

### Field guide
{FIELD_GUIDE}
### Calibration
{ESTIMATE_ANCHORS}
## Rules
{OUTPUT_RULES}
## Selection settings in force
The human's review budget is {config.daily_review_budget:g} minutes, at most
{config.max_per_project} item(s) per project. Cyborg applies these - you do not.
"""

    return {
        "brief": body,
        "projects": [p.to_dict() for p in projects],
        "config": config.to_dict(),
        "next_step": "Explore the projects above, then call rank_candidates with every candidate you found.",
    }
