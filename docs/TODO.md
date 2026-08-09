# TODO — THIEF Agent (גנב)

Ordered task list mirroring the seven PRD stages. **A stage is done when the
behaviour has been observed end-to-end — not when "the code is written".** Do not
open stage *n+1* before every gate in stage *n* is ticked.

Legend: `[ ]` open · `[~]` in progress · `[x]` done · **🚪 GATE** = milestone

> **Status: stages 0–7 are built and tested; league play and submission are
> what remain.** This matches the Status table in `README.md`. The open boxes
> below are the honest remainder: real-tunnel latency figures, two counted
> matches against other teams, screenshots, team member names, the submission
> tag, the Moodle paperwork, and the two Stage-4 wiring gaps recorded there.

---

## Stage 0 — Repository setup

- [x] `README.md`: academic report skeleton + **cross-link to the cop repo**
- [x] `.gitignore` **before the first commit**: `credentials.json`, `token.json`,
      `*.env`, `config/**/secrets*`, `token*.json`
- [ ] Repo made accessible to the lecturer (public, or private + shared with `rmisegal@gmail.com`)
      — cannot be verified from the working tree; confirm on GitHub
- [x] `config/` directory with `game.json` (shared) and `thief/game.toml` (private)
- [x] Python project scaffold (`uv` / `pyproject.toml`), `pytest` wired up
- [x] Branch-per-feature workflow agreed; merge to main only when stable
      (`CONTRIBUTING.md` — branch per issue, squash merge)
- [x] 8-character group identifier (no spaces) chosen and recorded (`s82kma9e`)

---

## Stage 1 — Base Logic → [PRD-1](prd/PRD-1-base-logic.md)

- [x] `BoardState` model (immutable), `Position`, `Move` types
      (`domain/board.py` — frozen dataclasses)
- [x] Coordinate system: origin `top-left`, index from `0`, both configurable
      (`domain/axes.py`)
- [x] `legal_moves()` — N/S/E/W/STAY, **no diagonals**, no barriers, no off-board
      (`domain/rules.py`)
- [x] Transition function returning a new state (`rules.apply_move`)
- [x] Barrier model: irreversible, impassable for both, quota `max_barriers` = 14
      (`domain/actions.py`)
- [x] Capture: coordinate overlap (`domain/outcome.py`)
- [x] Capture: **barrier placed on the thief's cell** (`outcome.is_trapping_capture`)
- [x] Capture: **thief with no legal move at all** (`outcome.is_enclosure_capture`)
- [x] Survival: `survival_threshold` = 35 valid steps → 5/10 scoring
- [x] Technical loss → 0/0 (`outcome.technical_loss_scores`)
- [x] Scoring table wired from config (capture 20/5, survival 5/10, tie 2)
      (`domain/scoring.py`, values via `shared/appendix_f.py`)
- [x] Config loader + **Appendix F validator** (fixed = exact, minimum = ≥)
      (`shared/config.py`, `shared/config_validation.py`, `shared/appendix_f.py`)
- [x] Per-match config naming `config_<game_id>_g<NN>.json` (`shared/naming.py`)
      — committing one per counted match is still open, see Submission
- [x] Tests: legality, quota, both capture variants, survival, scoring
      (`tests/test_rules.py`, `test_scoring.py`, `test_stage1_acceptance.py`)
- **🚪 GATE:** two agents move legally on the grid; over-quota barrier rejected;
  coordinate overlap triggers capture; a full race runs to termination

---

## Stage 2 — FastMCP Infrastructure → [PRD-2](prd/PRD-2-mcp-infrastructure.md)

- [x] FastMCP server instance, `mcp.run(transport="http", host="0.0.0.0", port=my_port)`
      (`infra/mcp_server.py`)
- [x] Client engine calling the opponent's tools at `opponent_url`
      (`infra/mcp_client.py`, `infra/mcp_transport.py`)
- [x] Tools: `handshake`, `negotiate_config`, `receive_move`, `get_state_digest`, `ping`
      — shipped as four tools instead: `negotiate` (greeting, config digest, scent
      lock and result claim all arrive here), `receive_turn`, `submit_audit`,
      `receive_control` (`infra/inboxes_keys.py:TOOL_NAMES`)
- [x] Input validation on every tool — never trust an unverified move
      (`infra/validation.py`, `validation_shapes.py`)
- [x] **Orchestrator** as single gateway to all five subsystems
      (`runtime/orchestrator*.py`)
- [x] `GamePhaseMachine` with the transition table; illegal transition raises
      (`runtime/state_machine.py`)
- [x] **Deadline Tracker**: timestamp + expiry on every request, controlled retry
      (`runtime/deadline.py`)
- [x] **Watchdog**: heartbeat monitor, state persistence, controlled shutdown
      (`runtime/watchdog.py`)
- [x] Turn scheduler with strict alternation (`runtime/scheduler.py`)
- [x] **Separation audit**: cop and thief in separate processes, separate config
      dirs, zero shared memory/modules/variables (`tests/test_separation_audit.py`)
- [x] Tests: illegal transition, opponent killed mid-turn, watchdog freeze
      (`tests/test_stage2_resilience.py`)
- **🚪 GATE:** a geometric message from agent A over localhost is received and
  parsed correctly by agent B

---

## Stage 3 — Blind Strategy → [PRD-3](prd/PRD-3-blind-strategy.md)

- [x] `ThiefBrain(BrainBase)` with `_pick_move`, selectable via `[strategy] thief_class`
      (`strategy/thief_brain.py`, `strategy/loader.py`)
- [x] Insertion point verified: after hint decode, before Commit pack
      (`runtime/subgame_commit.py`; `tests/test_driver_strategy.py`)
- [x] Manhattan distance evaluation; **maximise** distance to the cop
      (`strategy/thief_brain_geometry.py`, `thief_brain_ranking.py`)
- [x] Flood-fill escape-space tie-break (avoid dead-ends)
      (`domain/search.py`, `strategy/containment.py`)
- [x] Open-neighbour / corner-aversion penalty (`MIN_OPEN_NEIGHBOURS`)
- [x] Barrier-aware reachability tracking (`strategy/containment.py:ContainmentTracker`)
- [x] `STAY` treated as a first-class candidate (ranked with a linger cost)
- [x] Legality guard: policy output re-validated against `legal_moves()`
      (`strategy/base.py:_guard`)
- [x] Determinism: seeded randomness, seed logged (`tests/test_determinism.py`)
- [x] Decision on movement policy route recorded for the README (heuristic / own
      algorithm / RL) with justification (`README.md` section 3, and section 4
      states explicitly that RL was not used)
- [x] Tests: never-illegal property test; dead-end regression board; determinism
      (`tests/test_stage3.py`, `tests/test_determinism.py`)
- **🚪 GATE:** given a known target position, the agent computes and executes the
  optimal evasive path with no manual intervention

---

## Stage 4 — Language & Scent → [PRD-4](prd/PRD-4-language-and-scent.md)

- [x] 5×5 radial scent emission, centre τ = 0.9 — emitted by the live match loop
      on **every** action, `STAY` and barrier turns included
- [x] Decay `τ(t+1) = max(0, (1−ρ)τ(t) + Δτ)`, ρ = 0.10, at end of each **full** turn
- [x] Sample **opponent's** field only; never our own
- [x] Fixture test against hand-computed decay values
- [x] **Pre-series lock**: exchange emission/decay model + numeric example, hash it
      — `Orchestrator.agree_scent_model` offers it through `negotiate` and refuses
      the series on any disagreement; `MatchRunner.agree` runs it after the config
      digest and no sub-game opens without one
- [x] Offer our scent-engine code to the opponent (permitted and recommended)
      — `SOURCE_OFFER` travels in the lock message, outside the digest
- [x] Belief map `b(s)` over the grid; zero belief on barriers, updated from the
      opponent's field at the full-turn boundary
- [x] Scent snapshot transmitted in **phase 3** and sealed into the **phase-1**
      SHA-256 commitment; a field edited after the commit fails verification
- [x] Final audit re-derives the opponent's trail from the agreed start and the
      revealed movement history; an impossible, malformed, non-finite, negative,
      out-of-range or over-limit field is an audit failure
- [x] Fail-closed: a peer that cannot bind its scent is refused rather than
      believed — unverified scent is never absorbed
- [x] Bayes update combining scent evidence + hint, with reliability coefficient
      (`domain/inference.py:update(claim=…, reliability=…)`)
- [x] Adaptive reliability: lower on each detected contradiction
      (`domain/credibility.py:Credibility.observe`)
- [x] Lie detector: expected-vs-measured scent contradiction (reproduce book example)
      (`domain/credibility_verdict.py`; `tests/test_credibility.py` reproduces PDF p. 47)
- [x] Handle split probability mass (two foci) without oscillating
      (`domain/foci.py:Commitment`, `foci_clusters.py`)
- [x] Natural-language hint parser (**no numeric-coordinate protocol** — forbidden)
      (`domain/hints.py`, `CoordinateProtocolError`)
- [x] Hint generator with `hint_max_words` = 15 cap and `map_area` landmarks
      (`domain/hints_lexicon.py:LANDMARKS`, `domain/bluff_phrasing.py`)
- [x] **`Intent` flag** (`truth`/`lie`) chosen before sending (`domain/bluff_intent.py`)
- [x] **Self-consistency guard**: reject any hint contradicting our own emitted field
      (`domain/bluff_vetting.py`)
- [x] LLM providers: `template` (default, 0 tokens), `ollama`, `claude_api`, `claude_cli`
      (`domain/providers.py:Bluffer`)
- [x] `every_n_steps` throttle; `step_deadline_seconds` = 30 cap with template fallback
      (`domain/budgeting.py:Ration`)
- [x] Token metering (`infra/token_ledger.py`)
- [ ] **Wire the received hint into the belief.** `runtime/subgame.py` stores
      `received_hints`, but nothing reads them: `subgame_scent._observe` calls
      `inference.update` with the scent field only. Parse the hint, run it past
      `Credibility`, and pass it as `claim=` / `reliability=`.
- [ ] **Wire the hint generator into the live loop.** `strategy/base.py:_hint`
      returns a constant string, so `Intent`, `bluff_vetting`, `Bluffer`, `Ration`
      and `TokenLedger` never execute during a match.
- **🚪 GATE:** free-language report → inference; scent map updates and decays each
  step; LLM produces a hint (truth or lie) within the word cap
  — *scent half observed end-to-end; the verbal half is module-complete but not
  yet on the live path (the two boxes above).*

---

## Stage 5 — Cloud Exposure → [PRD-5](prd/PRD-5-tunneling.md)

- [x] ngrok / Localtonet tunnel exposing the FastMCP server publicly
      (`infra/tunnel.py`, `tunnel_ngrok.py`; real URLs recorded in
      `artefacts/declaration_warmup-01.json`)
- [x] Public URL exchanged in handshake, recorded in the declaration file
- [x] `opponent_url` switched from localhost to the public tunnel URL
      (`OPPONENT_URL` / `PUBLIC_URL` override the private config — see `docs/TUNNELING.md`)
- [x] Re-handshake path for a changed tunnel URL between sub-games
- [ ] Latency measured; `response_timeout_sec` justified against real round-trips
      — `infra/latency.py` and `docs/LATENCY.md` are ready, but the measurement
      table still reads *Not yet measured* and `justify()` reports `UNJUSTIFIED`
- [x] Retry policy applied to transport failures only — never to re-send a move
      (`infra/mcp_client_retry.py`)
- [x] Transport event logging (connect / timeout / retry / reconnect)
      (`infra/transport_log.py`)
- [x] Tunnel-drop test → controlled technical result, no hang
      (`tests/test_stage5_tunnel_drop.py`)
- **🚪 GATE:** an agent on a **remote machine** connects via ngrok and plays a full
  round against the local agent

---

## Stage 6 — Cryptography → [PRD-6](prd/PRD-6-crypto-commit-reveal.md)

- [x] Nonce generator: `secrets.token_hex(16)` (**never** `random`) (`domain/crypto.py`)
- [x] Canonical JSON serialisation (`sort_keys=True`, `separators=(",",":")`)
- [x] `H_commit = SHA256(State ‖ Move ‖ Intent ‖ Nonce)` over the full step record
      (`domain/crypto_record.py:step_record`, `crypto.commit_of`)
- [x] Phase 1 Commit — hash only crosses the wire (`infra/ceremony_commit.py`)
- [x] Phase 2 Acknowledge — opponent confirms lock (`infra/ceremony_ack.py`)
- [x] Phase 3 Reveal — move + hint, **nonce stays hidden** (`infra/ceremony_reveal.py`)
- [x] Phase 4 Final Reveal / Audit — all nonces at end of match (`infra/ceremony_final.py`)
- [x] Verification with `secrets.compare_digest`; mismatch ⇒ `TECHNICAL_LOSS`
- [x] Append-only log `log_<game_id>_g<NN>.json` with commit/reveal/nonce per step
      (`infra/match_log.py`)
- [x] **Truthful capture answer** computed directly from `BoardState`, no dishonest branch
      (`domain/outcome.py:capture_answer` / `answer_is_supported`)
- [x] `Step-0`: OS, CPU cores/freq, RAM, GPU/VRAM, LLM model name
      (`infra/step_zero_hardware.py`)
- [x] `Step-0`: code version, team name, sub-game number, **GitHub commit hash**
      (`infra/step_zero_provenance.py`)
- [x] Step-0 declaration signed with the pre-supplied key
      (`infra/step_zero_signing.py`; the field reads `"unsigned"` until the course
      issues the key — a deliberate refusal to fake a signature)
- [x] Token consumption metered and cryptographically locked
      (`infra/token_ledger.py:seal` / `commit` / `disclose`)
- [x] Cross-implementation fixture test: both peers hash byte-identical payloads
      (`tests/test_interop_fixture.py`, `tests/fixtures/`)
- [x] Tests: corrupted reveal detected; nonce never leaked early; audit passes clean
      (`tests/test_stage6_acceptance.py`)
- **🚪 GATE:** a move is committed then revealed with a valid nonce; Step-0 verifies
  hardware and commit hash on both sides

---

## Stage 7 — Reporting & Visualization → [PRD-7](prd/PRD-7-reporting-and-gui.md)

### GUI
- [x] Live GUI (Tkinter/PyQt) showing **local truth only** — no bird's-eye view
- [x] Belief heatmap bound to the real belief object (deeper red = higher probability)
- [x] Turn banner: green `YOUR TURN` / grey `LOCKED`, with input lock after Commit

### Replay
- [x] Replay App loading `log_<game_id>_g<NN>.json`, step forward/backward
- [x] Per-step SHA-256 re-computation vs stored commitment
- [x] Green `Verified OK` / red `TAMPERED`; abort and void on first failure
- [x] Hand-tampered log test triggers `TAMPERED`

### Gmail + Gatekeeper
- [x] Google Cloud project + Gmail API enabled
- [x] OAuth Consent Screen configured, team members added as Test Users
- [x] Scope restricted to `https://www.googleapis.com/auth/gmail.send` **only**
- [x] OAuth Client ID (Desktop Application) → `credentials.json` **(gitignored)**
- [x] First authorization flow → `token.json` **(gitignored)**
- [x] **Quota Manager** — daily safety threshold
- [x] **Token Bucket** — 30 rpm, 2 concurrent, 5 s backoff, 3 retries, queue 100
- [x] **DOS Detector** — anomaly lock (backpressure / circuit breaker)
- [x] 429 handling: honour, back off, wait for next window — never blind retry
- [x] Report sent as **structured JSON attachment**, never free plaintext
- [x] Destination hard-coded: `rmisegal+uoh26finalgame@gmail.com`
- [x] Send-storm simulation blocked before reaching the API
- [x] `report --send` command reaching the mail pipeline, dry-run by default
      (`cli_report.py`, `cli_report_send.py`)

### JSON artefacts
- [x] `declaration_<game_id>.json` — teams, members, **4 repo URLs**, MCP addresses,
      hardware, LLM model, token ceiling, start/end times
- [x] `config_<game_id>_g<NN>.json` — locked agreed parameters
- [x] `log_<game_id>_g<NN>.json` — full step record
- [x] `result_<game_id>.json` — per-sub-game and aggregate scores, commit hashes,
      total tokens
- [x] Shared `game_uid`, names derived from `game_id`
- **🚪 GATE:** match summary sent via Gmail; GUI displays state; Replay App
  reconstructs a recorded round with `Verified OK`

---

## Repository hygiene gates (CI)

- [x] 150-line file budget enforced unconditionally in CI
      (`scripts/check_line_limit.py`, no exemption list)
- [x] Tracked-file secret scan enforced unconditionally in CI
      (`scripts/secret_scan.py`, filename globs + high-signal content patterns)
- [x] Shared-module drift check against the sibling repo
      (`scripts/check_shared_drift.py`)
- [x] `ruff check`, `ruff format --check`, `mypy --strict`, `pytest` with the
      coverage floor read from `pyproject.toml`

---

## League play

- [x] Pre-match negotiation protocol: board, starts, `map_area`, timeouts, token ceiling
- [x] Exchange and verify `config_sha256`; **refuse to play on mismatch**
- [x] **Game-count declaration** at the start of every match (a false declaration
      disqualifies the team) — `infra/match_ledger.py`, read by
      `runtime/driver.py` before the first handshake and recorded afterwards
- [x] **Result agreed on the wire before either side reports** (Appendix E rule 35)
      — `runtime/orchestrator_result.py`, `shared/result_claim.py`; silence counts
      as disagreement
- [ ] Warm-up matches against varied strategies (not counted — allowed and encouraged)
      — only a self-warm-up is recorded (`artefacts/declaration_warmup-01.json`)
- [ ] **Counted match #1** vs team ___ — result agreed, both reports sent
- [ ] **Counted match #2** vs team ___ — result agreed, both reports sent
- [ ] (Optional, up to 10 total) further counted matches vs **different** teams
- [ ] One counted match per opponent — no repeats for points
- [x] Mutual log audit completed after every match, before agreeing the result
      (`runtime/match.py` — a series whose audit found forgery is never offered
      for agreement)
- [ ] Fill `[teams.them]` in `config/thief/game.toml` with the real opponent's
      group name, members and four repo URLs before a counted match
- [ ] Record the measured round-trip figures in `docs/LATENCY.md` per opponent

---

## Submission

- [x] `README.md` item 1 — Dec-POMDP model: state space, observations, uncertainty
- [x] `README.md` item 2 — FastMCP orchestration dilemmas: turn management,
      network-failure handling, Gatekeeper and Orchestrator roles
- [x] `README.md` item 3 — strategies implemented and why
- [x] `README.md` item 4 — learning curves (**only if** RL was used)
      — answered explicitly as *not applicable*; no RL is used
- [ ] `README.md` item 5 — **screenshots: belief heatmap + Replay `Verified OK`**
- [x] `README.md` item 6 — **cross-link to the cop repo**
- [ ] Team member names and student IDs — `README.md` `## Team` still says
      *Member names to be completed*, and `[game] members` in
      `config/thief/game.toml` still carries the placeholder
- [x] Any contradiction found in the rulebook documented: where, what we chose, why
      (`README.md` — six entries)
- [ ] `config/` files for every match committed
- [x] `docs/PLAN.md`, `docs/TODO.md`, `docs/prd/*` present (this set)
- [ ] Secrets audit: nothing sensitive anywhere in Git history
      — `scripts/secret_scan.py` gates every **tracked** file on every push; a
      sweep of the **history** has not been run
- [ ] Switch `[email] mode` from `draft` to `send` in `config/thief/game.toml`
      once a dry run has been verified
- [ ] Annotated tag pushed:
      `git tag -a v1.0-submission -m "Final submission: Police-Thief P2P, group N"`
- [ ] Moodle: Word template filled **without moving any field**, saved as PDF
- [ ] Moodle: **both** repo links (cop + thief) included
- [ ] Moodle: each group member submits separately
- [ ] Self-assessment score rates **code quality only**, not the league result

---

## Final pre-submission checklist (Rulebook §11.5)

- [x] Base logic works: full race, no crash, scoring enforced
      (`tests/test_stage1_acceptance.py`, `tests/test_localhost_match.py`)
- [x] FastMCP over a **public URL**, not just localhost
      (public ngrok addresses recorded in the warm-up declaration)
- [x] Commit-Reveal active and the audit completes with no forgery detected
      (`tests/test_stage6_acceptance.py`, `tests/test_localhost_match.py`)
- [x] Scent map and belief map computed **and actually influencing decisions**
      — belief peak is the `threat` the brain runs from; the verbal hint is not
      yet folded into the belief (see the two open Stage-4 boxes)
- [x] Live GUI and Replay App with a valid `Verified OK` stamp
- [ ] Gmail JSON reports sent **by both sides**
- [ ] GitHub repo with Git tag and academic README — the README is in place, the
      `v1.0-submission` tag does not exist yet
- [ ] **At least 2 matches against different teams**
