"""One peer's own half of a sub-game — local truth only.

The book's model is hidden positions: each peer knows where **it** is and never where the rival
is (book ch.1, ch.5; App. E rules 8-9 forbid even *displaying* the objective board). So there is
no referee object here and no shared board state. What exists is:

* your own position, which only you know;
* the barriers, which are public because the cop must declare every placement truthfully
  (App. E rules 15-16) — lying about one is grounds for disqualification;
* the rival's transmitted scent field, which cannot lie: it is emitted by movement itself.

That shape makes adjudication **distributed**, and it is the part most worth understanding before
you build your own peer:

* the cop cannot know it has captured anyone. It issues a ``capture_claim`` at a cell and the
  thief answers. App. E rule 21 makes that answer a cryptographic obligation — a lie is provable
  at the audit against the sealed ``state`` string, so the thief's honest answer is the cheapest
  move available to it as well as the required one;
* a barrier dropped on the thief's own cell is a capture (rule 46) that the **thief** notices;
* a thief with no legal move is captured (rule 47), which again only the thief can see;
* survival at the threshold is claimed by the thief.

So this engine never decides the game from a position it should not have. It decides only what it
is entitled to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sparring.rules.board import Board, Cell
from sparring.rules.outcome import Outcome, Role
from sparring.rules.scent import Trail


class IllegalMove(Exception):
    """Raised when the *opponent* sends a move the physics forbid.

    Rejecting it is the enforcement the book asks for (App. E rules 13-14): each side polices the
    other's physics, because there is nobody else to do it.
    """


@dataclass
class SubGameEngine:
    """The local half of one sub-game. Fresh per sub-game — never reused across them."""

    board: Board
    role: Role
    position: Cell
    trail: Trail
    max_steps: int = 35
    survival_threshold: int = 35
    barriers_max: int = 14
    barriers: list[Cell] = field(default_factory=list)
    rival_scent: dict[str, float] = field(default_factory=dict)
    barriers_placed: int = 0
    opponent_barriers: int = 0
    step: int = 0

    # --- what we are allowed to do ---------------------------------------------------------

    def legal_moves(self) -> list[str]:
        return self.board.legal_moves(self.position, self.barriers)

    def barrier_targets(self) -> list[Cell]:
        if self.role is not Role.POLICE or self.barriers_placed >= self.barriers_max:
            return []
        return self.board.barrier_targets(self.position, self.barriers)

    def apply_own_move(self, move: str) -> None:
        if move not in self.legal_moves():
            raise IllegalMove(f"{move} is not legal from {self.position} — "
                              f"legal here: {self.legal_moves()}")
        self.position = self.board.step(self.position, move)

    def place_own_barrier(self, cell: Cell) -> None:
        """Only the cop, only when forgoing movement, only within one orthogonal step."""
        if self.role is not Role.POLICE:
            raise IllegalMove("only the cop places barriers")
        if cell not in self.barrier_targets():
            raise IllegalMove(f"{cell} is not a legal barrier target from {self.position}")
        self.barriers.append(cell)
        self.barriers_placed += 1

    # --- what the opponent tells us --------------------------------------------------------

    def observe_barrier(self, cell: Cell | None) -> None:
        """Absorb the opponent's declared barrier. Public by rule; both sides must apply it."""
        if cell is None:
            return
        cell = (int(cell[0]), int(cell[1]))
        if not self.board.in_bounds(cell):
            raise IllegalMove(f"declared barrier {cell} is off the board")
        if cell not in self.barriers:
            # The signed quota binds the OPPONENT's declarations exactly as it binds our own
            # placements — an earlier revision absorbed 20 declared barriers against a quota of
            # 14 without noticing (anrbj666's A3).
            if self.opponent_barriers >= self.barriers_max:
                raise IllegalMove(
                    f"opponent barrier #{self.opponent_barriers + 1} at {cell} exceeds the "
                    f"signed quota of {self.barriers_max}")
            self.barriers.append(cell)
            self.opponent_barriers += 1

    def observe_scent(self, grid: dict[str, float] | None) -> None:
        if grid:
            self.rival_scent = dict(grid)

    def answer_capture_claim(self, claim: Cell | None) -> dict | None:
        """The thief's obligatory honest answer (App. E rules 21-22).

        Answering truthfully is not politeness. The sealed ``state`` string in every step record
        carries this peer's own position, so a denial is contradicted by our own revealed log at
        the audit — and the sanction for that is total, not proportional.
        """
        if claim is None or self.role is not Role.THIEF:
            return None
        cell = (int(claim[0]), int(claim[1]))
        return {"claim": [cell[0], cell[1]], "caught": cell == self.position}

    # --- what ends it ----------------------------------------------------------------------

    def self_captured(self) -> Outcome | None:
        """Terminal conditions only the thief can see: trapped, or walled in place."""
        if self.role is not Role.THIEF:
            return None
        if self.position in self.barriers:
            return Outcome.CAPTURE          # rule 46: a barrier dropped on our own cell
        if self.board.boxed_in(self.position, self.barriers):
            return Outcome.CAPTURE          # rule 47: no legal move at all
        return None

    def survived(self) -> bool:
        return self.role is Role.THIEF and self.step >= self.survival_threshold

    def state_string(self) -> str:
        """The sealed ``state`` field — **our own** position only, never the rival's.

        Format pinned by SPEC section 3 to the reference's own spelling, including the space after
        the comma that Python's list repr produces. It carries no shared board frame because
        there is none: each side seals what it alone knows.
        """
        barriers = sorted([list(b) for b in self.barriers])
        return (f"grid={self.board.size}x{self.board.size};"
                f"self={list(self.position)};barriers={barriers}")
