# PRD-4 — Natural Language and Scent Integration (שפה טבעית ושילוב ריח)

**Stage 4 of 7** · Rulebook Ch. 4 + Ch. 6 · Repo: **THIEF**
Prev: [PRD-3](PRD-3-blind-strategy.md) · Next: [PRD-5 — Cloud Exposure](PRD-5-tunneling.md)

## 1. Objective

This is the step-change stage: rigid coordinates are replaced by **free natural
language**, the **dynamic pheromone equations** and their decay are implemented,
and the **LLM** is plugged in for inference and for composing lies. Uncertainty —
the heart of the project — is born here, which is exactly why it comes only after
the infrastructure and the decision core have been proven.

## 2. Scope

**In:** scent emission and decay, opponent-scent sampling, Bayesian belief map,
natural-language hint generation and parsing, `Intent` flag, LLM providers, bluff
classification, lie detection by physics contradiction.
**Out:** public URLs (PRD-5), Commit-Reveal (PRD-6), GUI/replay/email (PRD-7).

## 3. Functional requirements

### 3.1 Scent — emission and decay (all parameters **fixed**)
- FR-4.1 Whenever an agent moves **or stays**, it emits a scent field of side
  `pheromone_grid_size` (**5×5**) centred on its cell.
- FR-4.2 Centre intensity is `pheromone_center_intensity` = **0.9**, falling off
  **radially** — a smooth hill, not a uniform blob. Radial fall-off gives the
  mechanism robustness: even if the exact cell is missed, the neighbours still
  indicate direction.
- FR-4.3 At the end of every **full** turn (cop **and** thief have moved), all
  scent on the board decays:

  ```
  τ_ij(t+1) = max(0, (1 − ρ)·τ_ij(t) + Δτ_ij)        ρ = 0.10
  ```
  - `τ_ij(t)` — current intensity, continuous in `[0, 0.9]`; effectively a local
    freshness/confidence score.
  - `(1 − ρ)` — forgetting: shrinks existing scent to 90 % per turn.
  - `Δτ_ij` — new deposit by radial proximity to the emitter (0.9 at centre,
    0 if the agent is far).
  - `max(0, ·)` — a cell that never absorbed scent, or fully decayed, is simply
    *silent* — absence of information, not negative information.
- FR-4.4 **Symmetry:** both sides emit; each side samples **only the opponent's**
  field, never its own.
- FR-4.5 Scent **cannot be faked**. It is emitted by the mere act of moving or
  staying; no agent can plant a misleading trail. What *can* be false is the
  verbal hint — and the environment is what exposes it.
- FR-4.6 With ρ = 0.10 a single deposit stays above half-peak for roughly six to
  seven turns. This is a deliberate design point: long enough to be tactically
  usable, short enough to distinguish old from new.

### 3.2 Pre-series cryptographic lock of the scent model
- FR-4.7 Before the series opens, both teams **exchange the full emission/decay
  model including a concrete numeric example** (e.g. a centre cell receives
  τ = 0.9; after one turn of decay at ρ it holds 0.9·(1 − ρ) = 0.81).
- FR-4.8 Both sides verify they interpret the formula identically, then lock the
  agreement with a **SHA-256 hash of the formula plus the numeric example**, so any
  later behavioural drift is detected immediately.
- FR-4.9 Supplying the opponent with our actual scent-engine code is **permitted
  and recommended**, to guarantee both sides run identical behaviour and leave no
  room for interpretation that would damage fairness.

### 3.3 Belief map (Bayesian)
- FR-4.10 Maintain a `grid_size × grid_size` matrix `b(s)` = probability the
  hidden **cop** occupies cell `s`. (Fully symmetric: the cop maintains the mirror
  map about us.)
- FR-4.11 On every incoming observation, update by **Bayes' rule** combining two
  evidence sources:
  1. the opponent's sampled scent field (trustworthy physics), and
  2. the opponent's verbal hint (possibly false) — weighted by a **reliability
     coefficient**.
- FR-4.12 The reliability coefficient is **adaptive**: each detected contradiction
  between a hint and the scent evidence lowers it; sustained consistency raises it.
- FR-4.13 Barrier cells carry zero belief.
- FR-4.14 `argmax_s b(s)` is the target the evasion policy runs *away* from;
  probability mass may split into two foci, and the policy must handle that rather
  than oscillating between them.

### 3.4 Lie detection by physical contradiction
- FR-4.15 For each incoming hint, compute the scent field the claim would imply
  and compare it to the measured field. Worked example from the book: the opponent
  says "I moved north"; a fresh northern trail would read ≈ (1−ρ)·0.9 ≈ 0.81, but
  the north measures **0.00** while all the scent mass sits in the south-east. The
  gap is absolute → the claim is a lie with high confidence.
- FR-4.16 On detection: lower the hint reliability coefficient, re-weight belief
  toward the true scent source, and re-aim.
- FR-4.17 **Applied to ourselves:** the same procedure is available to the
  opponent. Our hints must therefore be *consistent with our own emitted field* —
  deception should target intent and timing, not a position the environment has
  already published. A clumsy lie is a double-edged sword: the attempt to mislead
  is precisely what gives our position away.

### 3.5 Verbal channel
- FR-4.18 Inter-agent communication about position/intent is **free natural
  language only**. A direct numeric-coordinate protocol is **forbidden** — it
  destroys the psychological character of the game (Appendix E rules 26–27).
- FR-4.19 Each hint is capped at `hint_max_words` (default **15**). The cap applies
  to the template mode *and* is stated to the LLM in its system prompt.
- FR-4.20 Hints may be seasoned with real landmarks from the agreed `map_area`
  (default `"New York"`), e.g. "slipping past Times Square". Empty `map_area` ⇒
  generic landmarks. `map_area` and `hint_max_words` are negotiated and signed like
  any other match condition.
- FR-4.21 Every hint carries an **`Intent` flag** — `truth` or `lie` — chosen
  *before* sending and sealed into the commitment (PRD-6), so a team cannot claim
  afterwards that it lied "on purpose".

### 3.6 LLM integration — verbal layer only
- FR-4.22 The LLM composes bluff text and profiles the opponent's language (bluff
  classifier / behavioural profiler). It **never** decides the move (see
  PRD-3 FR-3.11/3.12).
- FR-4.23 Four operating modes, selected in `config/thief/game.toml`
  (`[trash_talk] provider`):

  | Mode | Where it runs | Token cost | Requirement |
  |---|---|---|---|
  | `template` **(default)** | in-process, pre-written lines | **zero** | none, offline, free |
  | `ollama` | local model at `localhost:11434` | zero API tokens, no rate limit | Ollama install + model pull |
  | `claude_api` | small cloud model (e.g. Haiku) | counted against `token_budget_per_series` | Anthropic API key (paid) |
  | `claude_cli` | `claude -p` via Claude Code CLI | highest cost | subscription |

- FR-4.24 `every_n_steps` invokes the model only once every N turns, cutting
  consumption further. **A full 6-sub-game series can be played at zero tokens** in
  `template` or `ollama` mode — which is the right default, since the league
  rewards algorithmic efficiency, not raw compute.
- FR-4.25 `step_deadline_seconds` (default 30) hard-caps LLM thinking per step;
  on timeout, fall back to `template` rather than stalling the turn.
- FR-4.26 Total tokens consumed are metered and reported in the final JSON.

### 3.7 Decision flow (final shape of the strategy module)

```
incoming hint + opponent scent
        ↓
   hint decode (parse text)
        ↓
   belief update (Bayes, reliability-weighted)
        ↓
   move choice (algorithmic: evasion policy)
        ↓
   LLM / template bluff text (+ Intent flag)
        ↓
   Commit pack (out)
```

## 4. Acceptance criteria (milestone gate)

- [ ] A free-language report is translated into an inference (belief update).
- [ ] The scent map updates and decays on every step, matching the formula to
      within floating-point tolerance against a hand-computed fixture.
- [ ] The LLM (or template) produces a hint, correctly flagged `truth` or `lie`,
      within `hint_max_words`.
- [ ] The book's worked lie-detection example is reproduced by our detector.
- [ ] Belief `argmax` demonstrably steers the evasion policy (log shows target
      cell changing after a contradicting hint).
- [ ] A full series runs end-to-end in `template` mode at **zero tokens**.
- [ ] Our own hint generator never emits a hint that contradicts our own emitted
      scent field (guard test).

## 5. Out of scope / deferred

Public exposure (PRD-5) · commitment/reveal of move + hint + Intent (PRD-6) ·
heatmap rendering (PRD-7) · token reporting in the final JSON (PRD-7).
