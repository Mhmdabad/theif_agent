# PRD-7 — Reporting and Visualization Shell (מעטפת דיווח והמחזה)

**Stage 7 of 7** · Rulebook Ch. 9 + Ch. 7 + Appendix A · Repo: **THIEF**
Prev: [PRD-6](PRD-6-crypto-commit-reveal.md) · Next: — (submission)

## 1. Objective

Build the outer shell: **Gmail API over OAuth 2.0**, the **Live GUI**, and the
**Replay App**. It is built last because it consumes every layer beneath it.

## 2. Scope

**In:** Live GUI (belief heatmap + turn banner), Replay viewer with cryptographic
verification, Gatekeeper (quota / token bucket / DOS detector), Gmail send-only
OAuth flow, the four mandatory JSON files, submission artefacts.
**Out:** nothing — this stage closes the project.

---

## 3. Live GUI

### 3.1 Local truth
- FR-7.1 Each side runs its **own** GUI (Tkinter or PyQt) showing **only local
  truth**: our own position, the scent we sense, and the hints we received.
- FR-7.2 **There is no bird's-eye view.** Displaying the full objective board state
  would violate the Dec-POMDP formalism — each agent's observation `Ω_i` is a
  partial subset of the true state `S` — and **disqualifies the project for an
  illegal advantage** (Appendix E rules 8–9).

### 3.2 Belief heatmap
- FR-7.3 A dynamic grid renders our belief map about the **cop's** position:
  higher probability ⇒ deeper red. (The cop's window mirrors this about us.)
- FR-7.4 The map updates in real time from the opponent's scent field and the
  hints received. The student reads a focus of suspicion at a glance instead of a
  matrix of numbers.
- FR-7.5 The heatmap must show the *actual* belief object driving decisions — not a
  cosmetic re-render.

### 3.3 Turn banner
- FR-7.6 A status banner turns **green (`YOUR TURN`)** when the opponent's MCP
  server signals the turn has passed to us.
- FR-7.7 Once we have chosen a move, signed it with a Commit and transmitted it,
  the banner turns **grey (`LOCKED`)** and the interface refuses input until the
  turn returns.
- FR-7.8 This is not decoration: it is the visual representation of the
  asynchronous state machine, and the input lock prevents a **race condition**
  where both sides act on the same step.

---

## 4. Replay App (mandatory submission requirement)

- FR-7.9 Building a **Replay Viewer is a mandatory submission requirement**, not an
  optional extra.
- FR-7.10 It loads the final log file (e.g. `logs/thief_match.json` /
  `log_<game_id>_g<NN>.json`) and lets the viewer step forward and backward in time.
- FR-7.11 Its distinguishing feature is not graphics but **cryptographic
  verification**: for each step it recomputes SHA-256 over the nonce and move
  recorded in the visible log and compares to the original commitment.
- FR-7.12 Match ⇒ green **`Verified OK`** stamp. Any alteration, however small ⇒
  a blazing red **`TAMPERED`** banner, and **the match is void immediately**. There
  is no appeal and no retroactive fix — the cryptographic witness system exists
  precisely so that no human judgement is involved in deciding whether a log was
  forged.
- FR-7.13 One `TAMPERED` result voids the whole match; the walk aborts on first
  failure.

```python
def verify_step(entry):
    payload = f"{entry['nonce']}|{entry['move']}".encode("utf-8")
    if hashlib.sha256(payload).hexdigest() == entry["commit"]:
        return "Verified OK"
    return "TAMPERED"
```
> Illustrative only — in practice the signature covers the full step
> (State, Move, Intent, Nonce) per PRD-6.

- FR-7.14 **Screenshots of the viewer showing `Verified OK`, alongside a screenshot
  of the belief heatmap in the Live GUI, are mandatory README content.**

---

## 5. Gmail reporting

### 5.1 Obligation
- FR-7.15 At the end of every legal match, **each team sends its own automated
  summary** to the lecturer via the Gmail API. One side sending is **not enough**;
  if a side does not report, that side receives no points for the match — even if
  it won on the board.
- FR-7.36 The send is **automatic** at the end of a legal match (§9.3), from both
  sides independently; `play` performs it. A rehearsal sends nothing.
- FR-7.16 Both teams must **agree on the result** before reporting. A missing or
  contradicting report voids the match and scores 0 for both.
- FR-7.17 Mandatory destination, supplied by configuration:

  The address Appendix ו mandates is set as `REPORT_RECIPIENT` in a git-ignored
  `.env` (see `.env.example`), and is deliberately **not** written into the
  source or the private config — one source, so no copy can go stale against
  another. There is no default and no fallback: unset, empty or blank is
  refused, naming the variable and the file, rather than guessing a destination.
  A refusal is visible while somebody can still fix it; a guessed address is
  visible only in the wrong inbox, or in none.

### 5.2 Gatekeeper — three cumulative defences
Automation is a blessing and a trap: it hands code — which may contain a bug — the
key to a live mail account. What happens when an infinite loop starts firing
thousands of messages a minute?

- FR-7.18 **Quota Manager** — counts operations performed today and blocks crossing
  the daily safety threshold. Last line of defence against account suspension.
- FR-7.19 **Token Bucket rate limiter** —

  ```
  tokens ← min(C, tokens + r·Δt),      allow ⟺ tokens ≥ 1
  ```
  `C` = burst capacity, `r` = steady refill rate (must stay below Google's API
  quota), `Δt` = elapsed time. Silence is rewarded with future burst capacity.
  Config: `requests_per_minute` 30, `concurrent_requests` 2, `retry_backoff_sec` 5,
  `max_retries` 3, `queue_depth` 100 (all **minimums**).
- FR-7.20 **DOS Detector** — recognises anomalous send patterns indicating a bug or
  infinite loop, then **locks API access entirely**, sacrificing one report to save
  the account. This is `backpressure` + `circuit breaker`.
- FR-7.21 A request reaches the API only after passing all three gates; each gate
  fails fast.

> **Three different things are called "token" in this project** and must not be
> confused: **rate tokens** (token bucket), **LLM tokens** (text units, budgeted and
> cryptographically locked at Step-0), and **OAuth tokens** (access/refresh).

### 5.3 429 and format — iron rules
- FR-7.22 Exceeding Google's quota returns **HTTP 429 (Too Many Requests)**. This is
  not a transient glitch: blindly insisting and immediately re-sending can get the
  account **suspended by the provider**. Honour the 429, **back off**, wait for the
  next window.
- FR-7.23 The report must be **structured, uniform, machine-readable JSON sent as
  an attachment**. Any attempt to send free plaintext that cannot be parsed
  automatically **leads to rejection of the report** — which can mean losing that
  round's league points.

### 5.4 OAuth 2.0 setup (Appendix A)
- FR-7.24 Five ordered steps: (1) create a Google Cloud project and enable the
  Gmail API; (2) configure the **OAuth Consent Screen** and add team members as
  Test Users; (3) restrict the scope to the absolute minimum; (4) create an OAuth
  Client ID of type **Desktop Application** and download `credentials.json`;
  (5) run the first authorization flow, which generates `token.json`.
- FR-7.25 **Scope: `https://www.googleapis.com/auth/gmail.send` only.** Never grant
  read or modify access. Least privilege turns a stolen token from a powerful
  weapon into a nearly harmless tool.
- FR-7.26 `token.json` holds a short-lived **Access Token** plus a long-lived
  **Refresh Token**; thanks to the latter the agent reports autonomously for months
  with no further manual intervention.
- FR-7.27 **`credentials.json` and `token.json` are secrets.** Both **must** be
  listed in `.gitignore` **before the first commit** — this applies even to a
  private repo shared only with the lecturer. A secret pushed even once is
  permanently compromised: deleting it from current code is not enough, the
  credentials must be **rotated** in the console.

---

## 6. The four mandatory JSON files

All four share a common `game_uid`, and each filename derives from `game_id`, so
files from different matches can never be mixed up.

| Variable | Filename | Role |
|---|---|---|
| Declaration file | `declaration_<game_id>.json` | Pre-game declaration: both teams and members, **cop and thief repo URLs**, MCP server addresses, hardware specs, LLM model, agreed token ceiling, start/end times. Fixes cryptographically everything that does not change during the match. |
| Config file | `config_<game_id>_g<NN>.json` | The agreed configuration: all quantitative sub-game parameters (Appendix F), cryptographically locked and identical on both sides. |
| Log file | `log_<game_id>_g<NN>.json` | Step-by-step record: Commit-Reveal commitments, moves, hints, LLM discussion fields, nonces and hashes. Enables full verification in the Replay App. |
| Result file | `result_<game_id>.json` | Final results report: each team's score per sub-game and the aggregate, for league weighting. **This is the binding report emailed to the lecturer.** |

- FR-7.28 Mandatory fields include **both teams' GitHub links (four links total)**,
  the **commit hash of each sub-game**, and **total tokens consumed**.

---

## 7. Submission artefacts

- FR-7.29 **Two separate GitHub repos** — cop and thief — each accessible to the
  lecturer (public, or private and explicitly shared with `rmisegal@gmail.com`).
- FR-7.30 **Mandatory cross-link:** each repo's `README.md` links to the team's
  other repo. This repo (THIEF) links to the COP repo, and vice versa. The Moodle
  submission carries **both** links; the end-of-match JSON carries **four**.
- FR-7.31 Each repo contains at minimum: `README.md` (the academic report),
  `config/`, the **PRD** files, the **PLAN** file, and the **TODO** files. These
  tell the story of development and let the grader reconstruct the working method
  — not just the final result.
- FR-7.32 Final version fixed with an **annotated Git tag**:

  ```bash
  git tag -a v1.0-submission -m "Final submission: Police-Thief P2P, group N"
  git push origin v1.0-submission
  ```
- FR-7.33 `README.md` academic report — six mandatory components:
  1. **The chosen Dec-POMDP model** — scientific description of the formalism:
     state space, observations, uncertainty.
  2. **FastMCP orchestration dilemmas** — turn management, network-failure
     handling, the roles of Gatekeeper and Orchestrator.
  3. **Strategies implemented** — heuristics (Manhattan, Bayesian belief),
     LLM-based strategy, or optionally Q-Learning.
  4. **Learning curves** — mandatory **if** RL was used, as empirical evidence of
     policy convergence.
  5. **Screenshots — absolute requirement** — the Live GUI belief map and the
     Replay App showing `Verified OK`.
  6. **Link to the companion repo** (cop ↔ thief).
- FR-7.34 Moodle: each group member submits separately; the group gets a unique
  **8-character identifier with no spaces**; the Word template is filled in and
  saved as PDF **without moving or changing any field**.
- FR-7.35 The self-assessment score must rate **code quality only — never the
  league result**. Basing it on the match outcome distorts the code-quality
  criterion.

## 8. Acceptance criteria (milestone gate)

- [ ] Match summary sent through Gmail as a structured JSON attachment.
- [ ] GUI displays live state under local truth only; banner locks input after commit.
- [ ] Replay App reconstructs a recorded round and stamps `Verified OK`.
- [ ] A hand-tampered log triggers `TAMPERED` and voids the match.
- [ ] Gatekeeper blocks a simulated send storm before it reaches the API.
- [ ] A 429 is honoured with back-off, not an immediate retry.
- [ ] All four JSON files generated with consistent `game_uid` and derived names.
- [ ] `.gitignore` verified — no `credentials.json` / `token.json` anywhere in history.
- [ ] `v1.0-submission` tag pushed; README complete with screenshots and cross-link.
