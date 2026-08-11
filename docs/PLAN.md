# PLAN — THIEF Agent (גנב)

**Project:** Distributed Cops-and-Robbers over a Peer-to-Peer Network
**Course:** Orchestration of AI Agents — CS Dept., University of Haifa, 2026
**Rulebook:** `police_thief_p2p.pdf`, book version 3.0.0 (Dr. Yoram Reuven Segal)
**This repo:** THIEF agent (GitHub: `theif_agent`). Companion repo: **COP agent** — [police_agent](https://github.com/Mhmdabad/police_agent)

---

## 1. What we are building

Two **symmetric, autonomous agents** — a COP and a THIEF — race each other on a
discrete grid **with no central server and no referee**. Neither agent sees the
true world state. Each builds a *belief* about its opponent's position from
(a) a decaying **scent map** the opponent cannot fake, and (b) a **verbal hint**
that may be a deliberate lie.

Formally this is a **Dec-POMDP** (Decentralized Partially Observable Markov
Decision Process). Practically it is a P2P network where each agent is
*simultaneously an MCP server and an MCP client* over **FastMCP**, and where
integrity is enforced by **Commit-Reveal over SHA-256** instead of by a judge.

This repository contains **only the THIEF**. The COP lives in a separate repo and
must run as a **completely separate process with a separate config directory**
(`config/thief/` here, `config/police/` there). Sharing memory, importing a
module that holds live state, or reading shared variables between the two sides
**disqualifies the solution** even if the game "works" technically
(Rulebook §2.4.2, Appendix E rules 1–2).

### The THIEF's asymmetric position

| | COP | **THIEF (this repo)** |
|---|---|---|
| Goal | Land on the thief's cell and claim capture | **Survive `survival_threshold` valid steps without being captured** |
| Special power | May place a barrier (forfeiting movement) | **None — pure evasion and deception** |
| Best score | 20 (capture) | **10 (survival)** |
| Consolation | 5 (thief survives) | 5 (thief captured) |
| Start (default) | corner `[0,0]` | **centre `[3,3]`** — maximum escape routes |

The thief has no board-shaping power, so its edge must come from three places:
**belief accuracy** (knowing where the cop is before the cop knows where we are),
**barrier-aware path planning** (never letting the cop's wall close around us),
and **the verbal game** (hints that mislead without contradicting our own scent
trail — the environment cannot be faked, so a clumsy lie *reveals* us).

---

## 2. Architectural shape

```
                    ┌──────────────────────────────┐
                    │      Orchestrator            │  single gateway;
                    │      (Gateway)               │  coordinates, never decides
                    └───┬───┬───┬────┬─────┬───────┘
                        │   │   │    │     │
        ┌───────────────┘   │   │    │     └──────────────┐
        ▼                   ▼   ▼    ▼                    ▼
  MCP Connector     Decision Module  Log Manager   Deadline Tracker   Watchdog
  (FastMCP          (Strategy:       (Commit-      (per-request       (heartbeat,
   server+client)    belief, move,    Reveal log,   expiry, retry)     controlled
                     hint)            audit)                           shutdown)
```

Hard rules that shape this design (Appendix E):

- The **Orchestrator is the single entry point** to every subsystem; no
  peripheral module drives another — cross-subsystem control flow goes through
  the Orchestrator (rule 3). Passive reads of a lower layer (`domain`,
  `shared`, or the ceremony state the banner renders) are not that traffic.
- Game phases run through a **strict state machine**; illegal transitions are
  rejected immediately (rules 4–5).
- **Deadline Tracker** on every MCP request and a **Watchdog** over the main loop
  (rules 6–7). A missed deadline is a *failure*, not an invitation to wait longer.
- The **Live GUI shows local truth only** — never a bird's-eye view of the real
  board (rules 8–9).
- The server is exposed to the public internet through a **tunnel** (rule 10);
  `localhost` is allowed only during early coding.

### Game-turn state machine

```
WAITING_FOR_OPPONENT → COMPUTING_MOVE → COMMITTING → AWAITING_REVEAL → VERIFYING
        ▲                                                                   │
        └───────────────────────────────────────────────────────────────────┘
              (any communication phase may exit to TECHNICAL_LOSS)
```

`TECHNICAL_LOSS` is terminal and scores **0 for both sides** — which is why
protocol hygiene matters more than winning a single board.

### Strategy module boundary

The strategy module plugs into the `PeerRuntime` at exactly one point:
**after decoding the incoming hint, before packing the outgoing Commit.**

```
incoming hint + scent → hint decode → belief update (Bayes)
                                            ↓
Commit pack (out)  ←  LLM bluff text  ←  move choice (algorithmic)
```

**The LLM never chooses the move.** LLMs hallucinate in Cartesian space — they
confuse directions, distances and coordinates, and will confidently return an
illegal or suicidal move (Rulebook §6.5). The LLM writes text and profiles the
opponent's language; the algorithm owns every spatial decision. (An LLM-driven
move policy is permitted *only* by explicit, documented mutual agreement of both
teams — and even then the local algorithm must still reject illegal moves.)

---

## 3. Movement policy — our choice

The book offers three **equal-standing** options for the move policy:

1. **Pure heuristics** — Bayesian belief map + Manhattan distance. Deterministic,
   transparent, easy to debug, frequently competitive. *Reference default.*
2. **Your own heuristic algorithm** — belief + scent + barrier awareness +
   lookahead (minimax / expectimax against the opponent's belief).
3. **Reinforcement learning (Q-Learning / Bellman)** — explicitly **optional**;
   the course never taught RL and a winning agent can be built without it.

**Our plan: start with (1), graduate to (2).** Stage 3 ships a pure
belief + Manhattan policy that *maximises* distance to `argmax b(s)` (the mirror
of the cop's minimisation). Stage 4+ upgrades it to a thief-specific evasion
policy:

- **Escape-space heuristic:** prefer the legal move that maximises the number of
  reachable free cells (flood-fill), not merely raw Manhattan distance. A thief
  that runs "away" into a pocket the cop is walling off loses.
- **Barrier-corridor avoidance:** track every declared barrier; penalise moves
  into regions whose reachable area is shrinking turn over turn.
- **Centre bias under uncertainty:** when belief about the cop is flat, drift
  toward high-degree cells (many open neighbours) rather than edges/corners.
- **Patience:** survival, not distance, is the win condition. Staying still is a
  legal move and sometimes the best one — it also re-emits scent at the current
  cell, which is a *cost* we must weigh.

RL, if we get there at all, is a stage-8 stretch goal and will be documented with
learning curves in the README (mandatory if used — §9.4.2 item 4).

---

## 4. Scent (stigmergy) — the un-fakeable channel

Every time an agent moves or stays, it emits a **5×5 scent field** centred on its
cell with intensity `0.9` at the centre, falling off radially. After every *full*
turn (cop + thief both moved) all scent decays:

```
τ_ij(t+1) = max(0, (1 − ρ)·τ_ij(t) + Δτ_ij)      with ρ = 0.10
```

Each side reads **the opponent's** scent field, never its own. With ρ = 0.10 a
single deposit stays above half-peak for roughly six to seven turns — long enough
to be tactically useful, short enough not to saturate the board.

**Consequence for the thief, stated bluntly:** our trail is public and cannot be
forged. Any hint that contradicts our own scent mass hands the cop a
high-confidence lie detection *and* a bearing. Deception must therefore be
*consistent with the physics* — misdirect about intent and timing, not about a
position the environment already betrays.

Before a series starts, both teams must exchange the full emission/decay model
**with a concrete numeric example** and lock the agreement cryptographically
(SHA-256 of the formula + example). Sharing the actual scent-engine code with the
opponent is explicitly permitted and recommended (Rulebook §4.5).

---

## 5. Integrity — Commit-Reveal over SHA-256

Four mandatory phases per step:

1. **Commit** — send only
   `H = SHA256(State ‖ Move ‖ Intent ‖ Nonce)`.
   Serialisation is **canonical JSON** (`sort_keys=True`, `separators=(",",":")`)
   so both peers hash byte-identical input. `Intent` is a flag declaring in
   advance whether the accompanying hint is `truth` or `lie` — you cannot claim
   afterwards that you "meant" to lie. `Nonce` is `secrets.token_hex(16)`
   (never `random`).
2. **Acknowledge** — opponent confirms it is locked on our commitment.
3. **Reveal** — send `Move` + hint. **The nonce stays secret.**
4. **Final Reveal / Audit** — at end of match, all nonces are revealed; each side
   recomputes the other's hashes.

Any mismatch is **proof of tampering** — no interpretation, no statistical doubt.
The cheating team takes a **technical loss (0 points)** regardless of the board.
The same applies to a false capture answer: when the cop claims a capture, the
thief is under a **cryptographic obligation to answer truthfully**. Denying a real
capture is caught at audit and disqualifies us (Appendix E rules 21–22).

**Step-0** (before move 1): both sides publish a signed hardware declaration —
OS, CPU cores/frequency, RAM, GPU/VRAM, LLM model name — plus code version, team
name, sub-game number, and **the exact GitHub commit hash being played**. Code may
change between matches; the commit hash must be re-declared every match so the
grader can reproduce the version that actually competed.

---

## 6. Configuration — the shared constitution

Two files, two purposes (Appendix B):

| File | Format | Scope | Signed? |
|---|---|---|---|
| `config/game.json` | JSON | **Shared**, byte-identical on both peers: board, movement, scoring, pheromones, network/league, rate limiter | **Yes** (`config_sha256`) |
| `config/thief/game.toml` | TOML | **Private**: my port, opponent URL, strategy class, LLM/trash-talk provider, email target, team identity | No |

Decision test: *"must the opponent agree to this value, or rely on it?"* → JSON.
Otherwise → TOML. When both exist, **JSON overrides TOML** for any shared key, so a
private file can never weaken a signed condition.

The negotiated contract is a **floor, not a ceiling**: parameters marked
*minimum* may be raised by mutual agreement but never lowered; *fixed* parameters
may not change at all; *negotiable* parameters are free. Any deviation from a
*fixed* value disqualifies the team.

### Binding defaults (Appendix F — single source of truth)

```jsonc
{
  "schema_version": "1.2",
  "agreed_between": ["group-a", "group-b"],
  "board_and_agents": {
    "grid_size": 7,               // minimum
    "num_agents": 2,              // fixed
    "thief_start": [3, 3],        // negotiable
    "cop_start": [0, 0],          // negotiable
    "axis_origin_corner": "top-left",
    "axis_start_index": 0
  },
  "world": { "map_area": "New York", "hint_max_words": 15 },
  "movement_and_barriers": {
    "move_set": ["N","S","E","W","STAY"],   // fixed — no diagonals
    "max_barriers": 14,           // minimum
    "max_moves": 35,              // minimum
    "survival_threshold": 35      // minimum — OUR win condition
  },
  "scoring": {                     // all fixed
    "capture_cop": 20, "capture_thief": 5,
    "survival_cop": 5, "survival_thief": 10,
    "tie_score": 2, "technical_loss": 0
  },
  "pheromones": {                  // all fixed
    "pheromone_center_intensity": 0.9,
    "pheromone_decay": 0.10,
    "pheromone_grid_size": 5
  },
  "network_and_league": {
    "response_timeout_sec": 30, "watchdog_timeout_sec": 60,
    "num_games": 1, "diversity_reward": 10,
    "min_games_to_pass": 2, "max_games_per_team": 10,
    "token_budget_per_series": 200000
  },
  "rate_limiter_gatekeeper": {
    "requests_per_minute": 30, "concurrent_requests": 2,
    "retry_backoff_sec": 5, "max_retries": 3, "queue_depth": 100
  }
}
```

A full league series against one opponent is **6 sub-games**; `num_games: 1` is the
single-sub-game demo default. Each config file must be **named per match** and
committed to this repo so any match is reproducible.

---

## 7. Build order — seven layers, seven PRDs

Incremental delivery: each layer runs **end-to-end** before the next is laid on
top, so at any moment the space of possible faults is confined to the newest
layer. Skipping ahead to crypto or the cloud does not save time — it doubles it.

| Stage | PRD | Builds | Rulebook |
|---|---|---|---|
| 1 | [PRD-1](prd/PRD-1-base-logic.md) | Grid, movement rules, barriers, capture detection — one process | Ch. 3 |
| 2 | [PRD-2](prd/PRD-2-mcp-infrastructure.md) | FastMCP servers + geometric tools over localhost | Ch. 2 |
| 3 | [PRD-3](prd/PRD-3-blind-strategy.md) | Blind strategy module (full information, no fog) | Ch. 6 |
| 4 | [PRD-4](prd/PRD-4-language-and-scent.md) | Natural-language hints, scent emission/decay, belief map, LLM bluffing | Ch. 4, 6 |
| 5 | [PRD-5](prd/PRD-5-tunneling.md) | Public URLs via ngrok / Localtonet, remote play | Ch. 2 |
| 6 | [PRD-6](prd/PRD-6-crypto-commit-reveal.md) | Commit-Reveal, nonce generator, Step-0 declarations, audit | Ch. 5 |
| 7 | [PRD-7](prd/PRD-7-reporting-and-gui.md) | Gmail API over OAuth 2.0, Live GUI, Replay App | Ch. 9, 7, App. A |

Milestone gate for each stage: **behaviour observed end-to-end**, not "code
written". See [TODO.md](TODO.md) for the checkable form of each gate.

---

## 8. League participation

- Minimum to pass: **2 counted matches against different teams**. Maximum: **10**.
- **One counted match per opponent.** Warm-ups that are not counted are allowed
  and encouraged.
- At the start of every match each team **declares how many counted matches it
  has already played**; the diversity incentive is weighted from those mutual
  declarations. A false declaration discovered at grading **disqualifies the team**
  — and since both sides email their reports, the lecturer always knows the truth.
- At the end of every legal match both teams must **agree on the result** and each
  team **sends its own JSON report** to `rmisegal+uoh26finalgame@gmail.com`. If one
  side does not report, that side gets no points — even if it won on the board.
  Contradictory reports void the match and score 0 for both.
- **Computational fairness:** the league normalises for hardware. A lean algorithm
  on a modest laptop scores better than a wasteful one on a server farm. This is a
  direct argument for the zero-token `template` bluff provider (or local Ollama)
  and a tight, deterministic move policy.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tunnel drops mid-turn → deadlock | Deadline Tracker on every request + Watchdog; controlled shutdown with state persistence rather than silent freeze |
| Config drift between peers | Exchange `config_sha256` before move 1; refuse to play on any mismatch |
| Scent formula interpreted differently | Lock the model + a numeric example by hash pre-series; offer the opponent our scent-engine code |
| LLM latency/blocking stalls a turn | `step_deadline_seconds = 30` hard cap; fall back to `template` provider; `every_n_steps` throttling |
| Gmail 429 / account suspension | Gatekeeper: Quota Manager → Token Bucket → DOS Detector; honour 429 with back-off, never retry blindly |
| Secret leak (`credentials.json`, `token.json`) | `.gitignore` before first commit; a leaked secret is permanently compromised — rotate in the console |
| Hint contradicts our own scent trail | Hint generator is fed the belief + our own emitted field; reject hints inconsistent with physics |
| Over-fitting to one opponent | Warm-up matches against varied strategies; never tune to a single adversary |

---

## 10. Definition of done

- [ ] Base logic runs a full race without crashing; scoring enforced correctly.
- [ ] FastMCP P2P over a **public URL**, not just localhost.
- [ ] Commit-Reveal active; full audit completes with no tampering detected.
- [ ] Scent map and belief map computed **and actually influencing decisions**.
- [ ] Live GUI + Replay App showing `Verified OK`.
- [ ] Gmail JSON reports sent **by both sides** after each match.
- [ ] GitHub repo accessible to the lecturer, annotated tag `v1.0-submission` pushed.
- [ ] README academic report complete (6 mandatory items) with screenshots.
- [ ] Cross-link to the cop repo present in the README.
- [ ] `.gitignore` verified: no secrets in history.
- [ ] ≥ 2 counted matches against different teams.

---

## 11. Reference material

- Reference implementation (study only, **not** a submission skeleton):
  <https://github.com/rmisegal/Game-P2P-Cop-Chase>
- Lecturer (general / repo sharing): `rmisegal@gmail.com`
- Agent report target (mandatory): `REPORT_RECIPIENT` in `.env`, no default
- Where the book and the reference repo disagree, **the book and Appendix F win**.
