"""The negotiation door: greetings, config digests and scent-model offers.

Split out of :mod:`.inboxes`. :class:`~.inboxes.PeerInboxes` inherits this
class, so every method below is a real, typed method of it.
"""

from typing import Any

from .inboxes_gate import InboxGate
from .inboxes_keys import ACK, DIGEST_KEY, SCENT_DIGEST_KEY, SCENT_KEY, SERIES_KEY
from .validation import (
    InvalidPayloadError,
    optional_scent,
    require_digest,
    require_mapping,
    require_str,
)


class NegotiateInbox(InboxGate):
    """:class:`~.inboxes_gate.InboxGate` plus the one negotiation channel's three bodies."""

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
