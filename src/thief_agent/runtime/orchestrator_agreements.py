"""Reading greetings off the mailbox under a deadline.

Mixed into :class:`~.orchestrator.Orchestrator`. The queue is reached through
``self.inboxes`` at the moment of the read rather than held here, so these
methods see whatever mailbox the orchestrator is actually serving.
"""

import queue
from typing import Any

from ..domain.outcome import TechnicalLoss
from ..infra.handshake import Greeting, HandshakeError, check
from .orchestrator_book import GREETING_TIMEOUT_SEC
from .orchestrator_core import MatchAborted, OrchestratorCore

__all__ = [
    "AgreementsMixin",
]


class AgreementsMixin(OrchestratorCore):
    """The opponent's greeting, taken off the queue and read."""

    def latest_agreement(self, timeout: float) -> dict[str, Any]:
        """Take the **newest** greeting waiting in the mailbox, not the oldest.

        A greeting states where a peer is *now*, so an older one is superseded
        by definition. Reading the queue in arrival order would mean adopting
        an address the opponent has already left — and greetings genuinely do
        accumulate: a peer whose first announcement failed sends a second, and
        a series re-greets before every sub-game.

        The oldest-first version of this looked correct for four stages because
        nothing announced twice until tunnel rotation arrived.

        Raises:
            MatchAborted: ``TIMEOUT`` if the mailbox is empty when the window
                closes. A missed deadline is a failure, not a reason to wait.
        """
        message = self.next_agreement(timeout)
        while True:
            try:
                message = self.inboxes.agreements.get_nowait()
            except queue.Empty:
                return message

    def next_agreement(self, timeout: float) -> dict[str, Any]:
        """The next greeting off the mailbox, or a timeout. Never an unbounded wait.

        Split out from :meth:`latest_agreement` because a boundary reads the
        queue one message at a time — every greeting waiting there has to be a
        legal rotation, not merely the last one — while the opening handshake
        only wants the newest. Both need the same deadline.

        Raises:
            MatchAborted: ``TIMEOUT`` once the window closes. A missed deadline
                is a failure, not a reason to wait.
        """
        try:
            return self.inboxes.agreements.get(timeout=timeout)
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT, f"no greeting from the opponent within {timeout}s"
            ) from None

    def accept_greeting(self, ours: Greeting, timeout: float = GREETING_TIMEOUT_SEC) -> Greeting:
        """Take the opponent's greeting off the queue and decide if we can play.

        Fire-and-forget, like every other inbound message: their greeting is
        pushed into *our* server and drains from :attr:`PeerInboxes.agreements`
        rather than arriving as the return value of our own call.

        The checks live in :func:`~..infra.handshake.check`, which is the only
        validator of a greeting. Re-checking the role and version here — as an
        earlier ``check_handshake`` did — meant two validators that could
        disagree, and the pair that disagrees is always the pair that matters.

        Raises:
            MatchAborted: ``TIMEOUT`` if no greeting arrives inside the window,
                ``ILLEGAL_ACTION`` if the one that does cannot be played
                against. A missed deadline is a failure, not a reason to wait.
        """
        self.beat("accept_greeting")
        message = self.latest_agreement(timeout)
        try:
            theirs = Greeting.from_dict(message.get("greeting"))
            check(ours, theirs)
        except HandshakeError as exc:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(exc)) from exc
        return theirs
