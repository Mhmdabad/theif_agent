# PRD-3 — "Blind" Strategy Module (מודול אסטרטגיה עיוור)

**Stage 3 of 7** · Rulebook Ch. 6 · Repo: **THIEF**
Prev: [PRD-2](PRD-2-mcp-infrastructure.md) · Next: [PRD-4 — Language & Scent](PRD-4-language-and-scent.md)

## 1. Objective

Wire in a first decision-making module that operates in a world of **complete and
accurate information** — the opponent's true position is known. "Blind" here means
blind to *uncertainty*: no scent, no natural language, no deception yet. The point
is to isolate the correctness of the decision core before the fog is switched on.

## 2. Scope

**In:** strategy module interface and its exact insertion point, evasion policy
v1, legality guard, deterministic reproducibility.
**Out:** belief maps and Bayes (PRD-4), hints and LLM (PRD-4), crypto (PRD-6).

## 3. Functional requirements

### 3.1 Module boundary
- FR-3.1 The strategy module is a **separate module** plugged into the
  `PeerRuntime` at exactly one point: **immediately after decoding the incoming
  hint, and before packing the outgoing Commit.** All of the agent's intelligence
  lives between those two points.
- FR-3.2 Interface follows the reference contract so it can be swapped from
  config: a class inheriting `BrainBase` / `ThiefBrain` that overrides
  `_pick_move`. Selected in `config/thief/game.toml`:

  ```toml
  [strategy]
  thief_class = "my_team.strategy:MyThiefBrain"   # package.module:Class
  ```
  Leaving the section empty runs the shipped combined heuristic brain.
- FR-3.3 The module returns **only a legal move**, validated against
  `legal_moves()` from PRD-1 before it can be committed.

### 3.2 Policy v1 — evasion under full information
- FR-3.4 Compute Manhattan distance to the cop:
  `D = |r_thief − r_cop| + |c_thief − c_cop|`.
- FR-3.5 Choose the legal move that **maximises** `D` (the cop minimises it).
- FR-3.6 **Tie-break by escape space**, not arbitrarily: prefer the candidate cell
  with the larger flood-fill reachable area over free cells. Running "further
  away" into a pocket the cop is about to seal is the classic thief failure mode.
- FR-3.7 Penalise moves that reduce our number of open neighbours below a
  threshold (corner/edge aversion) unless they strictly increase `D`.
- FR-3.8 Account for barriers already on the board: they change both distance and
  reachability, and their pattern reveals the cop's containment plan.
- FR-3.9 `STAY` is a first-class candidate. Survival, not distance, is the win
  condition — but note (for PRD-4) that staying re-emits scent at the same cell.

### 3.3 Alternative policies (documented choice)
The book treats three routes as **equal citizens**; in all three the spatial
decision stays algorithmic:

1. **Pure heuristics** — Bayesian belief + Manhattan. *Reference default; our
   starting point.*
2. **Your own heuristic algorithm** — belief + scent + barrier exploitation +
   lookahead (minimax / expectimax against the opponent's belief). *Our target.*
3. **Reinforcement learning** — Q-Learning with the Bellman update and
   ε-greedy exploration. **Optional**; RL was never taught in the course and a
   strong agent needs no RL at all.

   ```
   Q(s,a) ← Q(s,a) + α [ r + γ·max_a' Q(s',a') − Q(s,a) ]
   ```
   If used, learning curves become a **mandatory** README section.

- FR-3.10 Whichever route is chosen, it must be stated and justified in the README
  academic report.

### 3.4 Hard constraint — the LLM does not move the agent
- FR-3.11 The move decision is **always** computed in Python. LLMs hallucinate in
  Cartesian space — confusing directions, distances and coordinates — and will
  confidently return an illegal, wall-colliding or self-destructive move.
- FR-3.12 A single documented exception exists: if **both teams explicitly and
  mutually agree in pre-match negotiation**, an LLM-based move tactic is permitted.
  Even then the local algorithm must still enforce legality and reject any illegal
  suggestion, and the hallucination risk is on the team that chose it. One side may
  **not** adopt this unilaterally. Our default remains fully algorithmic.

### 3.5 Determinism
- FR-3.13 Given identical state and identical config, the policy returns an
  identical move. Any stochastic element (e.g. ε-greedy) is seeded and the seed is
  logged, so a match can be replayed exactly.

## 4. Acceptance criteria (milestone gate)

- [ ] Given a known target position, the agent computes and executes the optimal
      evasive path with **no manual intervention**.
- [ ] The module never returns an illegal move (property test over random boards).
- [ ] Swapping the brain class via `config/thief/game.toml` changes behaviour
      without touching runtime code.
- [ ] Barrier-aware tie-breaking demonstrably prefers open space over a dead-end
      that is nominally further away (regression test with a hand-built board).
- [ ] Same state + same seed ⇒ same move, across runs.

## 5. Out of scope / deferred

Probabilistic belief and Bayes updates (PRD-4) · scent reading (PRD-4) · hint
generation and bluff classification (PRD-4) · commitment of the chosen move
(PRD-6) · heatmap visualisation (PRD-7).
