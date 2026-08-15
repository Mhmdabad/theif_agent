"""Filing a verified reference-v3 offer as an agreement of our own shape.

Split from :mod:`.pairing_v3` for the line budget, and because it is the seam
rather than the rule: that module decides whether an offer is trustworthy, this
one decides what the rest of the code gets to see of it -- an ordinary
agreement, with the dialect left behind at this boundary.
"""

from typing import Any

from .pairing_v3 import Inbox, PairingError, check_pairing

__all__ = ["pairing_agreement"]


def pairing_agreement(
    inbox: Inbox,
    terms: dict[str, Any],
    nonce: str,
    signature: str,
    role: str,
    sub_game: int,
    identity: dict[str, Any],
) -> dict[str, Any]:
    """Verify a reference-v3 offer and file it as an ordinary agreement.

    Filed in our own shape once it verifies, so everything downstream sees what
    it already understands: the dialect stops at this function rather than
    spreading into the gate that reads agreements.

    **The protocol version is theirs, not a label for the dialect they used.**
    Writing ``reference-v3`` here because the call arrived flat made our own
    gate refuse the peer -- it compares the version against ours and the two
    could never match. What the version answers is *can these two play*, and a
    peer that does not say gets an empty string, which the gate reads as
    unstated rather than as agreement.
    """
    try:
        check_pairing(terms, nonce, signature, role, inbox.parameters)
    except PairingError as exc:
        return {"ok": False, "error": str(exc)}
    inbox.agreements.put(
        {
            "greeting": {
                "role": role,
                "group_id": str(identity.get("group_id", "")),
                "public_url": str(identity.get("mcp_url", identity.get("public_url", ""))),
                "protocol_version": str(identity.get("protocol_version", "")),
            },
            "sub_game_number": sub_game,
        }
    )
    return {"ok": True}
