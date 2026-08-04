"""What each peer knows about scent, split by whose it is.

Both agents emit. Neither may read its own trail — the rulebook's model is
that a peer infers the *opponent's* movement from the field the opponent
leaves, and a peer sampling its own emissions would be reading information the
rules never granted it. It would also be strictly misleading: our own trail is
brightest exactly where we are, so an agent that pooled both fields would
confidently track itself.

The rule is enforced structurally rather than by convention. The two fields
are separate attributes, and every sampling method reads
:attr:`ScentMemory.opponent`. Our own field is reachable only through
:meth:`outgoing`, whose name says what it is for: transmission, not inference.
There is no method that returns a merged view, because a merged view has no
legitimate use and one careless call site would silently corrupt every belief
update downstream.
"""

from dataclasses import dataclass, field

from .board import Position
from .scent import CENTRE_INTENSITY, emission
from .trail import Trail


@dataclass
class ScentMemory:
    """One peer's scent state: what we have laid down, and what we have read."""

    own: Trail = field(default_factory=Trail)
    """Everything we have emitted. Transmitted, never sampled."""

    opponent: Trail = field(default_factory=Trail)
    """Everything we have absorbed from the other side. The only evidence."""

    def emit(
        self, cell: Position, board_size: int, intensity: float = CENTRE_INTENSITY
    ) -> dict[Position, float]:
        """Lay our own field around ``cell`` and return what was laid.

        Called every turn, moving or standing still. The return value is for
        the caller to transmit; it is deposited into :attr:`own`, which
        nothing in this class will ever sample.
        """
        field_laid = emission(cell, board_size, intensity)
        self.own.deposit(field_laid)
        return field_laid

    def absorb(self, wire: dict[str, float], board_size: int) -> None:
        """Merge a received ``{"r,c": intensity}`` field into the opponent's.

        Out-of-range keys are dropped rather than trusted. The field arrives
        from an adversary who benefits from us believing wrong things, and a
        cell off the board would either crash a consumer or quietly widen the
        board we reason about.
        """
        for key, value in wire.items():
            row, _, col = key.partition(",")
            try:
                cell = (int(row), int(col))
            except ValueError:
                continue
            if 0 <= cell[0] < board_size and 0 <= cell[1] < board_size:
                self.opponent.deposit({cell: float(value)})

    def decay(self) -> None:
        """Age both fields by one full turn.

        Ours decays too. We do not read it, but we transmit it, and a peer
        that sent an un-aged field would be advertising a trail inconsistent
        with the model both sides hash-locked.
        """
        self.own.decay()
        self.opponent.decay()

    def sample(self, cell: Position) -> float:
        """Scent intensity at ``cell`` — the opponent's, by construction."""
        return self.opponent.intensity_at(cell)

    def strongest(self) -> Position | None:
        """The opponent's most fragrant cell: the naive guess at where it is."""
        return self.opponent.strongest()

    def outgoing(self) -> dict[str, float]:
        """Our own field in wire form. The only way out of :attr:`own`."""
        return self.own.snapshot()
