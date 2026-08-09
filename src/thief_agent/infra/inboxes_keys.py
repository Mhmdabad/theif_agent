"""Wire constants for the mailboxes, and the digest that identifies a turn.

Split out of :mod:`.inboxes`, which re-exports every name below; importers
should keep reading them from there.
"""

import hashlib
from typing import Any

from ..shared.config import canonical_bytes
from .protocol import TurnMessage


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

RESULT_KEY = "result_claim"
"""What makes a negotiation message a final-result claim.

Appendix E rule 35: both sides agree the result before either reports one. A
fourth body on the one negotiation channel, routed on content exactly as the
digest and the lock are, and for the same reason — the wire cannot distinguish
them, because greeting, digest, lock and claim all arrive as ``negotiate``.

It travels here rather than as a control signal because ``receive_control``
carries the reference's four fixed kinds, and inventing a fifth would be a
message a reference opponent parses as malformed. A negotiation body it does
not recognise is one it acknowledges and ignores, which is the failure we want:
no agreement recorded, rather than a match lost at the final gate.
"""

RESULT_DIGEST_KEY = "result_sha256"
"""The digest of the offered claim. Named apart from the other two digests.

Three digests over three different agreements — parameters, physics, outcome —
and conflating any two would be a peer answering one question with another
question's answer, so each travels under its own key into its own mailbox.
"""

RETRY_KEY = "retry"
"""Marks a refusal the sender should repeat rather than one it must accept.

``{"ok": false}`` on its own says *no*, and a fire-and-forget sender reads that
as *never*. But a door that is merely **not open yet** — a mailbox bound to no
sub-game, or to one before the sub-game the message names — has said nothing
about the message itself, and a series lost to that is the race this key ends.
Those two cases answer ``ok: false`` *and* this flag, and
:class:`~.mcp_client.OpponentClient` re-sends inside the Appendix F budget it
already spends on a socket that will not answer.

The alternative was to acknowledge what we could not yet judge, and that is what
had to be undone: an unbound mailbox queued any canonically shaped packet and
wrote its duplicate ledger from it, so a commitment forged before the runner
bound its inboxes became the head of the queue the ceremony drains and the
legitimate opening commitment behind it was never reached.

An opponent that ignores the flag is no worse off than it was: it reads a plain
refusal, exactly as it would have read one for a stale packet.
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
