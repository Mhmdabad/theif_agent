"""The turn, audit and control doors.

Split out of :mod:`.inboxes`, whose :class:`~.inboxes.PeerInboxes` inherits
this class -- so every method below is a real, typed method of it.
"""

import hashlib
from typing import Any

from ..shared.config import canonical_bytes
from .audit_shape import either_shape
from .ceremony import CeremonyError, Reveal
from .inboxes_keys import ACK, fingerprint
from .inboxes_negotiate import NegotiateInbox
from .protocol import AuditPayload, ControlMessage, TurnMessage
from .validation import InvalidPayloadError


class TurnInbox(NegotiateInbox):
    """:class:`~.inboxes_negotiate.NegotiateInbox` plus the three message-carrying tools."""

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
        closed = self._closed("turn", turn.game_uid, turn.sub_game)
        if closed is not None:
            return self._shut("receive_turn", closed)
        key = (
            turn.sender,
            turn.step,
            turn.game_uid or self.game_uid,
            turn.sub_game or self.sub_game,
        )
        digest = fingerprint(turn)
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

    def submit_audit(
        self,
        payload: object = None,
        sender: str = "",
        records: list[dict[str, Any]] | None = None,
        result_claim: str = "",
    ) -> dict[str, Any]:
        """Receive the opponent's end-of-game reveal: records and nonces.

        Flat or wrapped; see :func:`~.audit_shape.either_shape`. Two bindings
        are compared: the envelope goes through :meth:`_closed`, so nothing
        opens against a series or sub-game that is not ours, and each record is
        checked against *the envelope it arrived in* rather than our position
        again -- the sender wrote both, so a reveal re-wrapped in a fresher
        audit to replay an earlier sub-game is exactly what that exposes.
        """
        payload = either_shape(payload, sender, records, result_claim)
        try:
            audit = AuditPayload.from_dict(payload)
            closed = self._closed("audit payload", audit.game_uid, audit.sub_game)
            if closed is not None:
                return self._shut("submit_audit", closed)
            fresh: list[dict[str, Any]] = []
            pending: dict[tuple[str, int, str, int], str] = {}
            for record in audit.records:
                if "move" not in record:
                    fresh.append(record)
                    continue
                opened = Reveal.from_dict(record, hint_max_words=self.hint_max_words)
                if opened.game_uid != audit.game_uid or opened.sub_game != audit.sub_game:
                    return self._reject(
                        "submit_audit",
                        f"reveal is bound to {opened.game_uid!r} sub-game {opened.sub_game} "
                        f"but travelled in an audit for {audit.game_uid!r} sub-game "
                        f"{audit.sub_game}",
                    )
                key = (
                    opened.sender,
                    opened.step,
                    opened.game_uid or self.game_uid,
                    opened.sub_game or self.sub_game,
                )
                if key not in self.accepted_turns:
                    return self._reject(
                        "submit_audit",
                        f"{opened.sender} revealed step {opened.step} of {opened.game_uid!r} "
                        f"sub-game {opened.sub_game} without a current phase-one commitment",
                    )
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
