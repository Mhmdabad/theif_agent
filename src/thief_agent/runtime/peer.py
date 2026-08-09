"""Carrying four ceremony phases over four MCP tools that are not the same four.

:mod:`.subgame` decides what must be said and in what order. This is how it
crosses the wire, and the mapping is the decision worth reading:

============  ==========================================================
Phase         How it travels
============  ==========================================================
Commit        ``receive_turn``, carrying the digest in a ``TurnMessage``.
Acknowledge   **the response to that call.** Not a message of its own.
Reveal        ``submit_audit``, one record, no nonce.
Final Reveal  ``submit_audit``, the nonces, once, at the end.
============  ==========================================================

**Acknowledge is the response, and that is the point.** The four tools are
fixed by the protocol we share with every other team, and inventing a fifth
would fail against all of them at first contact. ``receive_turn`` already
answers, and an acknowledgement *is* an answer: "I hold your commitment". So the
phase costs no new message and no interop risk. What it does cost is honesty
about a limit — the reference implementation returns a bare ``{"ok": true}``,
which carries no digest, so against a reference opponent we can confirm delivery
but not *which* commitment they hold. Against another agent running this code
the digest is there. The difference is recorded rather than papered over.

**Reveal and Final Reveal share ``submit_audit``** because it is the only tool
whose payload is a list of records, and they are told apart by shape: a reveal
has a ``move``, a final reveal has ``nonces``. Splitting them across tools would
have meant putting a reveal in ``receive_control``, whose four kinds are fixed.

``AuditPayload`` requires a **non-empty** ``result_claim``, which is a sensible
demand of an end-of-game message and an awkward one for a mid-game reveal: at
step two nobody is claiming anything. Sending :data:`UNDECIDED` rather than
relaxing the schema keeps the wire contract we share with every other team, and
says something true — the sub-game is still running. Left empty, the opponent
refuses the message, nothing is enqueued, and both sides wait for each other
until their deadlines expire. That is not a hypothetical; it is what happened
the first time this ran.

**Receiving is draining an inbox, not calling anything.** The opponent pushes to
our server; :class:`~..infra.inboxes.PeerInboxes` queues it; this waits with a
deadline. A wait that ran out is not an error here — it is handed upward as one,
because a peer that stopped answering is a technical loss and that judgement
belongs where the match is scored.
"""

from dataclasses import dataclass

from ..infra.ceremony import Acknowledgement, Commitment, FinalReveal, Reveal
from ..infra.protocol import TurnMessage
from .peer_records import PeerRecords
from .peer_types import UNDECIDED, PeerTimeout, Record, Wanted

__all__ = ["UNDECIDED", "McpPeer", "PeerTimeout", "Record", "Wanted"]


@dataclass
class McpPeer(PeerRecords):
    """The opponent, over the wire."""

    # --- phase 1: commit ----------------------------------------------------
    def send_commit(self, commitment: Commitment) -> None:
        """Send our digest, and keep whatever came back as their acknowledgement."""
        turn = TurnMessage(
            step=commitment.step,
            sender=self.role,
            hint="",
            smell_grid={},
            commit=commitment.commit,
            timestamp=commitment.timestamp,
            game_uid=commitment.game_uid,
            sub_game=commitment.sub_game,
        )
        answer = self.client.call("receive_turn", {"message": turn.to_dict()})
        self.acks[commitment.step] = self._read_ack(commitment, answer)

    def _read_ack(self, ours: Commitment, answer: Record) -> Acknowledgement:
        """Their reply, as an acknowledgement of the digest we just sent.

        A reference opponent answers ``{"ok": true}`` with no digest. Rather
        than refuse to play against one, the digest we sent is used — we know
        what they received, because we sent it — and the step is recorded in
        :attr:`reference_acks` so the difference is visible instead of assumed.
        """
        acknowledges = answer.get("acknowledges")
        if not isinstance(acknowledges, str):
            self.reference_acks.append(ours.step)
            acknowledges = ours.commit
        return Acknowledgement(
            step=ours.step,
            sender=self.opponent,
            acknowledges=acknowledges,
            timestamp=self.now,
        )

    def await_commit(self, step: int) -> Commitment:
        turn = self._await_turn(step)
        return Commitment(
            step=turn.step,
            sender=turn.sender,
            commit=turn.commit,
            timestamp=turn.timestamp,
            game_uid=turn.game_uid,
            sub_game=turn.sub_game,
        )

    # --- phase 2: acknowledge -----------------------------------------------
    def send_ack(self, ack: Acknowledgement) -> None:
        """Nothing crosses the wire: our answer to *their* commit carried it."""

    def await_ack(self, step: int) -> Acknowledgement:
        ack = self.acks.get(step)
        if ack is None:
            raise PeerTimeout(
                f"no acknowledgement for step {step}; the {self.opponent} never answered "
                "our commitment, so nothing has locked and the reveal must not go out"
            )
        return ack

    # --- phase 3: reveal ----------------------------------------------------
    def send_reveal(self, opened: Reveal) -> None:
        self._submit([opened.to_dict()], UNDECIDED)

    def await_reveal(self, step: int) -> Reveal:
        """The reveal for ``step``, which is bound to this sub-game by construction.

        The binding is enforced where a record that fails it can be *set aside*
        — :meth:`_hold_payload` — rather than here, where the only thing left to
        do with one is raise. Those are not the same outcome: a foreign record
        that ends the wait costs the sub-game just as surely as one that gets
        played, and it is the legitimate reveal queued behind it that pays.
        """
        return Reveal.from_dict(
            self._await_reveal_record(step),
            hint_max_words=self.hint_max_words,
        )

    # --- phase 4: final reveal ----------------------------------------------
    def send_final(self, disclosed: FinalReveal) -> None:
        self._submit([disclosed.to_dict()], self.result_claim or UNDECIDED)

    def await_final(self) -> FinalReveal:
        return FinalReveal.from_dict(self._await_record(lambda r: "nonces" in r))
