"""Phase 1, and the belief-only decision boundary the brain is asked across.

Split from :mod:`.subgame` unchanged. The order inside :meth:`_commit` is the
load-bearing part: seal, record, *then* send.
"""

from dataclasses import dataclass, replace
from inspect import signature

from ..domain.actions import Action, MoveAction, PlaceBarrier
from ..domain.board import BoardState, Move
from ..domain.crypto import commit_of, nonce, step_record
from ..domain.rules import position_of
from ..infra.ceremony import Commitment, Reveal
from ..infra.validation import InvalidPayloadError, require_hint
from ..strategy.base import StrategyContextError
from .subgame_scent import SubGameScent


@dataclass
class SubGameCommit(SubGameScent):
    """The sealing half of a sub-game: decide, seal, log, send."""

    def _commit(self, step: int) -> tuple[dict[str, object], Action, Reveal]:
        """Phase 1. Seal our move, record it, then send — in that order.

        The log entry is written **before** the commitment crosses the wire.
        Sending first and recording after would leave a window in which the
        opponent holds a commitment we have no record of making, which is the
        one asymmetry an append-only log exists to prevent.
        """
        decision_state, context = self._strategy_input()
        try:
            signature(self.brain.decide).bind(decision_state, **context)
        except TypeError as exc:
            raise StrategyContextError(
                "configured brain decide() must accept **context containing "
                f"{next(iter(context))}, concentration, and uncertainty"
            ) from exc
        decision = self.brain.decide(decision_state, **context)
        if not decision.hint:
            # Compatibility for configured brains that overrode ``decide``
            # before hints became a required runtime output.
            decision = replace(decision, hint="I am watching the streets")
        try:
            require_hint({"hint": decision.hint}, max_words=self.hint_max_words)
        except InvalidPayloadError as exc:
            raise StrategyContextError(f"configured brain produced an invalid hint: {exc}") from exc
        action = decision.action
        self._our_actions[step] = action
        placed = action.at if isinstance(action, PlaceBarrier) else None
        move: Move | str = action.move if isinstance(action, MoveAction) else "barrier"
        laid = self._emit(action)
        record = step_record(
            self.state,
            self.role,
            move,
            decision.intent,
            decision.hint,
            placed,
            laid,
            game_uid=self.log.game_uid,
            sub_game=self.log.sub_game,
        )
        secret = nonce()
        commitment = Commitment(
            step=step,
            sender=self.role,
            commit=commit_of(record, secret),
            timestamp=self.now(),
            game_uid=self.log.game_uid,
            sub_game=self.log.sub_game,
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
            game_uid=self.log.game_uid,
            sub_game=self.log.sub_game,
            barrier_placed=list(placed) if placed else None,
            scent=laid,
        )
        return record, action, opened

    def _strategy_input(self) -> tuple[BoardState, dict[str, object]]:
        """Return the stable, belief-only decision boundary for a strategy.

        ``state`` retains the board geometry and our exact cell, but its opponent
        coordinate is replaced by the deterministic belief peak. The keyword
        context is intentionally small and stable for configured ``**context``
        brains: role-appropriate ``target``/``threat``, ``concentration``, and
        ``uncertainty``.
        """
        self.belief.apply_barriers(self.state)
        self.belief.exclude(position_of(self.state, self._agent(self.role)))
        peak = self.belief.most_likely()
        if peak is None:
            raise StrategyContextError("opponent belief has no possible cell")
        concentration = self.belief.concentration()
        state = (
            replace(self.state, thief=peak)
            if self.role == "police"
            else replace(self.state, cop=peak)
        )
        focus = "target" if self.role == "police" else "threat"
        return state, {
            focus: peak,
            "concentration": concentration,
            "uncertainty": 1.0 - concentration,
        }
