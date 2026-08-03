"""The legal phases of a single turn.

Appendix E rules 4 and 5: game phases run through a strict state machine, and
any transition not in the table is rejected immediately.

The point is not bookkeeping. In a peer-to-peer game with no referee, an
undefined state is how two agents end up waiting for each other forever — and
a deadlock produces no error, no result, and a technical loss scoring **zero
for both sides**. Raising on an illegal transition converts a logic bug into a
visible development-time failure instead of a silent stall during a match.
"""

from enum import Enum


class Phase(Enum):
    """Where a turn currently is."""

    WAITING_FOR_OPPONENT = "waiting_for_opponent"
    COMPUTING_MOVE = "computing_move"
    COMMITTING = "committing"
    AWAITING_REVEAL = "awaiting_reveal"
    VERIFYING = "verifying"
    TECHNICAL_LOSS = "technical_loss"


TRANSITIONS: dict[Phase, frozenset[Phase]] = {
    Phase.WAITING_FOR_OPPONENT: frozenset({Phase.COMPUTING_MOVE}),
    Phase.COMPUTING_MOVE: frozenset({Phase.COMMITTING, Phase.TECHNICAL_LOSS}),
    Phase.COMMITTING: frozenset({Phase.AWAITING_REVEAL, Phase.TECHNICAL_LOSS}),
    Phase.AWAITING_REVEAL: frozenset({Phase.VERIFYING, Phase.TECHNICAL_LOSS}),
    Phase.VERIFYING: frozenset({Phase.WAITING_FOR_OPPONENT, Phase.TECHNICAL_LOSS}),
    Phase.TECHNICAL_LOSS: frozenset(),
}
"""Legal successors per phase. ``TECHNICAL_LOSS`` is terminal."""


class IllegalTransitionError(RuntimeError):
    """Raised when a phase change is not in the transition table."""


class GamePhaseMachine:
    """Enforces the turn cycle, refusing anything off the table."""

    def __init__(self, phase: Phase = Phase.WAITING_FOR_OPPONENT) -> None:
        self._phase = phase
        self.history: list[Phase] = [phase]

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def is_terminal(self) -> bool:
        return not TRANSITIONS[self._phase]

    def can(self, target: Phase) -> bool:
        """Whether ``target`` is a legal successor of the current phase."""
        return target in TRANSITIONS[self._phase]

    def to(self, target: Phase) -> Phase:
        """Move to ``target``.

        Raises:
            IllegalTransitionError: if the transition is not in the table. It
                raises rather than returning a flag: a caller that can ignore
                the result is a caller that will, and the consequence is an
                undefined state rather than a wrong one.
        """
        if not self.can(target):
            legal = sorted(p.value for p in TRANSITIONS[self._phase])
            raise IllegalTransitionError(
                f"illegal transition {self._phase.value} -> {target.value}; "
                f"legal from here: {legal or ['(terminal)']}"
            )
        self._phase = target
        self.history.append(target)
        return target

    def abort(self, reason: str = "") -> Phase:
        """Move to ``TECHNICAL_LOSS`` from any non-terminal phase.

        Every communication phase can fail, so the escape hatch exists from all
        of them. It is a method rather than a bare transition so an abort is
        greppable in the history and cannot be confused with normal progress.
        """
        if self.is_terminal:
            raise IllegalTransitionError(f"already terminal in {self._phase.value}: {reason}")
        self._phase = Phase.TECHNICAL_LOSS
        self.history.append(Phase.TECHNICAL_LOSS)
        return self._phase
