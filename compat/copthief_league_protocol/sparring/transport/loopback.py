"""Both peers in one process, over the same four-tool surface as the wire.

This is not a mock. It is the same message dicts, the same tool names, the same
``{"ok": True}`` returns; only the hop is a function call. That is what lets the entire series —
handshake, six sub-games, mutual audits, artifacts — run in CI with **no dependencies installed**,
and it is why the fault injector in ``faults.py`` can prove the receiver contract without a
network to be flaky.

The four tools mirror the reference's surface exactly, including the argument-name asymmetry that
catches people out on a first meeting: ``negotiate``, ``receive_turn`` and ``receive_control``
take ``message``; ``submit_audit`` takes ``payload``.
"""

from __future__ import annotations

from collections import deque


class Inboxes:
    """One peer's four queues. A handler's whole job is to validate, enqueue, and return."""

    def __init__(self) -> None:
        self.agreements: deque[dict] = deque()
        self.turns: deque[dict] = deque()
        self.audits: deque[dict] = deque()
        self.controls: deque[dict] = deque()

    def drain(self) -> None:
        for q in (self.agreements, self.turns, self.audits, self.controls):
            q.clear()


class LoopbackPeer:
    """The callable surface one peer exposes to the other."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.inboxes = Inboxes()

    # The four tools. Each does exactly three things and returns — never blocking on game
    # progress, because two peers each awaiting the other inside a handler is an instant
    # deadlock, and that is the highest-severity failure available in this design.
    def negotiate(self, message: dict) -> dict:
        self.inboxes.agreements.append(message)
        return {"ok": True}

    def receive_turn(self, message: dict) -> dict:
        self.inboxes.turns.append(message)
        return {"ok": True}

    def submit_audit(self, payload: dict) -> dict:
        self.inboxes.audits.append(payload)
        return {"ok": True}

    def receive_control(self, message: dict) -> dict:
        self.inboxes.controls.append(message)
        return {"ok": True}


class LoopbackTransport:
    """What a peer uses to reach the other side."""

    def __init__(self, ours: LoopbackPeer, theirs: LoopbackPeer) -> None:
        self.ours = ours
        self.theirs = theirs

    # --- outbound ---------------------------------------------------------------------------
    def send_agreement(self, message: dict) -> dict:
        return self.theirs.negotiate(message)

    def send_turn(self, message: dict) -> dict:
        return self.theirs.receive_turn(message)

    def send_audit(self, payload: dict) -> dict:
        return self.theirs.submit_audit(payload)

    def send_control(self, message: dict) -> dict:
        return self.theirs.receive_control(message)

    # --- inbound ----------------------------------------------------------------------------
    def poll_agreement(self) -> dict | None:
        return self.ours.inboxes.agreements.popleft() if self.ours.inboxes.agreements else None

    def poll_turn(self) -> dict | None:
        return self.ours.inboxes.turns.popleft() if self.ours.inboxes.turns else None

    def poll_audit(self) -> dict | None:
        return self.ours.inboxes.audits.popleft() if self.ours.inboxes.audits else None

    def poll_control(self) -> dict | None:
        return self.ours.inboxes.controls.popleft() if self.ours.inboxes.controls else None


def pair(a_name: str = "A", b_name: str = "B") -> tuple[LoopbackTransport, LoopbackTransport]:
    a, b = LoopbackPeer(a_name), LoopbackPeer(b_name)
    return LoopbackTransport(a, b), LoopbackTransport(b, a)
