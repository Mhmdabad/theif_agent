# THIEF Agent (גנב) — Distributed Cops-and-Robbers over a Peer-to-Peer Network

[![CI](https://github.com/Mhmdabad/theif_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Mhmdabad/theif_agent/actions/workflows/ci.yml)

Final project — **Orchestration of AI Agents**, Computer Science Department,
University of Haifa, 2026. Rulebook: *Distributed Cops-and-Robbers over a
Peer-to-Peer Network*, book version 3.0.0, Dr. Yoram Reuven Segal.

> **Companion repository — COP agent: <https://github.com/Mhmdabad/police_agent>**
>
> This team submits two repositories. This one holds the **THIEF**; the link
> above holds the **COP**. The two agents run as completely separate processes
> under separate configuration directories and share no state whatsoever.

---

## Contents

- [What this is](#what-this-is)
- [Status](#status)
- [Running it](#running-it)
- [Repository layout](#repository-layout)
- **Academic report**
  - [1. The Dec-POMDP model](#1-the-dec-pomdp-model)
  - [2. FastMCP orchestration dilemmas](#2-fastmcp-orchestration-dilemmas)
  - [3. Strategies implemented](#3-strategies-implemented)
  - [4. Learning curves](#4-learning-curves)
  - [5. Screenshots](#5-screenshots)
  - [6. Companion repository](#6-companion-repository)
- [Documented rulebook contradictions](#documented-rulebook-contradictions)
- [Team](#team)

---

## What this is

A cop chases a thief on a discrete grid with **no central server and no
referee**. Neither agent observes the true world state: each maintains a belief
over its opponent's position, built from a decaying **scent field** that cannot
be faked and a **verbal hint** that may be a deliberate lie.

Each agent is simultaneously an MCP server and an MCP client over **FastMCP**,
exposed to the public internet through a tunnel. Integrity is enforced by
**Commit-Reveal over SHA-256** rather than by an authority: every move is sealed
before it is disclosed, and the full match log is mutually audited afterwards.

This repository implements the **THIEF** — the side that evades, survives, and
must answer a capture claim truthfully under cryptographic obligation.

## Status

Under development. Progress is tracked as one GitHub issue per task, labelled by
build stage (`stage-0` … `stage-7`, `league`, `submission`, `final-checklist`).

| Stage | Scope | State |
| --- | --- | --- |
| 0 | Repository setup | in progress |
| 1 | Base logic | not started |
| 2 | FastMCP infrastructure | not started |
| 3 | Strategy module | not started |
| 4 | Language and scent | not started |
| 5 | Cloud exposure | not started |
| 6 | Cryptography | not started |
| 7 | Reporting, GUI, replay | not started |

Planning documents: [`docs/PLAN.md`](docs/PLAN.md),
[`docs/TODO.md`](docs/TODO.md), [`docs/prd/`](docs/prd/README.md).
A transcription of the rulebook is in [`project-book/`](project-book/README.md).

## Running it

```bash
uv sync
```

<!-- TODO: expand once the peer entry point exists (PRD-2). Target shape:
     uv run python -m thief_agent peer --role thief
     uv run python -m thief_agent replay --log logs/thief_match.json         -->

Quality gates run on every push and pull request: `ruff check`, `ruff format`,
`mypy`, and `pytest` with a coverage floor defined in `pyproject.toml`.

## Repository layout

```
config/          shared signed game.json + private thief/game.toml
docs/            PLAN, seven PRDs, TODO
project-book/    Markdown transcription of the course rulebook
src/thief_agent/ the agent
tests/           pytest suite
```

---

# Academic report

> The six sections below are mandatory (Rulebook §9.4.2). They are stubbed here
> and filled in as the corresponding stage completes; each carries a note saying
> what belongs in it and which stage produces the material.

## 1. The Dec-POMDP model

<!-- Required: a scientific description of the formalism adopted for this race —
     the state space, the observation function available to each agent, and the
     structure of the uncertainty. Specific to our implementation, not generic
     textbook prose. Source: Rulebook ch. 1. Produced by: PRD-1, PRD-4.        -->

*To be written — see PRD-1 (state space) and PRD-4 (observations, belief).*

## 2. FastMCP orchestration dilemmas

<!-- Required: the development trade-offs around orchestrating communication
     between two mutually untrusted agents — turn management, handling network
     failures, and the roles of the Gatekeeper and Orchestrator patterns. The
     grader is looking for reasoning and rejected alternatives, not a
     description of the final code. Source: ch. 2, ch. 8. From: PRD-2, PRD-5.  -->

*To be written — see PRD-2 (Orchestrator, state machine, reliability patterns)
and PRD-5 (tunnelling, latency, failure handling).*

## 3. Strategies implemented

<!-- Required: the decision mechanism actually built, and why. The rulebook
     treats three routes as equal-standing: pure heuristics (Manhattan distance
     + Bayesian belief), an LLM-based strategy, or — optionally — Q-Learning.
     What is graded is the quality of the justification. Source: ch. 6.
     Produced by: PRD-3, PRD-4.                                                -->

**Route chosen: our own heuristic algorithm.** Not pure Manhattan-plus-belief,
and not reinforcement learning. The reasoning below is what the implementation
actually taught us, in the order it taught us.

### Why not the pure-heuristic route

The obvious policy is *maximise Manhattan distance from the cop, break ties by
remaining escape space*. We built exactly that first, and both halves failed
for reasons that are visible in the git history rather than argued from
theory.

**Distance is actively wrong in a corner.** From `(6, 6)` with the cop at
`(0, 0)`, standing still is the furthest cell on the board — and by Appendix D
the cheapest one for the cop to seal, because a corner supplies two of the four
sides it needs for free. A distance-maximising thief walks into the one place
where capture costs two barriers instead of four, and reports the whole way
that it is doing well.

**Escape space could not fix it, because it never discriminates.** A move
changes only the thief's own cell, so every legal destination is one step away
and therefore in the thief's own connected component; reachable area is a
property of that component, so it returns the same number for every candidate.
A sweep of four thousand random positions found **zero** where it differed
([`test_reachable_area_cannot_separate_candidates_at_all`](tests/test_strategy.py)).
It had been the stated tie-break for two issues and had never once broken a
tie.

So the pure route is not merely weaker here. Its tie-break is a constant.

### What we built instead

**Local degree as the primary safety signal.** How many of a cell's four sides
are still open. This is the quantity Appendix D actually prices capture by —
two barriers in a corner, three on an edge, four in the open — so refusing
low-degree ground is refusing to make ourselves cheap to catch. It enters the
ranking twice: as a veto above distance, exempted when a cramped cell strictly
gains ground (a real escape is never refused), and as a preference below
distance, which closes the gap the exemption leaves.

**Reachable area over time rather than across candidates.** Barriers are
permanent, so the region can only shrink, and the *rate* it shrinks at is the
cop's containment plan becoming visible. When it is closing, degree is promoted
above distance: the cop does not need to enter a pocket it is sealing, only to
finish the wall, so distance bought inside one buys nothing. The timing matters
more than the magnitude — a region that is closing has a last moment at which
leaving is possible, and by the time the area is alarming that moment has
passed.

**`STAY` priced rather than free.** Survival, not distance, is the win
condition, so waiting is sometimes optimal. But emission puts τ at the occupied
cell every turn while decay removes only ρ, so a cell sat on becomes a beacon —
and a beacon is negative distance, since it is what converts the cop's search
into a heading. Consecutive turns held are charged against the distance term.

Every one of those is a heuristic. None is learned. What makes it *our own
algorithm* rather than the pure route is that the ranking is derived from
Appendix D's cost structure instead of from proximity.

### Why not reinforcement learning

Four reasons, in descending order of how much they actually decided it.

1. **The sample budget does not exist.** RL needs episodes in the thousands.
   We have a league of at most ten games per team against opponents whose
   policies differ, and a token budget of 200 000 per series. Self-play against
   our own cop would train against one specific opponent — the one we control,
   and the one we will never face.
2. **Determinism is a requirement, not a preference.** A match must replay
   exactly and a reported bug must reproduce; a learned policy makes the
   weights part of the reproduction, and the weights are not in the transcript.
3. **The rulebook makes it costlier.** RL was never taught in the course and is
   explicitly optional, and choosing it makes learning curves a *mandatory*
   README section — real work whose absence is a deduction.
4. **What is graded is the justification.** A heuristic we can defend cell by
   cell against Appendix D is worth more than a policy whose behaviour we can
   only describe statistically.

The seeded RNG is wired up and the seed is logged on every turn regardless, so
if an ε-greedy element is ever added it is reproducible from day one. Nothing
currently draws from that stream, and a test asserts so.

## 4. Learning curves

<!-- Required ONLY if reinforcement learning was used, as empirical evidence of
     policy convergence. If no RL was used, say so explicitly — RL is an
     optional tool that the course never taught. Source: ch. 6.                -->

**Not applicable.** Reinforcement learning is not used by this agent, for the
four reasons set out in section 3. The movement policy is deterministic and
algorithmic: identical state plus identical config yields an identical action,
verified across processes under four different `PYTHONHASHSEED` values as well
as across runs.

This section is mandatory only where RL was used. It is left in place, and
answered explicitly, rather than deleted — a missing section and a section
that says "we did not do this, here is why" read very differently to a
grader.

## 5. Screenshots

<!-- ABSOLUTE REQUIREMENT (Rulebook §9.4.2 item 5, Appendix C). Two images:
     (a) the Live GUI belief heatmap, evidencing genuine probabilistic inference
         under partial observation;
     (b) the Replay App displaying a green "Verified OK" stamp, evidencing that
         match integrity held.
     Produced by: PRD-7.                                                       -->

*Pending — produced by PRD-7.*

| View | Image |
| --- | --- |
| Live GUI — belief heatmap | *pending* |
| Replay App — `Verified OK` | *pending* |

## 6. Companion repository

**COP agent: <https://github.com/Mhmdabad/police_agent>**

The cross-link is mandatory in both directions: this README points at the cop
repository, and the cop README points back here. The Moodle submission carries
both links; the end-of-match JSON carries four (both teams, both roles).

---

## Documented rulebook contradictions

The rulebook grants academic freedom where it contradicts itself, provided the
report records **where** the contradiction was found, **what** was chosen, and
**why**. Quantitative values remain governed solely by Appendix F.

| # | Where | Choice made | Rationale |
| --- | --- | --- | --- |
| — | *none recorded yet* | — | — |

## Team

| Field | Value |
| --- | --- |
| Group identifier | `s82kma9e` |

<!-- TODO: member names and student IDs. The group identifier above is the
     8-character code used in every declaration and result JSON, and is what
     the lecturer uses to attribute automated reports to this group.       -->

*Member names to be completed.*

---

<sub>The rulebook and its transcription are © 2026 Dr. Yoram Segal / Gal
Technologies Artificial Intelligence Ltd., reproduced here for authorized
educational coursework.</sub>
