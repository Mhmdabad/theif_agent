"""The mandatory state machine (book ch.8, App. E rules 4-5).

The book requires game states to be managed by a proper state machine and **every illegal
transition to be rejected**. The sanction for not doing so is a technical loss, which zeroes both
sides — so this is cheap insurance against a whole class of bug.

``TECHNICAL_LOSS`` is absorbing on purpose. A sub-game that reaches it is over, but the *series*
is not: a series is six sub-games, and abandoning the rest would leave the opponent playing a
match we had quietly quit.
"""

from __future__ import annotations

from enum import Enum


class PeerState(str, Enum):
    WAITING_FOR_OPPONENT = "WAITING_FOR_OPPONENT"
    COMPUTING_MOVE = "COMPUTING_MOVE"
    COMMITTING = "COMMITTING"
    AWAITING_REVEAL = "AWAITING_REVEAL"
    VERIFYING = "VERIFYING"
    TECHNICAL_LOSS = "TECHNICAL_LOSS"


TRANSITIONS: dict[PeerState, frozenset[PeerState]] = {
    PeerState.WAITING_FOR_OPPONENT: frozenset({PeerState.COMPUTING_MOVE,
                                               PeerState.TECHNICAL_LOSS}),
    PeerState.COMPUTING_MOVE: frozenset({PeerState.COMMITTING, PeerState.TECHNICAL_LOSS}),
    PeerState.COMMITTING: frozenset({PeerState.AWAITING_REVEAL, PeerState.TECHNICAL_LOSS}),
    PeerState.AWAITING_REVEAL: frozenset({PeerState.VERIFYING, PeerState.TECHNICAL_LOSS}),
    PeerState.VERIFYING: frozenset({PeerState.WAITING_FOR_OPPONENT, PeerState.TECHNICAL_LOSS}),
    PeerState.TECHNICAL_LOSS: frozenset(),
}


class IllegalTransition(Exception):
    pass


class PeerStateMachine:
    def __init__(self, start: PeerState = PeerState.WAITING_FOR_OPPONENT) -> None:
        self.state = start
        self.history: list[PeerState] = [start]

    def to(self, target: PeerState) -> PeerState:
        if target not in TRANSITIONS[self.state]:
            raise IllegalTransition(
                f"{self.state.value} -> {target.value} is not a legal transition; "
                f"legal from here: {sorted(s.value for s in TRANSITIONS[self.state])}")
        self.state = target
        self.history.append(target)
        return target

    def fail(self) -> None:
        """Enter the absorbing terminal state from anywhere. Always legal; never reversible."""
        if self.state is not PeerState.TECHNICAL_LOSS:
            self.state = PeerState.TECHNICAL_LOSS
            self.history.append(self.state)

    @property
    def finished(self) -> bool:
        return self.state is PeerState.TECHNICAL_LOSS
