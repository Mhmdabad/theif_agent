"""One digest message, waited for and compared.

Split from :mod:`.orchestrator_config`, which owns the exchange these two are
the reading half of. Mixed into :class:`~.orchestrator.Orchestrator`; the
mailbox is reached through ``self.inboxes`` at the moment of the read.
"""

import queue
import time
from typing import Any

from ..domain.outcome import TechnicalLoss
from ..infra.inboxes import DIGEST_KEY, SERIES_KEY
from ..shared.config import digests_agree
from .orchestrator_core import MatchAborted, OrchestratorCore

__all__ = [
    "ConfigDigestMixin",
]


class ConfigDigestMixin(OrchestratorCore):
    """The opponent's digest, read off the mailbox and checked against ours."""

    def wait_for_digest(self, deadline: float, timeout: float) -> dict[str, Any]:
        """The next digest message, or a timeout. Never an unbounded wait.

        Raises:
            MatchAborted: ``TIMEOUT`` once the deadline passes. Silence at this
                gate is a refusal to agree, not a reason to wait longer.
        """
        try:
            return self.inboxes.digests.get(timeout=max(deadline - time.monotonic(), 0.0))
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT,
                f"no config digest from the opponent within {timeout:g}s; an "
                "unanswered agreement is a refusal to agree, and a series played "
                "without one is void either way",
            ) from None

    def check_digest(self, body: dict[str, Any], ours: str, game_uid: str) -> str | None:
        """Their digest from one message, or ``None`` if it is not about this series.

        Compared in constant time through :func:`~..shared.config.digests_agree`,
        against the canonical lowercase form :func:`require_digest` normalises to
        at the door — so this only ever compares two values of the same shape.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if their parameters are not ours.
        """
        theirs = str(body.get(DIGEST_KEY, ""))
        about = str(body.get(SERIES_KEY, ""))
        if game_uid and about and about != game_uid:
            self.beat(f"stale-digest:{about}")
            return None
        if not digests_agree(ours, theirs):
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                f"the opponent is playing by {theirs} and we are playing by {ours}; "
                "Appendix E rule 11 requires byte-identical configuration on both "
                "sides, and a series played on two sets of physics produces two "
                "logs nobody can reconcile — zero for both teams",
            )
        return theirs
