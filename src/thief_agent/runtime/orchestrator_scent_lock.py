"""Consuming the opponent's scent-model offers and settling them.

Mixed into :class:`~.orchestrator.Orchestrator`. Split from :mod:`.orchestrator_scent`,
which owns the offer we make; this side owns the offers we are sent. The
mailbox is read through ``self.inboxes`` at the moment of the read.
"""

import queue
import time
from typing import Any

from ..domain.lock import ScentAgreement, ScentLock, disputes
from ..domain.outcome import TechnicalLoss
from ..infra.inboxes import SCENT_DIGEST_KEY, SCENT_KEY, SERIES_KEY
from .orchestrator_core import MatchAborted, OrchestratorCore

__all__ = [
    "ScentLockMixin",
]


class ScentLockMixin(OrchestratorCore):
    """Every offer queued for this series, not merely the first."""

    def accept_scent_lock(self, ours: ScentLock, game_uid: str, timeout: float) -> ScentAgreement:
        """Consume the opponent's offers and refuse anything short of agreement.

        **Every** offer queued for this series has to agree, not merely the
        first, for the reason the config gate already gives: a retry re-sends
        the same bytes, so duplicates are ordinary — but stopping at the first
        would let a re-send stand in for a contradiction queued behind it, which
        is the one arrangement of messages where a peer changing its model
        mid-negotiation goes unnoticed.

        Offers naming a **different** series are dropped as stale and the wait
        continues on the same deadline. Consumed rather than peeked, so nothing
        is left behind that could open the *next* series unlocked.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` on disagreement, ``TIMEOUT`` if
                nothing about this series arrives before the deadline.
        """
        self.beat("await_scent")
        deadline = time.monotonic() + timeout
        settled: ScentAgreement | None = None
        while settled is None:
            settled = self.check_scent_lock(
                self.wait_for_scent_lock(deadline, timeout), ours, game_uid
            )
        while True:
            try:
                queued = self.inboxes.scent_locks.get_nowait()
            except queue.Empty:
                return settled
            self.check_scent_lock(queued, ours, game_uid)

    def wait_for_scent_lock(self, deadline: float, timeout: float) -> dict[str, Any]:
        """The next offer, or a timeout. Never an unbounded wait.

        Raises:
            MatchAborted: ``TIMEOUT`` once the deadline passes. A peer that
                offers no model has not agreed one, and Appendix E rule 23 voids
                a match played on a model nobody fixed.
        """
        try:
            return self.inboxes.scent_locks.get(timeout=max(deadline - time.monotonic(), 0.0))
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT,
                f"no scent-model lock from the opponent within {timeout:g}s; Appendix E "
                "rule 23 fixes the emission model before the game starts, and a peer "
                "that will not lock one cannot produce a heatmap either side can check",
            ) from None

    def check_scent_lock(
        self, body: dict[str, Any], ours: ScentLock, game_uid: str
    ) -> ScentAgreement | None:
        """Their offer settled, or ``None`` if it is not about this series.

        Decided by :func:`~..domain.lock.disputes`, which is where the physics
        live: this class coordinates and does not decide, and a second opinion
        about the model here is a second opinion that can disagree with the one
        both repositories share.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if their model is not ours.
        """
        about = str(body.get(SERIES_KEY, ""))
        if about != game_uid:
            self.beat(f"stale-scent-lock:{about}")
            return None
        offer = body.get(SCENT_KEY)
        problems = disputes(
            ours, offer if isinstance(offer, dict) else {}, str(body.get(SCENT_DIGEST_KEY, ""))
        )
        if problems:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                "; ".join(problems) + "; Appendix E rule 23 locks the scent-emission "
                "model before the game starts and prices a deviation in the decay "
                "formula at a void match, so the remedy is negotiation between the "
                "teams rather than a series played on two different fields",
            )
        return ours.agreement()
