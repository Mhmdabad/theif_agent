"""The Appendix E rule 23 gate: the emission model, locked before the game.

Mixed into :class:`~.orchestrator.Orchestrator`. The offer is built from the
live engine and pushed through ``self.call_opponent``, both read at call time.
"""

from ..domain.lock import ScentAgreement, ScentLock, propose
from ..domain.outcome import TechnicalLoss
from ..infra.inboxes import SCENT_DIGEST_KEY, SCENT_KEY, SERIES_KEY
from .orchestrator_book import SCENT_TIMEOUT_SEC
from .orchestrator_core import MatchAborted
from .orchestrator_scent_lock import ScentLockMixin

__all__ = [
    "ScentMixin",
]


class ScentMixin(ScentLockMixin):
    """Offering our scent model and waiting for theirs."""

    def agree_scent_model(
        self,
        game_uid: str,
        ours: ScentLock | None = None,
        timeout: float = SCENT_TIMEOUT_SEC,
    ) -> ScentAgreement:
        """Exchange the scent-emission model, refusing to play unless it is shared.

        Appendix E rule 23: the model is locked cryptographically **before** the
        game starts, and a deviation in the decay formula voids the match. The
        lock existed and was never sent — ``domain/lock.py`` had no import site
        in ``src/`` at all — so the two known divergences from the reference
        implementation surfaced as an audit failure halfway through a series
        instead of as a conversation before it opened.

        The offer is built from the **live engine** through
        :func:`~..domain.lock.propose`, never transcribed, so what we hash is
        what we will actually emit. Whatever it says, it says only about the
        published 5x5 worked example: no nonce exists yet, no commitment has
        been made, and the live board is not an input, so nothing about our
        position can travel in it.

        **Speak, then listen**, exactly as :meth:`agree_config` does and for the
        same reason: both peers run this at once and each blocks on a message
        only the other can send.

        Args:
            game_uid: the series this lock is about. Required rather than
                optional — unlike the config digest, this message is our dialect
                and not the reference's, so a peer sending one at all can bind
                it. An empty value is refused by the opponent's own door, which
                is where we would rather learn about it than at their audit.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if their model is not ours or their
                offer was refused, ``TIMEOUT`` if none arrives inside the window.
        """
        ours = ours or propose()
        self.beat("negotiate_scent")
        reply = self.call_opponent("negotiate", {"message": self.scent_offer(ours, game_uid)})
        if not reply.get("ok", False):
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(reply.get("detail", "")))
        return self.accept_scent_lock(ours, game_uid, timeout)

    @staticmethod
    def scent_offer(ours: ScentLock, game_uid: str) -> dict[str, object]:
        """The canonical offer: the model, its digest, and the series it binds."""
        return {SCENT_KEY: ours.terms(), SCENT_DIGEST_KEY: ours.digest(), SERIES_KEY: game_uid}
