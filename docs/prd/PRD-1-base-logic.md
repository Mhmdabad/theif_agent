# PRD-1 — Base Logic (לוגיקת בסיס)

**Stage 1 of 7** · Rulebook Ch. 3 · Repo: **THIEF**
Prev: — · Next: [PRD-2 — MCP Infrastructure](PRD-2-mcp-infrastructure.md)

## 1. Objective

Stand up the physical core of the game — grid, movement, barriers, capture
detection, scoring — in **one process, with no networking and no intelligence**.
If two agents cannot move legally on a local board, there is no point wiring a
network between them.

## 2. Scope

**In:** board model, coordinate system, legal-move generation, barrier rules,
capture/survival conditions, scoring table, config loading, turn counter.
**Out:** MCP, scent, belief, LLM, hints, cryptography, GUI, email.

## 3. Functional requirements

### 3.1 Board
- FR-1.1 Square grid of side `grid_size` (default **7**, minimum — may be raised
  by mutual agreement, never lowered).
- FR-1.2 Cells addressed as `(row, col)`. Origin at `axis_origin_corner`
  (default `top-left`, vertical axis grows downward), counting from
  `axis_start_index` (default `0`). Both are negotiable but **must be identical on
  both peers** — if one counts from 0 and the other from 1, `[3,3]` means two
  different cells and the race falls apart.
- FR-1.3 Start positions loaded from config: thief `[3,3]` (centre), cop `[0,0]`
  (corner) by default. Negotiable; any legal agreed layout is allowed.
- FR-1.4 A cell is one of: free, barrier, occupied-by-cop, occupied-by-thief.

### 3.2 Movement
- FR-1.5 Per turn an agent performs exactly **one** action: move one cell
  orthogonally (N/S/E/W) **or** `STAY`.
- FR-1.6 **Diagonal movement is illegal.** An attempted diagonal is rejected by
  the physics enforcer (later: by the opponent) → technical loss.
- FR-1.7 A move into a barrier or off-board is illegal and must be rejected before
  it is ever committed.
- FR-1.8 `legal_moves(state, agent) -> list[Move]` is the single source of legality
  and is used by both the engine and (later) the strategy module.

### 3.3 Barriers (cop capability — modelled here, exercised by the opponent)
- FR-1.9 On a turn where the **cop forfeits movement**, it may place a barrier on
  its own cell or any of the 4 orthogonally adjacent cells.
- FR-1.10 Barriers are **irreversible** and impassable **for both players** until
  the end of the match.
- FR-1.11 Cop's barrier budget is `max_barriers` (default **14**, minimum).
  Placement beyond quota is rejected.
- FR-1.12 **Trapping placement:** a barrier placed on the cell the thief currently
  occupies **counts as a capture**.
- FR-1.13 A thief with **no legal move at all** (all neighbours blocked by barriers
  and/or board edges) is likewise **considered captured**.
- FR-1.14 Every barrier placement must be **declared truthfully**, with its exact
  location. No hidden barriers; lying about the location is a serious offence.
  *This repo's job is to verify the opponent's declarations, not to make them.*

### 3.4 Termination and scoring
- FR-1.15 **Capture** — cop lands on the thief's cell and issues a Capture Claim
  (or FR-1.12 / FR-1.13 fire).
- FR-1.16 **Survival** — thief completes `survival_threshold` valid steps
  (default **35**, minimum) without being captured. **This is our win condition.**
- FR-1.17 **Technical loss** — a side crashes, times out, or commits a
  cryptographic forgery. Scores **0 for both sides**.
- FR-1.18 `max_moves` (default **35**, minimum) caps the sub-game length.
- FR-1.19 Scoring table (all values **fixed** — deviation disqualifies):

  | Outcome | Cop | Thief |
  |---|---|---|
  | Capture | 20 | 5 |
  | Survival | 5 | **10** |
  | Technical loss | 0 | 0 |
  | Aggregate tie over a series | 2 | 2 |

- FR-1.20 **Truthful capture answer:** when the cop claims capture, the thief must
  answer truthfully. (Enforced cryptographically in PRD-6; the honest answer path
  is built here.)

### 3.5 Configuration
- FR-1.21 All quantitative values load from `config/game.json`; nothing hard-coded.
- FR-1.22 Config files are named per match (`config_<game_id>_g<NN>.json`) and
  committed to this repo for reproducibility.
- FR-1.23 Startup validates every value against Appendix F: *fixed* values must
  match exactly; *minimum* values must be ≥ the book default. Refuse to start
  otherwise.

## 4. Data model (indicative)

```python
Position = tuple[int, int]                  # (row, col)
Move     = Literal["N", "S", "E", "W", "STAY"]

@dataclass(frozen=True)
class BoardState:
    grid_size: int
    cop: Position
    thief: Position
    barriers: frozenset[Position]
    barriers_used: int
    step: int
```

`BoardState` is immutable — the transition function returns a new state. This
matters later: the Commit hash is taken over a specific state snapshot.

## 5. Acceptance criteria (milestone gate)

- [ ] Two agents move legally on a `grid_size` board; every illegal move is refused.
- [ ] A barrier placed beyond `max_barriers` is rejected.
- [ ] Coordinate overlap triggers capture.
- [ ] Barrier-on-thief triggers capture (FR-1.12).
- [ ] Fully-enclosed thief triggers capture (FR-1.13).
- [ ] Reaching `survival_threshold` triggers survival with 5/10 scoring.
- [ ] A full race runs to termination without crashing.
- [ ] `pytest` suite covers legality, barrier quota, both capture variants,
      survival, and score assignment.

## 6. Out of scope / deferred

Networking (PRD-2) · decision-making (PRD-3) · uncertainty, scent, hints (PRD-4) ·
public exposure (PRD-5) · cryptography (PRD-6) · GUI, replay, email (PRD-7).
