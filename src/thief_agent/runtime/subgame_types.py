"""What a sub-game says to its opponent, and what it hands back at the end.

Lifted out of :mod:`.subgame` verbatim so each module stays inside the line
budget. Nothing here knows how a sub-game is played; these are the vocabulary
the loop, the peer and the caller share, and :mod:`.subgame` re-exports every
one of them, so importers keep the address they already use.
"""

from dataclasses import dataclass
from typing import Protocol

from ..domain.board import BoardState
from ..infra.ceremony import (
    Acknowledgement,
    AuditResult,
    Commitment,
    FinalReveal,
    Reveal,
)

OPPONENT_OF = {"police": "thief", "thief": "police"}

MOVES: frozenset[str] = frozenset({"N", "S", "E", "W", "STAY"})
"""What a revealed move may be. A barrier turn reveals ``"barrier"`` instead."""


class UnplayableReveal(ValueError):
    """Raised when the opponent revealed something the board cannot be advanced by."""


class Peer(Protocol):
    """The opponent, reduced to the eight things a sub-game needs to say and hear.

    Each ``await_`` blocks until the message for that step arrives or the
    caller's deadline passes; a peer that never answers is the transport's
    problem to convert into a technical loss, not this module's to guess at.
    """

    def send_commit(self, commitment: Commitment) -> None: ...
    def await_commit(self, step: int) -> Commitment: ...
    def send_ack(self, ack: Acknowledgement) -> None: ...
    def await_ack(self, step: int) -> Acknowledgement: ...
    def send_reveal(self, opened: Reveal) -> None: ...
    def await_reveal(self, step: int) -> Reveal: ...
    def send_final(self, disclosed: FinalReveal) -> None: ...
    def await_final(self) -> FinalReveal: ...


@dataclass(frozen=True, slots=True)
class Played:
    """How a sub-game ended, the board it ended on, and whether they played fair."""

    steps: int
    final: BoardState
    captured: bool
    reason: str
    audit: AuditResult

    @property
    def thief_survived(self) -> bool:
        return not self.captured

    @property
    def opponent_played_fairly(self) -> bool:
        return self.audit.clean
