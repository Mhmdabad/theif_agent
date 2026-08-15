"""Deciding which record that arrived is the one this wait is waiting for.

Two queues carry commitments, reveals and final reveals, and they do not
arrive in the order any single caller wants. Each search here looks past what
is not its answer without consuming it: a record bound to another sub-game is
quarantined, a record for a later step is held, and the wait continues on the
deadline it started with rather than on a fresh one.
"""

import time
from dataclasses import dataclass

from ..infra.ceremony import CeremonyError
from ..infra.protocol import AuditPayload, TurnMessage
from .peer_mailbox import PeerMailbox
from .peer_types import Record, Wanted


@dataclass
class PeerRecords(PeerMailbox):
    """The searches over the two inboxes, each spending one caller's patience."""

    def _submit(self, records: list[Record], result_claim: str) -> None:
        payload = AuditPayload(
            sender=self.role,
            records=records,
            result_claim=result_claim,
            game_uid=self.game_uid,
            sub_game=self.sub_game,
        )
        # Wrapped, for now. The cohort's tool takes the three fields flat, and
        # nothing is lost by that -- every record's payload already carries
        # game_uid and sub_game *inside the commitment preimage*, so the sealed
        # copy proves the binding the envelope only asserts, and
        # :func:`~..infra.audit_shape.either_shape` rebuilds the envelope from
        # it. What is not yet solved is the receiving end: sent flat, the call
        # returns 200 and the audit still never reaches the peer waiting on it.
        self.client.call("submit_audit", {"payload": payload.to_dict()})

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
            # Absent binding means the cohort's protocol; see peer_mailbox.
            if (not turn.game_uid or turn.game_uid == self.game_uid) and (
                not turn.sub_game or turn.sub_game == self.sub_game
            ):
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
