"""One sub-game, start to finish: brain → ceremony → peer → log.

Every module this calls has been tested for months. **Nothing has ever called
them in sequence.** Every acceptance test to date drove them directly, which
means the seams between them were the only part of the system with no coverage
at all — and nine of the defects found in this project have been exactly there.

The order below is the rulebook's four phases, in the order Chapter 6 puts them
and the order ``test_stage6_acceptance`` already proves the ceremony expects:

1. **Commit** — both sides seal a move before either says anything about it.
2. **Acknowledge** — each confirms it holds the other's commitment. This phase
   is the one the reference implementation omits, and it is the reason the
   reveal is safe: a reveal that went out before the opponent had committed
   would let them choose their move knowing ours.
3. **Reveal** — only now, and only for a step both sides have locked.
4. **Final Reveal** — every nonce, once, at the end of the sub-game.

**The peer is a Protocol, not a client.** This module decides *what* must be
said and in what order; how it crosses the wire is :mod:`.mcp_transport`'s
problem and the entry point's. Keeping them apart is what lets a whole sub-game
run in a test against a stand-in opponent, with real digests, a real ceremony
and a real log — which is the only way to check the sequence itself.

**The log is written as the match runs, never afterwards.** A commitment is
recorded before it goes out and a reveal when it is spoken, because the *order*
in the file is the evidence: a log assembled at the end is exactly what a cheat
produces, and an auditor cannot tell the two apart.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from ..domain.actions import Action, MoveAction, PlaceBarrier, apply_action
from ..domain.axes import AxisConvention
from ..domain.board import Agent, BoardState, Move
from ..domain.crypto import commit_of, nonce, step_record
from ..domain.outcome import is_capture_by_overlap, is_enclosure_capture, is_trapping_capture
from ..domain.rules import advance_turn
from ..infra.ceremony import (
    Acknowledgement,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
)
from ..infra.match_log import MatchLog
from ..strategy.base import BrainBase

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
    """How a sub-game ended, and the board it ended on."""

    steps: int
    final: BoardState
    captured: bool
    reason: str

    @property
    def thief_survived(self) -> bool:
        return not self.captured


@dataclass
class SubGame:
    """One sub-game of one match."""

    role: str
    brain: BrainBase
    peer: Peer
    log: MatchLog
    state: BoardState
    axes: AxisConvention
    max_steps: int
    ceremony: MatchCeremony = field(init=False)
    now: Callable[[], str] = field(default=lambda: "")

    def __post_init__(self) -> None:
        self.ceremony = MatchCeremony(role=self.role)

    @property
    def opponent(self) -> str:
        return OPPONENT_OF[self.role]

    def play(self) -> Played:
        """Run until capture or the step limit, then disclose every nonce.

        The loop stops the moment a capture is on the board rather than
        finishing the step count. A sub-game that continued past a capture
        would produce a log whose later steps describe a game that was already
        over, and two peers disagreeing about when it ended is a disagreement
        about the result.
        """
        played = 0
        for step in range(1, self.max_steps + 1):
            played = step
            self._one_step(step)
            if self._captured():
                self._disclose()
                return Played(step, self.state, captured=True, reason="capture")
        self._disclose()
        return Played(played, self.state, captured=False, reason="step limit reached")

    def _one_step(self, step: int) -> None:
        """Advance the board's own step counter *before* anything is sealed.

        ``step_record`` seals ``state.step``, and the Replay App checks that
        number against the slot the row was filed under — the anti-replay rule
        from #102. A loop that committed while the board still said ``step - 1``
        would produce a log in which every row seals the wrong number, and the
        stamp on every honest match this agent ever played would be
        ``TAMPERED``. It is the loop's job to keep the board and the ceremony
        counting the same thing.
        """
        self.state = advance_turn(self.state)
        record, action, opened = self._commit(step)
        self._acknowledge(step)
        self._reveal(step, record, opened)
        self._advance(action, self.peer_move(step))

    def _commit(self, step: int) -> tuple[dict[str, object], Action, Reveal]:
        """Phase 1. Seal our move, record it, then send — in that order.

        The log entry is written **before** the commitment crosses the wire.
        Sending first and recording after would leave a window in which the
        opponent holds a commitment we have no record of making, which is the
        one asymmetry an append-only log exists to prevent.
        """
        decision = self.brain.decide(self.state)
        action = decision.action
        placed = action.at if isinstance(action, PlaceBarrier) else None
        move: Move | str = action.move if isinstance(action, MoveAction) else "barrier"
        record = step_record(self.state, self.role, move, decision.intent, decision.hint, placed)
        secret = nonce()
        commitment = Commitment(
            step=step,
            sender=self.role,
            commit=commit_of(record, secret),
            timestamp=self.now(),
        )
        self.ceremony.at(step).commit(commitment, secret)
        self.log.commit(step, commitment.commit)
        if decision.reasoning:
            self.log.discuss(step, {"intent": decision.intent, "reasoning": decision.reasoning})
        self.peer.send_commit(commitment)
        self.ceremony.at(step).receive(self.peer.await_commit(step))

        opened = Reveal(
            step=step,
            sender=self.role,
            move=move,
            intent=decision.intent,
            hint=decision.hint,
            timestamp=self.now(),
            barrier_placed=list(placed) if placed else None,
        )
        return record, action, opened

    def _acknowledge(self, step: int) -> None:
        """Phase 2. The phase the reference skips, and the reason reveal is safe."""
        self.peer.send_ack(self.ceremony.at(step).acknowledge(self.now()))
        self.ceremony.at(step).receive_ack(self.peer.await_ack(step))

    def _reveal(self, step: int, record: dict[str, object], opened: Reveal) -> None:
        """Phase 3. Only reachable once both sides are locked."""
        self.ceremony.at(step).reveal(opened)
        self.log.reveal(step, record)
        self.peer.send_reveal(opened)
        self._peer_reveals[step] = self.ceremony.at(step).receive_reveal(
            self.peer.await_reveal(step)
        )

    _peer_reveals: dict[int, Reveal] = field(default_factory=dict, init=False)

    def peer_move(self, step: int) -> Action | None:
        """What the opponent said they did, once they have said it."""
        opened = self._peer_reveals.get(step)
        if opened is None:
            return None
        if opened.barrier_placed:
            if self.opponent != "police":
                raise UnplayableReveal(
                    f"the thief revealed a barrier at step {step}; only the cop may place "
                    "one, and a board advanced by an illegal action is a board the two "
                    "peers no longer share"
                )
            return PlaceBarrier(at=(opened.barrier_placed[0], opened.barrier_placed[1]))
        if opened.move not in MOVES:
            raise UnplayableReveal(
                f"the {self.opponent} revealed move {opened.move!r} at step {step}, which is "
                "not a move; the board cannot be advanced from a statement it cannot read"
            )
        return MoveAction(move=cast("Move", opened.move))

    def _advance(self, ours: Action, theirs: Action | None) -> None:
        """Apply both moves to one board.

        Ours first, then theirs, and both against the same starting state as
        far as legality is concerned — the two were chosen simultaneously and
        neither saw the other. Applying them in sequence is the only thing a
        single board can do; what must not happen is either side *deciding*
        with knowledge of the other, and the ceremony above is what prevents it.
        """
        self.state = apply_action(self.state, self._agent(self.role), ours, self.axes)
        if theirs is not None:
            self.state = apply_action(self.state, self._agent(self.opponent), theirs, self.axes)

    @staticmethod
    def _agent(role: str) -> Agent:
        return "cop" if role == "police" else "thief"

    def _captured(self) -> bool:
        """Any of the three capture conditions the rulebook defines."""
        return (
            is_capture_by_overlap(self.state)
            or is_trapping_capture(self.state)
            or is_enclosure_capture(self.state, self.axes)
        )

    def _disclose(self) -> None:
        """Phase 4. Every nonce, once, and only now.

        ``finish()`` is what makes the nonces releasable at all — the ceremony
        refuses to produce them while any step is still open, so a sub-game
        that ended early cannot leak a secret for a step nobody has revealed.
        """
        self.ceremony.finish()
        disclosed = self.ceremony.final_reveal(self.now())
        for step, secret in disclosed.nonces.items():
            self.log.disclose(step, secret)
        self.peer.send_final(disclosed)
        self.ceremony.receive_final_reveal(self.peer.await_final())
