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

from dataclasses import dataclass

from ..domain.rules import advance_turn
from ..infra.ceremony import Reveal
from .subgame_audit import SubGameAudit
from .subgame_types import MOVES, OPPONENT_OF, Peer, Played, UnplayableReveal

__all__ = [
    "MOVES",
    "OPPONENT_OF",
    "Peer",
    "Played",
    "SubGame",
    "UnplayableReveal",
]
"""Re-exported explicitly: ``no_implicit_reexport`` rejects importers otherwise.

Every name this module exported before the split is still exported from here,
so ``from ..runtime.subgame import Played, SubGame`` keeps meaning what it did.
"""


@dataclass
class SubGame(SubGameAudit):
    """One sub-game of one match."""

    def play(self) -> Played:
        """Run until capture or the step limit, then disclose every nonce.

        The loop stops the moment a capture is on the board rather than
        finishing the step count. A sub-game that continued past a capture
        would produce a log whose later steps describe a game that was already
        over, and two peers disagreeing about when it ended is a disagreement
        about the result.
        """
        if self._captured():
            self._disclose()
            return self._finished(0, captured=True, reason="capture")
        played = 0
        for step in range(1, self.max_steps + 1):
            played = step
            self._one_step(step)
            if self._captured():
                self._disclose()
                return self._finished(step, captured=True, reason="capture")
        self._disclose()
        return self._finished(played, captured=False, reason="step limit reached")

    def _finished(self, steps: int, *, captured: bool, reason: str) -> Played:
        self.play_result = Played(steps, self.state, captured, reason, self.audit())
        return self.play_result

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
        self.sealed_states[step] = self.state
        record, action, opened = self._commit(step)
        self._acknowledge(step)
        self._reveal(step, record, opened)
        self._advance(action, self.peer_move(step))
        self._observe(step)
        self.scent.decay()

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
        self.received_hints[step] = self._peer_reveals[step].hint
