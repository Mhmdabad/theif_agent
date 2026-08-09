"""Steps 1 and 2: the addresses in force, and the terms both sides signed.

Split from :mod:`.match` unchanged. Nothing here caches what it reads: the
peering is taken off ``self`` at the moment it is used, because
:meth:`MatchAgreement.rehandshake` reassigns it at every sub-game boundary.
"""

from dataclasses import dataclass

from ..domain.lock import ScentAgreement
from ..domain.outcome import TechnicalLoss
from ..infra.handshake import Peering
from .match_state import MatchState
from .orchestrator import CONFIG_TIMEOUT_SEC, GREETING_TIMEOUT_SEC, MatchAborted

__all__ = ["MatchAgreement"]


@dataclass
class MatchAgreement(MatchState):
    """The two agreements a series opens on, and the boundary that renews one."""

    def agree(self, timeout: float = CONFIG_TIMEOUT_SEC) -> str:
        """Step 2: refuse to start unless both sides hold the same parameters.

        Before any move, because a mismatch discovered mid-match is a match
        already spoiled — the steps played under the wrong physics cannot be
        un-played, and both sides have logs nobody can reconcile.

        **Two agreements, in this order.** Appendix E rule 11 fixes the
        parameters and rule 23 fixes the scent-emission model, and they are not
        the same document: the config digest covers ``game.json``, while the
        emission kernel, its falloff, its rounding and the dialect the field
        travels in live in the code and would pass a config comparison
        untouched. The parameters go first because two peers who cannot agree
        what board they are on have nothing to say about pheromones on it.

        Both are bound to this runner's ``game_uid``, so the series the
        declaration names and the series we negotiated are provably the same
        one. Without it an agreement reached for an earlier series could be
        replayed to open this one, and the declaration would record a
        negotiation that never happened.

        **The mailboxes are bound before the first digest goes out**, because
        this is the message the opponent is waiting for before it sends anything
        of its own. Their opening commitment can only follow an agreement we
        completed, and an agreement we completed can only follow one we sent, so
        binding first is what puts their first packet after our door opening —
        rather than in the window where the door names nothing and would have to
        guess.

        Returns:
            The config digest. The scent agreement is kept on
            :attr:`scent_lock`, because it is not a digest but a set of terms
            the sub-games have to be played under.
        """
        self.orchestrator.inboxes.bind(self.declaration.game_uid, 1)
        digest = self.orchestrator.agree_config(
            self.parameters, game_uid=self.declaration.game_uid, timeout=timeout
        )
        self.scent_lock = self.orchestrator.agree_scent_model(
            game_uid=self.declaration.game_uid, timeout=timeout
        )
        return digest

    def locked_scent(self) -> ScentAgreement:
        """The agreed model, or a refusal to open a sub-game without one.

        The alternative — falling back to a default — is precisely the silent
        downgrade this gate exists to prevent. A peer that never locked a model
        is a peer whose field we cannot check, and the rulebook's price for a
        series played on an unfixed model is the match.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` when no lock was agreed.
        """
        if self.scent_lock is None:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                "no scent-emission model was locked with the opponent; Appendix E "
                "rule 23 fixes it cryptographically before the game starts, and a "
                "sub-game opened without one is played on a field neither side can "
                "check — call agree() before playing",
            )
        return self.scent_lock

    def peered(self) -> Peering:
        """The addresses in force, or a refusal to play a series that agreed none.

        The alternative — playing on whatever the private config bootstrapped
        us with — is a series whose declaration names addresses nobody traded,
        and one that could not re-handshake because it has nothing to compare a
        fresh greeting against.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` when no handshake opened the series.
        """
        if self.peering is None:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                "no addresses were agreed with the opponent; a series opens by "
                "trading greetings through open_series, and one that skipped it "
                "has nothing to re-handshake against between its sub-games",
            )
        return self.peering

    def rehandshake(self, number: int, timeout: float = GREETING_TIMEOUT_SEC) -> Peering:
        """Re-agree the addresses at the boundary before sub-game ``number``.

        The addresses we announce are the ones already agreed: our own tunnel
        rotating is a discovery the driver makes, not something a series loop
        can invent. What this recovers from is *their* tunnel rotating, which is
        the case the loop can neither predict nor be told about — and it is the
        common one, because a free-tier tunnel issues a new URL on every restart.

        The result replaces :attr:`peering` only once it is agreed, so a refused
        boundary leaves the series pointing where it was rather than half-moved.

        **The mailboxes cross the boundary before the announcement does.** The
        announcement is what tells the opponent we have reached ``number``, and
        they open the sub-game by sending into our door, so a door bound after
        the announcement is one we have invited a message through before opening
        it. That is the same window that let a packet in before any binding
        existed, one boundary further along, and it is closed the same way:
        by saying where we are only once we can act on the answer.
        """
        self.orchestrator.inboxes.bind(self.declaration.game_uid, number)
        current = self.peered()
        self.peering = self.orchestrator.rehandshake(
            current, current.ours, number, self.directory, self.game_id, timeout
        )
        return self.peering
