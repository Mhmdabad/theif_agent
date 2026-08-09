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

Stages 0–7 are complete: both agents run, expose the four MCP tools over a
tunnel, play a full Commit-Reveal match against each other, audit the
opponent's every step, and write the four mandatory artefacts. What remains is
league play and submission — matches against other teams, screenshots, and the
Moodle paperwork.

Progress is tracked as one GitHub issue per task, labelled by build stage
(`stage-0` … `stage-7`, `league`, `submission`, `final-checklist`).

| Stage | Scope | State |
| --- | --- | --- |
| 0 | Repository setup | complete |
| 1 | Base logic | complete |
| 2 | FastMCP infrastructure | complete |
| 3 | Strategy module | complete |
| 4 | Language and scent | complete |
| 5 | Cloud exposure | complete |
| 6 | Cryptography | complete |
| 7 | Reporting, GUI, replay | complete |
| — | League play and submission | in progress |

Every merge is gated on `ruff`, `ruff format`, `mypy --strict`, a 100 %-covered
test suite, and a cross-repository drift check that fails if a module shared
with the companion agent has diverged.

**Known limits, stated rather than discovered.** The Step-0 declaration reads
`"unsigned"` until the course issues the signing key. The verbal layer runs in
zero-token `template` mode by default, so `total_tokens` is 0 until the
`claude_api` provider is enabled. Neither is a defect; both are choices with a
reason, and the reasons are in [`docs/SECRETS.md`](docs/SECRETS.md) and
[`docs/prd/PRD-4-language-and-scent.md`](docs/prd/PRD-4-language-and-scent.md).

Planning documents: [`docs/PLAN.md`](docs/PLAN.md),
[`docs/TODO.md`](docs/TODO.md), [`docs/prd/`](docs/prd/README.md).
A transcription of the rulebook is in [`project-book/`](project-book/README.md).

## Running it

```bash
uv sync
```

### Serve — answer an opponent

```bash
python -m thief_agent serve
```

Binds `0.0.0.0` and exposes the four MCP tools. Runs happily without a tunnel,
because local development must not be conditional on ngrok.

### Check — before you commit to a match

```bash
PUBLIC_URL=https://ours.ngrok.io OPPONENT_URL=https://theirs.ngrok.io/mcp \
    python -m thief_agent check
```

Prints the port, the address we would advertise, the opponent, and the tool
names — and binds nothing. If it says *not publicly reachable*, **stop**:
announcing a loopback address means every call the opponent makes times out,
and a technical loss scores zero for *both* sides.

### Play — a whole match

```bash
PUBLIC_URL=https://ours.ngrok.io OPPONENT_URL=https://theirs.ngrok.io/mcp \
    python -m thief_agent play --game-id AGREED_ID --out artefacts
```

Handshake → agree the config digest → play the sub-games → audit the opponent →
write `declaration_`, `config_`, `log_` and `result_`. The `game_id` is agreed
with the opponent beforehand: both sides name their files from it.

**It sends nothing.** FR-7.16 requires both teams to agree the result before
either reports it, so the report is written with `result_agreed_with_opponent`
false and mailing it is a separate, deliberate act.

### The two windows

```bash
python -m thief_agent.ui.app live
python -m thief_agent.ui.app replay artefacts/log_<game_id>_g01.json
```

The live board never receives the opponent's true cell — `render()` has no
parameter for it. The Replay App stamps the log `Verified OK` or `TAMPERED`,
computed over the whole file rather than the step on screen.

### Authorising Gmail, once

```bash
python -m thief_agent.infra.authorize
```

See [`docs/GMAIL_SETUP.md`](docs/GMAIL_SETUP.md). A Testing-mode refresh token
expires after seven days; re-run this if the agent has been idle a week.

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

The race is a decentralised partially observable Markov decision process —
the octuple ⟨n, S, {Aᵢ}, P, R, {Ωᵢ}, O, γ⟩ of Rulebook ch. 1 — and every
component of that octuple is a concrete object in this repository rather than
a notational courtesy. What follows maps the formalism onto the code that
carries it.

**The state S exists nowhere.** S is the full picture: both positions, the
barrier layout, the accumulated scent field. No process holds it. The two
agents run as separate OS processes under separate configuration directories
(Appendix E rules 1–2), with shared memory and shared live modules forbidden
outright — which is what makes this a *Dec*-POMDP rather than two POMDPs that
happen to share a board. With no environment process to ask, the true state is
only ever the **agreement** between two local truths: established before the
series by the config digest (`runtime/orchestrator_config.py`), maintained
per turn by Commit-Reveal, and checked after the fact by mutual audit.
`BoardState` in `domain/board.py` is this side's local reconstruction of S —
frozen, because the Commit hash is taken over a specific snapshot — not a
window onto S itself.

**The thief's actions mix physics and psychology.** The physical action space
is five moves — `N`, `S`, `E`, `W`, `STAY` (`domain/actions.py`), diagonals
illegal, with `legal_moves` in the domain layer as the single source of
legality. The communicative action is the verbal hint: free natural language,
permitted to be a deliberate lie, composed by the bluff modules
(`domain/bluff.py` and its siblings). Even `STAY` is not a null action,
because emission continues while decay only fades — a cell sat on becomes a
beacon, which is why the strategy prices waiting rather than treating it as
free. The cop's barrier placements enter this repository only as declarations
to be verified, never as actions to be taken.

**The transition P is deterministic, and therefore must be shared.** With no
referee, two peers running different transition functions are playing
different games without knowing it. P is encoded in the shared configuration,
validated against Appendix F at startup, and agreed by SHA-256 digest at
negotiation — a mismatch is refused, not reconciled.

**R is the scoring table, verbatim** (`domain/scoring.py`): capture 20/5,
survival 5/10, technical loss 0/0. For this agent the gradient points at
survival — thirty-five valid steps at 10 points — and the 0/0 row is load-
bearing: it is why so much of section 2 below is about not deadlocking.

**The observation Ωₜₕᵢₑ𝒻 is the heart of the model.** Per turn the thief
observes exactly: its own position, the legality of its own candidates, the
opponent's disclosed scent field, and the opponent's hint. The cop's cell is
never in it. The Live GUI's `render()` has no parameter for the opponent's
true position — the observation model enforced as an API signature, not as a
promise.

**O is two witnesses of unequal honesty.** Scent is physics: emitted every
turn by presence itself, impossible to suppress or to plant elsewhere
(`domain/scent.py`), fading multiplicatively so that intensity encodes
recency (`domain/trail.py`), and re-derivable at audit from the revealed
movement history (`domain/scent_audit.py`) — noisy, but incapable of lying. A
hint is a claim (`domain/hints.py`): it may be true or a lie, so it enters
the update weighted by a reliability earned by checking past claims against
the trail (`domain/credibility.py`).

**The belief state is the posterior the formalism calls for.**
`domain/belief.py` maintains a normalised distribution over cells: uniform
over free cells as the honest prior, zero on barriers always, one Bayes step
per piece of evidence. Two of its invariants come straight from the model. A
cell the evidence does not mention is multiplied by one, not zero — silence
is absent information, not negative information. And reliability is applied
by flattening toward uniform rather than by scaling
(`domain/inference.py`), because the belief renormalises, so a uniformly
scaled likelihood has no effect and an unreliable hint would become
indistinguishable from a reliable one.

**γ appears structurally, not as a constant.** The thief's horizon is finite
and known — `survival_threshold` steps — and its future-regard lives in
`strategy/containment.py`: barriers only accumulate, so the reachable region
only shrinks, and the *rate* of shrinkage is the cop's plan becoming visible.
Reacting to how small the region is reacts too late by construction; reacting
to how fast it is closing is what the discount factor means here. The same
symmetry the rulebook calls *uncertainty as a resource* is this side's
weapon: the cop's Ω is just as blind, and the hint channel exists so the
thief can spend that blindness.

## 2. FastMCP orchestration dilemmas

<!-- Required: the development trade-offs around orchestrating communication
     between two mutually untrusted agents — turn management, handling network
     failures, and the roles of the Gatekeeper and Orchestrator patterns. The
     grader is looking for reasoning and rejected alternatives, not a
     description of the final code. Source: ch. 2, ch. 8. From: PRD-2, PRD-5.  -->

Ch. 2's architecture — every agent simultaneously server and client, no
referee anywhere — is one sentence to state and was most of the engineering
to build. Each dilemma below is one this codebase actually hit, the decision
taken, and why; the rejected alternative is stated because in most cases we
built it first.

### Async FastMCP under a synchronous match loop

`fastmcp.Client` is asynchronous. The retry and deadline logic decides
matches — a mishandled timeout is the technical loss that scores zero for
both sides — so it has to be testable without an event loop, and letting
`async` leak upward would mean every one of those tests needed one. The
decision, in `infra/mcp_transport.py`: the bridge lives in exactly one
module, each call runs its own loop start to finish, and nothing above that
line knows. The accepted cost is a fresh connection per call instead of a
session held open for the match. That is the right trade here: sub-games are
turn-based with seconds between messages, so connection setup is not the
bottleneck — and a long-lived session is precisely the thing that fails
silently when a tunnel restarts between sub-games, which the handshake
rotation in `infra/handshake.py` exists because it *does* happen.

### What a failure means, and which layer gets to say so

`infra/mcp_client.py` decides what a failure *means* — what is retried, when
the budget is spent, when a timeout becomes a technical loss — and it decides
by exception type, retrying `TimeoutError`, `ConnectionError` and `OSError`.
FastMCP throws that distinction away: a peer that is simply not there
surfaces as a bare `RuntimeError` reading *"Client failed to connect"*, which
would skip the retry budget entirely and crash the turn instead of becoming
the technical loss the rules define. Through a tunnel it is worse: the
connection *succeeds*, because ngrok is up and answers `502` on the absent
peer's behalf — an HTTP status error that is neither `OSError` nor
`RuntimeError`, so the retry logic was correct and unreachable. It worked in
every localhost test and could not work in the one situation it was written
for. The decision: translate exactly two things — connection failures become
`ConnectionError` with the original chained, and the `UPSTREAM_DEAD` gateway
statuses are recognised as an unreachable opponent, whatever layer says so —
and nothing else. A tool that answers badly answers with a value, and our own
`TypeError` is our own bug; neither deserves three retries before being
misreported as an absent peer.

### One gateway, when FastMCP wants tool functions everywhere

FastMCP's natural shape puts logic inside `@mcp.tool` handlers, which is a
short road to peripheral modules referencing each other — exactly what
Appendix E rule 3 forbids. The decision: the four exposed tools
(`negotiate`, `receive_turn`, `submit_audit`, `receive_control`) are dumb
mailboxes (`infra/inboxes.py`) that validate at the door, enqueue, and return
immediately; the runtime drains them through the `Orchestrator`
(`runtime/orchestrator.py`), the single entry point to every subsystem, which
coordinates and does not decide. The payoff is more than architectural
hygiene: accepting a message costs nothing, so a busy runtime never makes the
opponent's send time out, and an inbound message can never block on our
decision-making — which is where the language-model deadline lives. The
Gatekeeper (`infra/gatekeeper.py`) is the same pattern facing the other
direction, three gates in front of every API request, ordered cheapest and
most final first.

### Deadlines, the watchdog, and the deadlock nobody reports

In a P2P game a deadlock produces no error, no result, and 0/0 — for the
thief, thirty-five turns of successful evasion evaporating into nothing.
The decision is three layers answering three different questions. The
Deadline Tracker (`runtime/deadline.py`) asks *did this call take too long*:
every request carries an expiry, and a missed deadline is a failure, not an
invitation to wait longer. The Watchdog (`runtime/watchdog.py`) asks *is
anything still happening at all*, because the failures that kill matches are
rarely one slow request — a hung model or a transport that neither returns
nor errors trips no per-request timeout — and on a stall it persists state
and shuts down cleanly rather than losing the sub-game. The state machine
(`runtime/state_machine.py`) raises on any transition not in its table,
converting a logic bug into a development-time failure instead of a silent
in-match stall. The wiring between them was a dilemma of its own: client
retries feed the watchdog's heartbeat (`runtime/orchestrator.py`), because a
client patiently retrying a dead tunnel is otherwise silent for longer than
the watchdog's patience — a stall reported over a recovery that was working
exactly as designed.

### Starting up: two humans, two rooms, one deadline

Nothing guarantees the peers start together — the two people running these
commands are typing them in different rooms. Fail on the first `502` and the
faster team always aborts; wait indefinitely and the startup is itself a
deadlock. The decision, in `runtime/driver_startup.py`: announce repeatedly
for a 180-second patience window, and retry *only* the announcement. Once it
lands, a handshake failure is a real failure — an opponent who accepted our
greeting and then went quiet is a different problem from one who had not
started yet, and collapsing the two would hide the first. An opponent who
never appears raises `StartupTimeout`, named as such rather than surfacing
the transport's `502 Bad Gateway`, which describes a proxy and not the
situation — and it is not recorded as a technical loss, because no match ever
began.

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
| 1 | **Scent falloff shape.** Ch. 4.3 calls the emission a *radial distribution*; the reference implementation in [Appendix D's repository](https://github.com/rmisegal/Game-P2P-Cop-Chase) (`domain/smell.py`) uses **Chebyshev** distance, producing a square terrace whose entire 5×5 border shares one value. | The **PDF's Euclidean Gaussian**, σ = 1.15. Chebyshev is retained as a selectable model so a series against an opponent running the reference code costs a negotiation rather than a code change. | Figure 4 (p. 44) prints the whole field, and two of its numbers settle the shape without any fitting: `(1,2)` and `(2,1)` are **0.14** while `(2,2)` is **0.04**. Under Chebyshev all three are ring 2 and would be equal. The difference is the mechanism, not a detail — ch. 4.3 states the point of spreading at all is that a hill marks *direction* when the exact cell is missed, and a terrace of equal border values carries none. |
| 2 | **Decay rule.** Ch. 4.3 gives `τ(t+1) = max(0, (1−ρ)·τ(t) + Δτ)` — multiplicative. The same reference implementation subtracts: `τ − ρ`. | The **PDF's multiplicative rule**. One turn from 0.9 gives **0.810**, not 0.800. | The book states it four times over: the formula (p. 43), the prose gloss that the trail keeps *90% of its value* each turn (p. 43), the worked lie-detection example computing `(1−ρ)·0.9 ≈ 0.81` (p. 47), and the half-life of six-to-seven turns — true of `0.9ⁿ`, but `0.9 − 0.1n` crosses half at 4.5. Subtraction also decouples lifetime from strength, so a faint *old* trace and a faint *fresh* one become indistinguishable and intensity stops encoding recency. |
| 3 | **Enclosure capture.** Ch. 3 defines it as *"a thief imprisoned with no legal move at all"*, then parenthesises *"(all adjacent cells blocked by barriers and/or board edges)"*. Read literally, the first clause **never fires** — `STAY` survives any encirclement, so a thief always has a legal move. | The **parenthetical**: enclosure is decided over the four **adjacent** cells, and standing still is not an escape. | The literal reading makes the condition unreachable, which cannot be the intent of a rule the book prices at two barriers in a corner and four in the open. The parenthetical is the operative definition and is the only one under which Appendix D's arithmetic holds. |
| 4 | **Agreement key names.** Appendix B names the shared-config keys one way (`grid_size`, `max_barriers`, `pheromone_decay`); the reference repository's negotiation schema uses another (`board_size`, `barriers_max`, `decay_per_step`). | **The reference's key names on the wire, Appendix F's values inside them.** `shared/terms.py` translates between the two. | Key names are a transport detail and must match the opponent's parser or the handshake fails; values are governed by Appendix F, where a *fixed* parameter deviating disqualifies the team. Following the wire for names and the book for values satisfies both, and `test_values_come_from_appendix_f_not_the_key_names` pins the distinction. |
| 5 | **When the hint may be sent.** Ch. 5.3.2 puts an **Acknowledge** phase between Commit and Reveal, and states its purpose: the acknowledgement *"ensures the reveal happens only once both sides have already fixed their moves"*. The reference bundles commitment, hint and scent into a single `TurnMessage`, one round trip per turn. | The **PDF's four phases**, in `infra/ceremony.py`. The bundled `TurnMessage` shape is kept for an opponent who speaks only the reference dialect, so the difference costs a negotiation rather than a code change. | Under the bundled form, whichever peer sends second has read the first one's hint **before** choosing what to commit to — which is exactly the advantage the Acknowledge phase exists to remove. The two are not variants of one protocol: one of them contains the security property the chapter is about, and the other does not. |
| 6 | **Where the scent field travels, and whether anything binds it.** The rulebook puts the field in the environment and calls it unfalsifiable (ch. 4.4), but never says how a peer transmits one; the reference implementation ships it as `TurnMessage.smell_grid` **alongside the phase-1 commitment**, unbound and unchecked. | The field is disclosed in **phase 3**, sealed into the **phase-1 SHA-256 commitment**, and re-derived at the final audit from the agreed start and the revealed movement history. `domain/scent_audit.py` does the reconstruction; a peer that cannot bind its field is refused, explicitly and before the series, through the `binding` term in the pre-series scent lock. | Two separate problems, and the reference form has both. A fresh emission peaks on the emitter's own cell, so a field sent with the commitment discloses the exact position that commitment exists to conceal. And an unbound field can be chosen *after* reading the opponent's reveal — which makes "the scent cannot lie" false, since the field is now just another claim. Sealing it fixes the second; holding it to phase 3 fixes the first; and neither is enough on its own, because a sealed field can still be a field the physics could never have produced. Only re-deriving the trail turns *a hint may lie, a trail may not* into a property of the protocol rather than an aspiration about it. |

Entries 1, 2, 4, 5 and 6 are divergences between the rulebook and the reference code
published alongside it. In each case the **PDF is treated as authoritative** —
its own header states that the source PDF governs and that Appendix F is the
sole authority for quantitative parameters. The reference implementation is
treated as one more implementation we may have to negotiate against, not as a
standard.

Entry 6 is the one place this project **declines** the reference dialect outright rather
than keeping it as a negotiable alternative. There is no way to accept unbound scent that
does not give up both the secrecy of our position and the evidence the belief map is built
on, so the fallback is a series played with **no scent at all**, agreed in advance — never
a series played with scent nobody can check.

Entries 1 and 2 are both **hash-locked before a series** (see the pre-series
scent lock), so a disagreement surfaces at negotiation rather than mid-match.

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
