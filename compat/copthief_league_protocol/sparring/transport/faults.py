"""Inject the hazards SPEC section 7.1 describes, deterministically.

A receiver contract tested only against a calm transport has not been tested. These are not
exotic conditions: a client that retries an in-game push on the turn budget — the behaviour that
stops a network flap from costing you the game — **is a duplicate sender by design**.

The flagship test uses this to run the same seeded six-sub-game series twice, once clean and once
with duplicates, reordering and dropped-then-retried messages, and asserts the outcome ledger is
byte-identical. That is the receiver contract proven at the level teams actually care about: not
"we handled a duplicate" but "the duplicates changed nothing about who won".
"""

from __future__ import annotations

from sparring.transport.loopback import LoopbackTransport


class FaultyTransport:
    """Wraps a transport and mistreats the turn channel in reproducible ways."""

    def __init__(self, inner: LoopbackTransport, *, duplicate_every: int = 0,
                 reorder_every: int = 0, drop_then_retry_every: int = 0) -> None:
        self.inner = inner
        self.duplicate_every = duplicate_every
        self.reorder_every = reorder_every
        self.drop_then_retry_every = drop_then_retry_every
        self._sent = 0
        self._held: dict | None = None
        self._dropped: dict | None = None

    def send_turn(self, message: dict) -> dict:
        self._sent += 1
        n = self._sent

        # Dropped, then retried on the next send — an ack lost in flight.
        if self._dropped is not None:
            self.inner.send_turn(self._dropped)
            self._dropped = None
        if self.drop_then_retry_every and n % self.drop_then_retry_every == 0:
            self._dropped = message
            return {"ok": True}          # the sender believes it went; it will be retried

        # Held back one message, then released after the next — arrival out of order.
        if self.reorder_every and n % self.reorder_every == 0 and self._held is None:
            self._held = message
            return {"ok": True}
        result = self.inner.send_turn(message)
        if self._held is not None:
            self.inner.send_turn(self._held)
            self._held = None

        # Delivered twice — the retry whose first copy did arrive.
        if self.duplicate_every and n % self.duplicate_every == 0:
            self.inner.send_turn(message)
        return result

    def flush(self) -> None:
        """Release anything still held, so a game never ends because a fault ate a message."""
        for pending in (self._dropped, self._held):
            if pending is not None:
                self.inner.send_turn(pending)
        self._dropped = self._held = None

    # Everything else passes straight through — the hazards being modelled are the turn
    # channel's, and duplicating a handshake or an audit would be a different experiment.
    def __getattr__(self, name: str):
        return getattr(self.inner, name)
