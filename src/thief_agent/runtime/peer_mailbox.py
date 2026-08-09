"""What the peer holds, and the single wait that gives up on it.

Every piece of mutable state lives here — the client, the two mailboxes, the
deadline, and the two sidings for records that are not ours — because the
phases in :mod:`.peer` read it off ``self`` at the moment they need it. A
caller that re-points an inbox or shortens the timeout after construction is
therefore still obeyed; nothing is captured into a helper at build time.
"""

import queue
import time
from dataclasses import dataclass, field
from typing import Any

from ..infra.ceremony import Acknowledgement
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import OpponentClient
from .peer_types import PeerTimeout, Record


@dataclass
class PeerMailbox:
    """The opponent's state, and the one wait that can run out on it."""

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

    _held: list[Record] = field(default_factory=list, init=False)
    quarantined: list[Record] = field(default_factory=list, init=False)
    """Records that could not belong to this sub-game, kept rather than acted on.

    The door queues only what names our exact binding, so nothing here should
    ever arrive. *Should* is the reason it is kept: an inbox reached before it
    was bound is precisely how a forged commitment once became the head of this
    queue, and the evidence of an attempt is worth more than the silence of a
    consumer that quietly dropped it.
    """

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
