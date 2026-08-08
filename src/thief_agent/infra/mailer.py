"""Actually sending the report, once every gate has said yes.

Everything this needs already existed and nothing tied it together: :mod:`.report`
builds the message, :mod:`.gatekeeper` runs the three gates, :mod:`.token_store`
holds the credential. Nothing called the API.

FR-7.15 is what makes that urgent rather than tidy — **a side that does not
report receives no points for the match, even if it won on the board.** The
difference between playing correctly and scoring.

**The order is the requirement, and it is enforced here rather than hoped for.**

1. ``admit()`` — all three gates, and the quota slot is reserved *before* the
   send, so a crash between the call and the response cannot leave a message
   that went out uncounted.
2. ``record_attempt()`` — on **every** attempt, including the ones that fail.
   The DOS detector is looking for the shape of a loop, and a loop that fails
   every time is the one most likely to be running.
3. the send.
4. a 429 goes to ``on_429()``, never to a retry. FR-7.22: insisting is what
   gets an account suspended by the provider.

**The API is a seam.** :class:`Sender` is a Protocol and :func:`gmail_sender`
is the only code that imports a Google library. Every rule above is therefore
testable against a counting fake — which is the only responsible way to test a
component whose failure mode is *sending real mail to a lecturer*.

**Nothing here decides to send.** :meth:`Mailer.send_report` is called by a
person or by a match that has finished and been agreed; this module has no
schedule, no retry-forever, and no opinion about when a report is due.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .gatekeeper import TOO_MANY_REQUESTS, Gatekeeper, TooManyRequests, Wait, status_code_of
from .mailer_provider import Sender, gmail_sender, retry_after_of
from .report import Message, Report
from .token_bucket import RateLimitError

LECTURER_NOTE = (
    "This module does not decide to send. A real report goes to a real lecturer, "
    "so the decision is a person's: nothing here is scheduled, nothing retries "
    "forever, and no test in this repository has ever contacted Google."
)
"""Why there is no 'send when ready' path, stated where somebody would add one."""


class SendError(RuntimeError):
    """Raised when a report could not be sent and no further attempt is allowed."""


@dataclass
class Mailer:
    """One report, through the gates, to the API."""

    gatekeeper: Gatekeeper
    sender: Sender
    sleep: Callable[[float], None] = field(default=time.sleep)
    waits: list[str] = field(default_factory=list, init=False)
    """Every pause and why, so a slow send can be told from a stalled one."""

    def send_report(self, report: Report, sender_address: str) -> dict[str, Any]:
        """Send one report. Returns whatever the API said.

        Raises:
            SendError: when a gate refused outright, when the retry budget is
                spent, or when the provider kept saying 429. Never silently
                gives up — a report that was not sent costs the match's points,
                so the caller has to be told.
        """
        message = Message(report=report, sender=sender_address)
        payload = message.raw()

        attempt = 0
        while True:
            self._admit()
            self.gatekeeper.record_attempt()
            try:
                return self.sender.send(payload)
            except Exception as exc:  # noqa: BLE001 - re-raised or converted below
                if status_code_of(exc) != TOO_MANY_REQUESTS:
                    raise
                attempt += 1
                self._back_off(exc, attempt)

    def _admit(self) -> None:
        """Run the gates, waiting when the bucket says *not yet*.

        A :class:`~.gatekeeper.Wait` is not a refusal, so it is slept through
        and the gates re-run — the quota is only charged once a request is
        actually going out, so waiting costs nothing but time.
        """
        while True:
            try:
                verdict = self.gatekeeper.admit()
            except Exception as exc:  # noqa: BLE001 - a gate said no; that is final
                raise SendError(f"the report was not sent: {exc}") from exc
            if verdict is None:
                return
            self._pause(verdict)

    def _pause(self, verdict: Wait) -> None:
        self.waits.append(str(verdict))
        try:
            self.sleep(verdict.seconds)
        finally:
            self.gatekeeper.release()

    def _back_off(self, exc: object, attempt: int) -> None:
        """Honour a 429. Never an immediate retry.

        Raises:
            SendError: once ``max_retries`` is spent. ``on_429`` refuses to
                describe an attempt that must not happen, and that refusal is
                the end of the road rather than something to work around.
        """
        try:
            told = self.gatekeeper.on_429(attempt, retry_after_of(exc))
        except RateLimitError as spent:
            raise SendError(
                f"the provider refused {attempt} times and the retry budget is spent; "
                "the report was not sent. Insisting past this is what gets an account "
                "suspended, so it stops here"
            ) from spent
        self.waits.append(str(told))
        self.sleep(told.retry_after)


__all__ = ["Mailer", "SendError", "Sender", "TooManyRequests", "gmail_sender", "retry_after_of"]
