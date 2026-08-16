"""The at-least-once receiver contract (SPEC section 7.1), as an object.

The decision itself is not made here — it is ``kitref.delivery_decision``, the kit's own pinned
function, checked against ``vectors/delivery_contract.json``. This module is only the state the
decision reads. That split is on purpose: if this peer and the published table ever disagreed,
the fixtures would fail in CI rather than a game failing on a tunnel.

Why any of it is needed: HTTP is at-least-once. A push whose acknowledgement is lost is retried by
a *correct* client, so the same message arrives twice by design — not only on bad networks. A
receiver that treats the second copy as a protocol violation converts a flaky tunnel into a
technical loss, and under App. E rule 35 the missing or contradictory report that follows zeroes
**both** teams.

Note what this class does **not** hold: a reference to the deadline tracker. Tolerated traffic
cannot renew a turn deadline, and the cleanest way to guarantee that is to make it structurally
impossible to try.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sparring import kitref


class Equivocation(Exception):
    """A second, DIFFERENT commit for a step already played.

    Transport tolerance, no rules tolerance. This is not a duplicate; it is two commitments for
    one step, which is exactly what commit-reveal exists to catch. It stays loud.
    """


class ProtocolViolation(Exception):
    """An arrival past the reorder window. Let the window be the flood rule."""


@dataclass
class Inbox:
    """Ordered delivery over an unordered, duplicating transport."""

    window: int = 4
    next_step: int = 1
    played: dict[int, str] = field(default_factory=dict)
    buffered: dict[int, dict] = field(default_factory=dict)
    absorbed: int = 0

    def _state(self) -> dict:
        return {"played": {str(k): v for k, v in self.played.items()},
                "window": self.window, "next": self.next_step}

    def offer(self, message: dict) -> list[dict]:
        """Take one inbound message; return the messages now ready to apply, in step order.

        An empty list means "nothing to do yet" — the message was a duplicate we absorbed, or it
        is buffered ahead of a gap. It never means "something went wrong": that is an exception.
        """
        arrival = {"step": int(message["step"]), "commit": message["commit"]}
        decision = kitref.delivery_decision(self._state(), arrival)

        if decision in ("absorb", "discard"):
            # discard: below `next` and never played — a stale index that can never become
            # applicable (SPEC section 7.1, the row anrbj666's audit added). Counted with
            # absorbed traffic: tolerated, applied nowhere, renews nothing.
            self.absorbed += 1
            return []
        if decision == "equivocation":
            raise Equivocation(
                f"step {arrival['step']} was already played under commit "
                f"{self.played[arrival['step']]}, and a DIFFERENT commit "
                f"{arrival['commit']} has now arrived for it. Two commitments for one step is "
                f"tampering evidence, not a redelivery.")
        if decision == "violation":
            raise ProtocolViolation(
                f"step {arrival['step']} is more than {self.window} ahead of the next expected "
                f"step ({self.next_step}) — past the reorder window.")

        if decision == "buffer":
            self.buffered[arrival["step"]] = message
            return []

        # "apply": take it, then drain whatever was waiting behind it.
        ready = [message]
        self.played[arrival["step"]] = arrival["commit"]
        self.next_step = arrival["step"] + 1
        while self.next_step in self.buffered:
            nxt = self.buffered.pop(self.next_step)
            self.played[self.next_step] = nxt["commit"]
            ready.append(nxt)
            self.next_step += 1
        return ready
