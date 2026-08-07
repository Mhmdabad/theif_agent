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

import queue
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..infra.ceremony import Acknowledgement, CeremonyError, Commitment, FinalReveal, Reveal
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import OpponentClient
from ..infra.protocol import AuditPayload, TurnMessage

Record = dict[str, Any]
Wanted = Callable[[Record], bool]


UNDECIDED = "in_progress"
"""What a mid-game reveal claims about the result: nothing yet."""


class PeerTimeout(RuntimeError):
    """Raised when the opponent did not say something in time.

    The caller converts this into a technical loss. Not retried here: the
    client's budget is the whole allowance, and a second wait on top of it
    would be a deadline nobody agreed to.
    """


@dataclass
class McpPeer:
    """The opponent, over the wire."""

    role: str
    client: OpponentClient
    inboxes: PeerInboxes
    game_uid: str
    sub_game: int
    now: str = ""
    timeout: float = 30.0
    hint_max_words: int = 15
    acks: dict[int, Acknowledgement] = field(default_factory=dict, init=False)
    result_claim: str = ""
    """What we claim the sub-game's result was. Set before the final reveal."""

    reference_acks: list[int] = field(default_factory=list, init=False)
    """Steps where their acknowledgement carried no digest. See the module docs."""

    @property
    def opponent(self) -> str:
        return "thief" if self.role == "police" else "police"

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

    # --- plumbing -----------------------------------------------------------
    def _submit(self, records: list[Record], result_claim: str) -> None:
        payload = AuditPayload(
            sender=self.role,
            records=records,
            result_claim=result_claim,
            game_uid=self.game_uid,
            sub_game=self.sub_game,
        )
        self.client.call("submit_audit", {"payload": payload.to_dict()})

    _held: list[Record] = field(default_factory=list, init=False)
    quarantined: list[Record] = field(default_factory=list, init=False)
    """Records that could not belong to this sub-game, kept rather than acted on.

    The door queues only what names our exact binding, so nothing here should
    ever arrive. *Should* is the reason it is kept: an inbox reached before it
    was bound is precisely how a forged commitment once became the head of this
    queue, and the evidence of an attempt is worth more than the silence of a
    consumer that quietly dropped it.
    """

    def _await_turn(self, step: int) -> TurnMessage:
        """The next commitment actually bound to the sub-game we are playing.

        Taking the head of the queue on trust is what let one packet that should
        never have been there cost the legitimate commitment behind it — the
        ceremony refuses the forgery, and nothing can put the real one back. A
        consumer that raised instead would lose the same sub-game by a longer
        route. So a foreign turn is set aside and the wait continues on the
        deadline it started with, which is what keeps skipping from becoming a
        second, unbudgeted wait.
        """
        deadline = time.monotonic() + self.timeout
        while True:
            turn: TurnMessage = self._drain(self.inboxes.turns, step, "commitment", deadline)
            if turn.game_uid == self.game_uid and turn.sub_game == self.sub_game:
                return turn
            self.quarantined.append(turn.to_dict())

    def _await_reveal_record(self, step: int) -> Record:
        """Return the one reveal for ``step`` after classifying every sibling."""
        deadline = time.monotonic() + self.timeout
        while True:
            current: list[Record] = []
            kept: list[Record] = []
            for record in self._held:
                record_step = record.get("step")
                if "move" not in record or not isinstance(record_step, int) or record_step > step:
                    kept.append(record)
                elif record_step < step:
                    self.quarantined.append(record)
                else:
                    current.append(record)
            self._held = kept
            if current:
                canonical = current[0]
                if any(record != canonical for record in current[1:]):
                    raise CeremonyError(f"conflicting reveals for step {step}")
                return canonical
            self._hold_payload(deadline)

    def _hold_payload(self, deadline: float) -> None:
        """Take one audit payload, holding what is ours and quarantining what is not.

        Both bindings are checked, and a failure of either sets the record aside
        rather than ending the wait. The envelope can only be foreign if it
        reached a mailbox that was not yet bound; a record can only be foreign
        if the sender wrapped an old reveal in a current envelope, which is the
        replay the inner binding exists to catch. Neither is a reason to stop
        waiting for the reveal that *is* ours.
        """
        payload = self._drain(self.inboxes.audits, None, "audit record", deadline)
        ours = payload.game_uid == self.game_uid and payload.sub_game == self.sub_game
        for entry in payload.records:
            record = dict(entry)
            if ours and not self._foreign(record):
                self._held.append(record)
            else:
                self.quarantined.append(record)

    def _foreign(self, record: Record) -> bool:
        """Whether a record names a binding that is not the one we are playing.

        A record that names none — a final reveal carries nonces and no
        sub-game — is bound by the envelope it travelled in, which has already
        been checked, so it is ours by default rather than foreign by omission.
        """
        return bool(
            record.get("game_uid", self.game_uid) != self.game_uid
            or record.get("sub_game", self.sub_game) != self.sub_game
        )

    def _await_record(self, wanted: Wanted) -> Record:
        """Find a record we are waiting for, keeping the ones we are not.

        Reveals and final reveals share one queue, and they do not arrive in
        the order any single caller wants — a final reveal can land while a
        step's reveal is still outstanding. Records that do not match are held
        rather than dropped, because a discarded message is a deadlock nobody
        can diagnose.
        """
        for kept in list(self._held):
            if wanted(kept):
                self._held.remove(kept)
                return kept
        deadline = time.monotonic() + self.timeout
        while True:
            self._hold_payload(deadline)
            for kept in list(self._held):
                if wanted(kept):
                    self._held.remove(kept)
                    return kept

    def _drain(
        self,
        inbox: "queue.Queue[Any]",
        step: int | None,
        what: str,
        deadline: float | None = None,
    ) -> Any:  # noqa: ANN401
        """Take the next message off an inbox, or say who stopped talking.

        Returns whatever that inbox holds — a ``TurnMessage`` or an
        ``AuditPayload``. Typed loosely because the queues are, and narrowing
        it here would mean two near-identical copies of the timeout message.

        ``deadline`` is what a caller that may have to take several messages
        waits against, so setting a foreign one aside costs no extra patience:
        the whole search shares the one allowance the caller was given.
        """
        remaining = self.timeout if deadline is None else max(deadline - time.monotonic(), 0.0)
        try:
            return inbox.get(timeout=remaining)
        except queue.Empty as exc:
            where = "" if step is None else f" for step {step}"
            raise PeerTimeout(
                f"waited {self.timeout:g}s for the {self.opponent}'s {what}{where} and it "
                "never came; a peer that stops answering is a technical loss, which "
                "scores zero for both sides"
            ) from exc
