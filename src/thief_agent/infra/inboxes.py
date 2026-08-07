"""The peer's mailboxes and the four tools that fill them.

The reference model is fire-and-forget: the opponent pushes a message into our
server, the tool enqueues it and returns ``{"ok": True}`` immediately, and our
runtime drains the queue on its own schedule. Replies travel as separate pushes
into *their* server, not as return values.

That decoupling is why a peer can be slow without being stalled — accepting a
message costs nothing, so a busy runtime never makes the opponent's send time
out. It also means an inbound message can never block on our decision-making,
which is where the language-model deadline lives.

Validation happens **at the door**, before anything reaches a queue. A malformed
message is refused and recorded rather than enqueued for a consumer that would
have to handle it mid-turn.
"""

import hashlib
import queue
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..shared.config import canonical_bytes
from .ceremony import CeremonyError, Reveal
from .protocol import AuditPayload, ControlMessage, TurnMessage
from .validation import (
    InvalidPayloadError,
    optional_scent,
    require_digest,
    require_mapping,
    require_str,
)


def fingerprint(turn: TurnMessage) -> str:
    """A digest of everything a turn asserts.

    Canonical serialisation, so two peers hashing the same turn agree — the
    same rule already used for ``config_sha256``. Comparing digests rather than
    objects means a re-send is recognised even after a round trip through JSON,
    where dictionary order and integer/float typing need not survive.
    """
    return hashlib.sha256(canonical_bytes(turn.to_dict())).hexdigest()


DIGEST_KEY = "config_sha256"
"""What makes a negotiation message a config digest rather than a greeting."""

SERIES_KEY = "game_uid"
"""Which series a digest is about. Optional: the reference sends the digest alone.

Carried when the sender offers it so a digest agreed for one series cannot be
replayed to open another. Absence is not suspicious — it is what a reference
implementation looks like — so it is treated as *unbound* rather than as stale;
only a message naming a **different** series is refused downstream.

**Required on a scent-lock offer, and optional only on a config digest.** The
lock is this project's dialect rather than the reference's: a peer speaking it
at all is speaking ours, so an offer that will not say which series it is about
is a message we have no honest reading of. Accepting it as "unbound" would let
a lock agreed for a finished series open the next one, which is the one thing
binding exists to prevent.
"""

SCENT_KEY = "scent_lock"
"""What makes a negotiation message a scent-model offer.

Appendix E rule 23 locks the emission model cryptographically *before* the game
starts, and this is the message that does it. A third body on the one
negotiation channel, routed on content exactly as the digest is, because the
wire cannot distinguish them: greeting, digest and lock all arrive as
``negotiate``.
"""

SCENT_DIGEST_KEY = "scent_sha256"
"""The digest of the offered model. Named apart from ``config_sha256``.

Two digests over two different agreements, and conflating them would be a peer
answering the physics question with the parameters answer — so they travel
under separate keys and are routed to separate mailboxes.
"""

ACK: dict[str, Any] = {"ok": True}
"""What every tool returns on acceptance. The reference expects exactly this.

Worth being explicit about what it does **not** mean. It is an acknowledgement
of receipt and nothing more: it says a well-formed message reached a mailbox,
not that anybody has agreed with its contents. A peer reading its own ``ok`` as
consent would be reading its opponent's politeness as physics — which is exactly
how a series once started with two different configurations. Agreement is
decided by comparing the digest the opponent pushes at *us*.
"""

TOOL_NAMES: tuple[str, ...] = ("negotiate", "receive_turn", "submit_audit", "receive_control")
"""The complete inbound surface, exactly as the reference names it."""


@dataclass
class PeerInboxes:
    """Thread-safe mailboxes filled by the MCP tools, drained by the runtime."""

    agreements: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    """Greetings only. Digests go to :attr:`digests`; see :meth:`negotiate`."""

    digests: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    """Config digests, kept apart from greetings even though one tool carries both.

    ``negotiate`` is the protocol's single negotiation channel and it carries
    two unrelated messages: *here is where I am* and *here is the digest of the
    parameters I am playing by*. Draining both into one mailbox meant
    ``latest_agreement`` — which takes the newest item, correctly, because a
    newer greeting supersedes an older one — could hand a digest to
    ``accept_greeting``, which then failed with ``greeting must be an object,
    got NoneType``. Whether it did depended on the order two peers happened to
    call each other in.
    """
    scent_locks: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    """Pre-series scent-model offers, kept apart from greetings and digests.

    A third mailbox rather than a flag on the second, for the reason the second
    exists: ``latest_agreement`` takes the *newest* item because a newer
    greeting supersedes an older one, and every message sharing that queue
    inherits a rule written for greetings. The config gate and the scent gate
    also run one after the other, so an offer that arrived early has to survive
    untouched while the digest gate drains its own queue.
    """

    turns: "queue.Queue[TurnMessage]" = field(default_factory=queue.Queue)
    audits: "queue.Queue[AuditPayload]" = field(default_factory=queue.Queue)
    controls: "queue.Queue[ControlMessage]" = field(default_factory=queue.Queue)
    rejected: list[str] = field(default_factory=list)
    accepted_turns: dict[tuple[str, int], str] = field(default_factory=dict)
    accepted_reveals: dict[tuple[str, int, str, int], str] = field(default_factory=dict)
    hint_max_words: int = 15
    game_uid: str = ""
    sub_game: int = 0
    """``(sender, step) -> digest`` of every turn taken. The duplicate detector."""

    duplicates: list[str] = field(default_factory=list)
    """Turns dropped as re-sends. Not errors — evidence a retry behaved."""

    def _refuse(self, what: str, exc: ValueError) -> dict[str, Any]:
        """Record a refusal without raising across the wire.

        Kept rather than discarded: a match that ends in a dispute needs to
        show what arrived and why it was not acted on.
        """
        self.rejected.append(f"{what}: {exc}")
        return {"ok": False, "detail": str(exc)}

    def _reject(self, what: str, detail: str) -> dict[str, Any]:
        """Refuse something well-formed that we will not act on."""
        self.rejected.append(f"{what}: {detail}")
        return {"ok": False, "detail": detail}

    def negotiate(self, message: object) -> dict[str, Any]:
        """Receive a greeting, a config digest or a scent lock, and file it by what it is.

        Routed on content because the wire cannot distinguish them: all three
        arrive as ``negotiate``. A message carrying ``scent_lock`` is an offer,
        one carrying ``config_sha256`` is a digest; anything else is treated as
        a greeting and validated as one downstream, so a malformed message still
        fails where greetings are understood rather than being silently filed as
        something nobody reads.
        """
        try:
            body = require_mapping(message, "agreement")
            if SCENT_KEY in body:
                self.scent_locks.put(self._scent_lock(body))
            elif DIGEST_KEY in body:
                self.digests.put(self._digest(body))
            else:
                self.accepted_turns.clear()
                self.accepted_reveals.clear()
                self.agreements.put(body)
        except InvalidPayloadError as exc:
            return self._refuse("negotiate", exc)
        return ACK

    def _scent_lock(self, body: dict[str, Any]) -> dict[str, Any]:
        """A scent-model offer, checked for shape, or a refusal before it is filed.

        Shape only. Whether their model is *ours* is a question about the game
        and belongs to :func:`~..domain.lock.disputes`, which knows what our
        engine does; splitting them keeps one validator per question instead of
        two that can disagree.

        What is settled here is what would be dangerous before anybody compares
        physics: an offer that is not an object, a model that is not one, a
        digest that is not a digest, a series binding that is missing or empty,
        and an emission field too large to be about a board at all. The last
        goes through :func:`~.validation.optional_scent` — the same bound the
        turn message gets — because this payload is attacker-controlled and is
        about to be canonicalised and hashed.

        Refused at the door rather than filed, so the sender learns while it is
        still listening instead of sitting out its whole agreement window
        waiting for a reply to something we had already thrown away.
        """
        offer = require_mapping(body[SCENT_KEY], SCENT_KEY)
        model = require_mapping(offer.get("scent_model"), f"{SCENT_KEY}.scent_model")
        optional_scent(model, "emission")
        return {
            **body,
            SCENT_KEY: offer,
            SCENT_DIGEST_KEY: require_digest(body, SCENT_DIGEST_KEY),
            SERIES_KEY: require_str(body, SERIES_KEY),
        }

    def _digest(self, body: dict[str, Any]) -> dict[str, Any]:
        """A digest message, canonicalised, or a refusal before it is filed.

        Checked here rather than by the gate that reads it, because this is the
        door and the door is where validation lives. The difference is not
        cosmetic: a malformed digest refused here is answered ``{"ok": False}``
        while the sender is still listening, so they learn their message was
        never accepted. Filed and rejected later, the same message would be
        acknowledged, and the peer would sit out its whole agreement window
        waiting for a reply to something we had already thrown away.
        """
        filed = {**body, DIGEST_KEY: require_digest(body, DIGEST_KEY)}
        if SERIES_KEY in body:
            filed[SERIES_KEY] = require_str(body, SERIES_KEY)
        return filed

    def receive_turn(self, message: object) -> dict[str, Any]:
        """Receive the opponent's turn. Receiving one makes it our turn.

        **A re-sent turn is not a second turn.** The sender's retry loop
        guarantees identical bytes go out, but that guarantee is worth nothing
        on its own: a request that timed out *after* being delivered gets
        retried, and without this the same step would be enqueued twice and
        played twice. So a turn already taken for ``(sender, step)`` is
        acknowledged and dropped — acknowledged, because it genuinely did
        arrive, and refusing would only make the sender retry again.

        **The same step arriving with different content is the opposite.** That
        is not a retry; it is a move changed after the fact, the exact fraud
        Commit-Reveal exists to expose. It is refused and recorded, because
        silently keeping the first copy would hide evidence the audit needs.
        """
        try:
            turn = TurnMessage.from_dict(message)
        except InvalidPayloadError as exc:
            return self._refuse("receive_turn", exc)
        if turn.game_uid != self.game_uid or turn.sub_game != self.sub_game:
            return self._reject(
                "receive_turn",
                f"turn is bound to {turn.game_uid!r} sub-game {turn.sub_game}, expected "
                f"{self.game_uid!r} sub-game {self.sub_game}",
            )
        key, digest = (turn.sender, turn.step), fingerprint(turn)
        taken = self.accepted_turns.get(key)
        if taken == digest:
            self.duplicates.append(f"receive_turn: {turn.sender} step {turn.step} re-sent")
            return ACK
        if taken is not None:
            return self._reject(
                "receive_turn",
                f"{turn.sender} already played step {turn.step} with a different message; "
                "a retry may re-send an action, never replace one",
            )
        self.accepted_turns[key] = digest
        self.turns.put(turn)
        return ACK

    def submit_audit(self, payload: object) -> dict[str, Any]:
        """Receive the opponent's end-of-game reveal: records and nonces."""
        try:
            audit = AuditPayload.from_dict(payload)
            if audit.game_uid != self.game_uid or audit.sub_game != self.sub_game:
                return self._reject(
                    "submit_audit",
                    "audit payload is bound to "
                    f"{audit.game_uid!r} sub-game {audit.sub_game}, expected "
                    f"{self.game_uid!r} sub-game {self.sub_game}",
                )
            fresh: list[dict[str, Any]] = []
            pending: dict[tuple[str, int, str, int], str] = {}
            for record in audit.records:
                if "move" not in record:
                    fresh.append(record)
                    continue
                opened = Reveal.from_dict(record, hint_max_words=self.hint_max_words)
                if (opened.sender, opened.step) not in self.accepted_turns:
                    return self._reject(
                        "submit_audit",
                        f"{opened.sender} revealed step {opened.step} without a current "
                        "phase-one commitment",
                    )
                if opened.game_uid != self.game_uid or opened.sub_game != self.sub_game:
                    return self._reject(
                        "submit_audit",
                        f"reveal is bound to {opened.game_uid!r} sub-game {opened.sub_game}, "
                        f"expected {self.game_uid!r} sub-game {self.sub_game}",
                    )
                key = (opened.sender, opened.step, opened.game_uid, opened.sub_game)
                digest = hashlib.sha256(canonical_bytes(opened.to_dict())).hexdigest()
                taken = pending.get(key, self.accepted_reveals.get(key))
                if taken == digest:
                    self.duplicates.append(
                        f"submit_audit: {opened.sender} step {opened.step} re-sent"
                    )
                    continue
                if taken is not None:
                    return self._reject(
                        "submit_audit",
                        f"{opened.sender} already revealed step {opened.step} differently",
                    )
                pending[key] = digest
                fresh.append(record)
            self.accepted_reveals.update(pending)
            if fresh or not audit.records:
                self.audits.put(
                    AuditPayload(
                        audit.sender,
                        fresh,
                        audit.result_claim,
                        audit.game_uid,
                        audit.sub_game,
                    )
                )
        except (InvalidPayloadError, CeremonyError) as exc:
            return self._refuse("submit_audit", exc)
        return ACK

    def receive_control(self, message: object) -> dict[str, Any]:
        """Receive a control signal: enable, status, restart or quit."""
        try:
            self.controls.put(ControlMessage.from_dict(message))
        except InvalidPayloadError as exc:
            return self._refuse("receive_control", exc)
        return ACK


class ToolHost(Protocol):
    """The one method of ``FastMCP`` this module needs."""

    def tool(self, fn: Callable[..., dict[str, Any]]) -> object: ...


def register(host: ToolHost, inboxes: PeerInboxes) -> tuple[str, ...]:
    """Expose the four tools on a FastMCP host.

    The parameter names matter as much as the tool names: the reference sends
    ``{"message": ...}`` for three of them and ``{"payload": ...}`` for
    ``submit_audit``. A mismatch there fails at first contact with a real
    opponent, which is the worst moment to discover it.
    """
    host.tool(inboxes.negotiate)
    host.tool(inboxes.receive_turn)
    host.tool(inboxes.submit_audit)
    host.tool(inboxes.receive_control)
    return TOOL_NAMES
