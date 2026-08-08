"""The Appendix E rule 11 gate: byte-identical configuration on both sides.

Mixed into :class:`~.orchestrator.Orchestrator`. The digest mailbox and the
outbound call are both reached through ``self`` at the moment they are used,
so a re-pointed client and a re-bound mailbox are both honoured here.
"""

import queue
import time
from typing import Any

from ..domain.outcome import TechnicalLoss
from ..infra.inboxes import DIGEST_KEY, SERIES_KEY
from ..shared.config import config_sha256
from .orchestrator_book import CONFIG_TIMEOUT_SEC
from .orchestrator_config_digest import ConfigDigestMixin
from .orchestrator_core import MatchAborted

__all__ = [
    "ConfigMixin",
]


class ConfigMixin(ConfigDigestMixin):
    """Exchanging the configuration digest and refusing to play without it."""

    def agree_config(
        self,
        config: dict[str, Any],
        game_uid: str = "",
        timeout: float = CONFIG_TIMEOUT_SEC,
    ) -> str:
        """Exchange config digests, refusing to play unless both sides agree.

        The digest is computed from the **loaded** configuration rather than
        re-hashed from a file, so the value advertised is provably the one this
        peer is enforcing. Advertising a digest we are not playing by would be
        indistinguishable from cheating at audit.

        **Both halves are required, and only one of them used to be here.**
        Pushing our digest and reading the opponent's ``ok`` proves nothing:
        ``negotiate`` acknowledges any well-formed message, so that ``ok`` is
        the same whether they compared our parameters or never looked at them.
        Agreement is decided the other way round — by taking the digest *they*
        pushed at us and comparing it with ours.

        **Speak, then listen.** Both peers run this at the same time and each
        blocks on a message only the other can send, so a version that waited
        before announcing would be two polite peers deadlocking — the failure
        :meth:`open_series` is ordered to avoid, for the same reason.

        Args:
            game_uid: the series this digest is about, carried so an agreement
                reached for one series cannot be replayed to open another. Sent
                only when set, and enforced only when the opponent sends one
                back: the reference protocol carries the digest alone, and
                refusing a peer for speaking it would lose a match over a field
                the rulebook never asked for.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if the opponent's digest disagrees
                with ours, ``TIMEOUT`` if none arrives inside the window.
        """
        ours = config_sha256(config)
        self.beat("negotiate_config")
        message: dict[str, object] = {DIGEST_KEY: ours}
        if game_uid:
            message[SERIES_KEY] = game_uid
        reply = self.call_opponent("negotiate", {"message": message})
        if not reply.get("ok", False):
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(reply.get("detail", "")))
        self.accept_config_digest(ours, game_uid, timeout)
        return ours

    def accept_config_digest(self, ours: str, game_uid: str, timeout: float) -> str:
        """Consume the opponent's digest and refuse anything short of agreement.

        **Every** digest queued for this series has to agree, not merely the
        first. A retry re-sends the same bytes, so duplicates are ordinary and
        expected — but stopping at the first one would let a re-send that
        arrived before a contradiction stand in for the contradiction, which is
        the one arrangement of messages where a peer changing its parameters
        mid-negotiation would go unnoticed.

        Digests naming a **different** series are dropped as stale and the wait
        continues on the same deadline, so replaying an agreement from an
        earlier series buys nothing and does not shorten our patience either.

        Consumed rather than peeked, so nothing is left in the mailbox that
        could open the *next* series without a negotiation of its own.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` on disagreement, ``TIMEOUT`` if
                nothing about this series arrives before the deadline.
        """
        self.beat("await_config")
        deadline = time.monotonic() + timeout
        agreed: str | None = None
        while agreed is None:
            agreed = self.check_digest(self.wait_for_digest(deadline, timeout), ours, game_uid)
        while True:
            try:
                queued = self.inboxes.digests.get_nowait()
            except queue.Empty:
                return agreed
            self.check_digest(queued, ours, game_uid)
