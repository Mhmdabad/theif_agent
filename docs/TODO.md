# TODO — THIEF Agent (גנב)

Ordered task list mirroring the seven PRD stages. **A stage is done when the
behaviour has been observed end-to-end — not when "the code is written".** Do not
open stage *n+1* before every gate in stage *n* is ticked.

Legend: `[ ]` open · `[~]` in progress · `[x]` done · **🚪 GATE** = milestone

---

## Stage 0 — Repository setup

- [ ] `README.md`: academic report skeleton + **cross-link to the cop repo**
- [ ] `.gitignore` **before the first commit**: `credentials.json`, `token.json`,
      `*.env`, `config/**/secrets*`, `token*.json`
- [ ] Repo made accessible to the lecturer (public, or private + shared with `rmisegal@gmail.com`)
- [ ] `config/` directory with `game.json` (shared) and `thief/game.toml` (private)
- [ ] Python project scaffold (`uv` / `pyproject.toml`), `pytest` wired up
- [ ] Branch-per-feature workflow agreed; merge to main only when stable
- [ ] 8-character group identifier (no spaces) chosen and recorded

---

## Stage 1 — Base Logic → [PRD-1](prd/PRD-1-base-logic.md)

- [ ] `BoardState` model (immutable), `Position`, `Move` types
- [ ] Coordinate system: origin `top-left`, index from `0`, both configurable
- [ ] `legal_moves()` — N/S/E/W/STAY, **no diagonals**, no barriers, no off-board
- [ ] Transition function returning a new state
- [ ] Barrier model: irreversible, impassable for both, quota `max_barriers` = 14
- [ ] Capture: coordinate overlap
- [ ] Capture: **barrier placed on the thief's cell**
- [ ] Capture: **thief with no legal move at all**
- [ ] Survival: `survival_threshold` = 35 valid steps → 5/10 scoring
- [ ] Technical loss → 0/0
- [ ] Scoring table wired from config (capture 20/5, survival 5/10, tie 2)
- [ ] Config loader + **Appendix F validator** (fixed = exact, minimum = ≥)
- [ ] Per-match config naming `config_<game_id>_g<NN>.json`, committed to repo
- [ ] Tests: legality, quota, both capture variants, survival, scoring
- **🚪 GATE:** two agents move legally on the grid; over-quota barrier rejected;
  coordinate overlap triggers capture; a full race runs to termination

---

## Stage 2 — FastMCP Infrastructure → [PRD-2](prd/PRD-2-mcp-infrastructure.md)

- [ ] FastMCP server instance, `mcp.run(transport="http", host="0.0.0.0", port=my_port)`
- [ ] Client engine calling the opponent's tools at `opponent_url`
- [ ] Tools: `handshake`, `negotiate_config`, `receive_move`, `get_state_digest`, `ping`
- [ ] Input validation on every tool — never trust an unverified move
- [ ] **Orchestrator** as single gateway to all five subsystems
- [ ] `GamePhaseMachine` with the transition table; illegal transition raises
- [ ] **Deadline Tracker**: timestamp + expiry on every request, controlled retry
- [ ] **Watchdog**: heartbeat monitor, state persistence, controlled shutdown
- [ ] Turn scheduler with strict alternation
- [ ] **Separation audit**: cop and thief in separate processes, separate config
      dirs, zero shared memory/modules/variables
- [ ] Tests: illegal transition, opponent killed mid-turn, watchdog freeze
- **🚪 GATE:** a geometric message from agent A over localhost is received and
  parsed correctly by agent B

---

## Stage 3 — Blind Strategy → [PRD-3](prd/PRD-3-blind-strategy.md)

- [ ] `ThiefBrain(BrainBase)` with `_pick_move`, selectable via `[strategy] thief_class`
- [ ] Insertion point verified: after hint decode, before Commit pack
- [ ] Manhattan distance evaluation; **maximise** distance to the cop
- [ ] Flood-fill escape-space tie-break (avoid dead-ends)
- [ ] Open-neighbour / corner-aversion penalty
- [ ] Barrier-aware reachability tracking
- [ ] `STAY` treated as a first-class candidate
- [ ] Legality guard: policy output re-validated against `legal_moves()`
- [ ] Determinism: seeded randomness, seed logged
- [ ] Decision on movement policy route recorded for the README (heuristic / own
      algorithm / RL) with justification
- [ ] Tests: never-illegal property test; dead-end regression board; determinism
- **🚪 GATE:** given a known target position, the agent computes and executes the
  optimal evasive path with no manual intervention

---

## Stage 4 — Language & Scent → [PRD-4](prd/PRD-4-language-and-scent.md)

- [ ] 5×5 radial scent emission, centre τ = 0.9
- [ ] Decay `τ(t+1) = max(0, (1−ρ)τ(t) + Δτ)`, ρ = 0.10, at end of each **full** turn
- [ ] Sample **opponent's** field only; never our own
- [ ] Fixture test against hand-computed decay values
- [ ] **Pre-series lock**: exchange emission/decay model + numeric example, hash it
- [ ] Offer our scent-engine code to the opponent (permitted and recommended)
- [ ] Belief map `b(s)` over the grid; zero belief on barriers
- [ ] Bayes update combining scent evidence + hint, with reliability coefficient
- [ ] Adaptive reliability: lower on each detected contradiction
- [ ] Lie detector: expected-vs-measured scent contradiction (reproduce book example)
- [ ] Handle split probability mass (two foci) without oscillating
- [ ] Natural-language hint parser (**no numeric-coordinate protocol** — forbidden)
- [ ] Hint generator with `hint_max_words` = 15 cap and `map_area` landmarks
- [ ] **`Intent` flag** (`truth`/`lie`) chosen before sending
- [ ] **Self-consistency guard**: reject any hint contradicting our own emitted field
- [ ] LLM providers: `template` (default, 0 tokens), `ollama`, `claude_api`, `claude_cli`
- [ ] `every_n_steps` throttle; `step_deadline_seconds` = 30 cap with template fallback
- [ ] Token metering
- **🚪 GATE:** free-language report → inference; scent map updates and decays each
  step; LLM produces a hint (truth or lie) within the word cap

---

## Stage 5 — Cloud Exposure → [PRD-5](prd/PRD-5-tunneling.md)

- [ ] ngrok / Localtonet tunnel exposing the FastMCP server publicly
- [ ] Public URL exchanged in handshake, recorded in the declaration file
- [ ] `opponent_url` switched from localhost to the public tunnel URL
- [ ] Re-handshake path for a changed tunnel URL between sub-games
- [ ] Latency measured; `response_timeout_sec` justified against real round-trips
- [ ] Retry policy applied to transport failures only — never to re-send a move
- [ ] Transport event logging (connect / timeout / retry / reconnect)
- [ ] Tunnel-drop test → controlled technical result, no hang
- **🚪 GATE:** an agent on a **remote machine** connects via ngrok and plays a full
  round against the local agent

---

## Stage 6 — Cryptography → [PRD-6](prd/PRD-6-crypto-commit-reveal.md)

- [ ] Nonce generator: `secrets.token_hex(16)` (**never** `random`)
- [ ] Canonical JSON serialisation (`sort_keys=True`, `separators=(",",":")`)
- [ ] `H_commit = SHA256(State ‖ Move ‖ Intent ‖ Nonce)` over the full step record
- [ ] Phase 1 Commit — hash only crosses the wire
- [ ] Phase 2 Acknowledge — opponent confirms lock
- [ ] Phase 3 Reveal — move + hint, **nonce stays hidden**
- [ ] Phase 4 Final Reveal / Audit — all nonces at end of match
- [ ] Verification with `secrets.compare_digest`; mismatch ⇒ `TECHNICAL_LOSS`
- [ ] Append-only log `log_<game_id>_g<NN>.json` with commit/reveal/nonce per step
- [ ] **Truthful capture answer** computed directly from `BoardState`, no dishonest branch
- [ ] `Step-0`: OS, CPU cores/freq, RAM, GPU/VRAM, LLM model name
- [ ] `Step-0`: code version, team name, sub-game number, **GitHub commit hash**
- [ ] Step-0 declaration signed with the pre-supplied key
- [ ] Token consumption metered and cryptographically locked
- [ ] Cross-implementation fixture test: both peers hash byte-identical payloads
- [ ] Tests: corrupted reveal detected; nonce never leaked early; audit passes clean
- **🚪 GATE:** a move is committed then revealed with a valid nonce; Step-0 verifies
  hardware and commit hash on both sides

---

## Stage 7 — Reporting & Visualization → [PRD-7](prd/PRD-7-reporting-and-gui.md)

### GUI
- [ ] Live GUI (Tkinter/PyQt) showing **local truth only** — no bird's-eye view
- [ ] Belief heatmap bound to the real belief object (deeper red = higher probability)
- [ ] Turn banner: green `YOUR TURN` / grey `LOCKED`, with input lock after Commit

### Replay
- [ ] Replay App loading `log_<game_id>_g<NN>.json`, step forward/backward
- [ ] Per-step SHA-256 re-computation vs stored commitment
- [x] Green `Verified OK` / red `TAMPERED`; abort and void on first failure
- [x] Hand-tampered log test triggers `TAMPERED`

### Gmail + Gatekeeper
- [ ] Google Cloud project + Gmail API enabled
- [ ] OAuth Consent Screen configured, team members added as Test Users
- [x] Scope restricted to `https://www.googleapis.com/auth/gmail.send` **only**
- [ ] OAuth Client ID (Desktop Application) → `credentials.json` **(gitignored)**
- [ ] First authorization flow → `token.json` **(gitignored)**
- [x] **Quota Manager** — daily safety threshold
- [ ] **Token Bucket** — 30 rpm, 2 concurrent, 5 s backoff, 3 retries, queue 100
- [ ] **DOS Detector** — anomaly lock (backpressure / circuit breaker)
- [ ] 429 handling: honour, back off, wait for next window — never blind retry
- [ ] Report sent as **structured JSON attachment**, never free plaintext
- [ ] Destination hard-coded: `rmisegal+uoh26finalgame@gmail.com`
- [ ] Send-storm simulation blocked before reaching the API

### JSON artefacts
- [ ] `declaration_<game_id>.json` — teams, members, **4 repo URLs**, MCP addresses,
      hardware, LLM model, token ceiling, start/end times
- [ ] `config_<game_id>_g<NN>.json` — locked agreed parameters
- [ ] `log_<game_id>_g<NN>.json` — full step record
- [ ] `result_<game_id>.json` — per-sub-game and aggregate scores, commit hashes,
      total tokens
- [ ] Shared `game_uid`, names derived from `game_id`
- **🚪 GATE:** match summary sent via Gmail; GUI displays state; Replay App
  reconstructs a recorded round with `Verified OK`

---

## League play

- [ ] Pre-match negotiation protocol: board, starts, `map_area`, timeouts, token ceiling
- [ ] Exchange and verify `config_sha256`; **refuse to play on mismatch**
- [ ] **Game-count declaration** at the start of every match (a false declaration
      disqualifies the team)
- [ ] Warm-up matches against varied strategies (not counted — allowed and encouraged)
- [ ] **Counted match #1** vs team ___ — result agreed, both reports sent
- [ ] **Counted match #2** vs team ___ — result agreed, both reports sent
- [ ] (Optional, up to 10 total) further counted matches vs **different** teams
- [ ] One counted match per opponent — no repeats for points
- [ ] Mutual log audit completed after every match, before agreeing the result

---

## Submission

- [ ] `README.md` item 1 — Dec-POMDP model: state space, observations, uncertainty
- [ ] `README.md` item 2 — FastMCP orchestration dilemmas: turn management,
      network-failure handling, Gatekeeper and Orchestrator roles
- [ ] `README.md` item 3 — strategies implemented and why
- [ ] `README.md` item 4 — learning curves (**only if** RL was used)
- [ ] `README.md` item 5 — **screenshots: belief heatmap + Replay `Verified OK`**
- [ ] `README.md` item 6 — **cross-link to the cop repo**
- [ ] Any contradiction found in the rulebook documented: where, what we chose, why
- [ ] `config/` files for every match committed
- [ ] `docs/PLAN.md`, `docs/TODO.md`, `docs/prd/*` present (this set)
- [ ] Secrets audit: nothing sensitive anywhere in Git history
- [ ] Annotated tag pushed:
      `git tag -a v1.0-submission -m "Final submission: Police-Thief P2P, group N"`
- [ ] Moodle: Word template filled **without moving any field**, saved as PDF
- [ ] Moodle: **both** repo links (cop + thief) included
- [ ] Moodle: each group member submits separately
- [ ] Self-assessment score rates **code quality only**, not the league result

---

## Final pre-submission checklist (Rulebook §11.5)

- [ ] Base logic works: full race, no crash, scoring enforced
- [ ] FastMCP over a **public URL**, not just localhost
- [ ] Commit-Reveal active and the audit completes with no forgery detected
- [ ] Scent map and belief map computed **and actually influencing decisions**
- [ ] Live GUI and Replay App with a valid `Verified OK` stamp
- [ ] Gmail JSON reports sent **by both sides**
- [ ] GitHub repo with Git tag and academic README
- [ ] **At least 2 matches against different teams**
