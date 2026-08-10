"""Steps 3 and 4: the series, the boundaries between its sub-games, and a board.

Split from :mod:`.match` unchanged. The loop lives one link below
:class:`~.match_agreement.MatchAgreement` because a boundary is an agreement
being renewed, and it calls it through ``self`` so the peering it re-points is
the one every later message is addressed from.
"""

from dataclasses import dataclass

from ..infra.match_log import MatchLog
from ..shared.config import config_sha256
from .match_agreement import MatchAgreement
from .match_outcome import SubGameOutcome
from .peer import McpPeer
from .subgame import SubGame

__all__ = ["MatchPlay"]


@dataclass
class MatchPlay(MatchAgreement):
    """A whole series, and one numbered sub-game of it."""

    def play_series(self, timeout: float = 30.0) -> list[SubGameOutcome]:
        """Step 3 for the whole series: every numbered sub-game, in order.

        The length is resolved *before* the first sub-game, so a configuration
        that deviates costs nothing — no board is played under it, and the
        opponent never sees a series that stops short of the book.

        **Every pair of sub-games is separated by a re-handshake**, which is the
        thing this loop had none of. ``rehandshake`` was written, documented and
        never called: six sub-games ran back to back, so a tunnel that rotated
        partway through killed the series — and a technical loss scores zero for
        *both* sides, so it destroyed the sub-games already won on the board too.

        Five boundaries, at 1→2 through 5→6. Not before the first, which the
        opening handshake already covered, and not after the last, where an
        announcement is a message nobody is waiting for.

        The peering is resolved alongside the length and for the same reason: a
        series that cannot re-handshake is one that will lose a board it has
        already won, and the cheapest moment to say so is before there is a
        board to lose. The length goes first of the two because a deviating
        configuration is a fault of our own that needs no opponent to diagnose.
        """
        length = self.sub_games
        self.peered()
        played: list[SubGameOutcome] = []
        for number in range(1, length + 1):
            if number > 1:
                self.rehandshake(number, timeout)
            played.append(self.play_sub_game(number, timeout))
        return played

    def play_sub_game(self, number: int, timeout: float = 30.0) -> SubGameOutcome:
        """Steps 3 and 4 for one sub-game.

        The scent rules are read from the agreement before anything else, so a
        series that never locked a model costs a refusal rather than a board.

        **The mailbox ledgers are not emptied here, and emptying them was a
        bug.** Both are keyed by the sub-game a message is bound to, so a new
        sub-game cannot collide with an old one and nothing needs forgetting.
        Clearing them looked like a per-sub-game reset and was really a reset of
        *shared* state on our own schedule: the opponent pushes this sub-game's
        first turn when their thread reaches the boundary, which under load is
        before ours does, so the clear regularly destroyed the ledger entry for
        a turn already accepted — and the reveal that opened it was then refused
        as uncommitted, deadlocking the series. Advancing the binding below is
        safe in a way the clear was not: it only ever moves forward, and the
        ledgers are keyed by it, so nothing that is still current is forgotten.

        The bind here is ordinarily a repeat of the one :meth:`agree` or
        :meth:`rehandshake` already did — those are where the boundary is
        actually crossed, ahead of the message that invites a reply. It stays
        because a sub-game can be played directly, and a door left on the
        previous sub-game would defer every packet of this one until the
        opponent's retry budget ran out.
        """
        locked = self.locked_scent()
        self.orchestrator.inboxes.bind(self.declaration.game_uid, number)
        hint_max_words = int(self.parameters.get("hint_max_words", 15))
        self.orchestrator.inboxes.hint_max_words = hint_max_words
        role = self.role_in(number)
        log = MatchLog(
            game_id=self.game_id,
            sub_game=number,
            role=role,
            game_uid=self.declaration.game_uid,
            config_sha256=config_sha256(self.parameters),
        )
        game = SubGame(
            role=role,
            brain=self.brain_for(number),
            peer=McpPeer(
                role=role,
                client=self.orchestrator.client,
                inboxes=self.orchestrator.inboxes,
                now=self.now(),
                timeout=timeout,
                hint_max_words=hint_max_words,
                game_uid=self.declaration.game_uid,
                sub_game=number,
            ),
            log=log,
            state=self.start,
            axes=self.axes,
            max_steps=self.max_steps,
            hint_max_words=hint_max_words,
            now=self.now,
            require_bound_scent=locked.require_bound_scent,
        )
        played = game.play()
        outcome = SubGameOutcome(
            number=number, played=played, audit=game.audit(), log=log, game=game, our_role=role
        )
        self.outcomes.append(outcome)
        return outcome
