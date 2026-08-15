"""The reference-v3 pre-game gate: flat terms, a signature, and an identity.

The cohort's ``negotiate`` takes six flat arguments where ours takes one routed
message. This module is the translation, and it lives apart from
:mod:`.inboxes_negotiate` because it is a *dialect*, not a new rule: the same
question -- do we agree on the terms, and is the peer who they say -- asked in
the shape another implementation asks it.

**The signature is the §3 construction, and the separator matters.**
``SHA256(canonical_json(terms) + "|" + nonce)``, a single ``|``. The kit spells
this out because all three plausible readings -- bare concatenation, one pipe,
two -- look equally right in prose, only one reproduces the vector, and the
wrong ones fail *every* handshake with nothing to go on but "signature
mismatch". Worse, they are invisible to self-testing: sign and verify with the
same wrong separator and every local test passes. :func:`~..domain.crypto.commit_of`
is already that construction and already passes their vector, so it is used
rather than re-derived here.

**Terms are compared by value, never by digest.** Two peers can hold the same
fourteen agreed values in configs that differ elsewhere -- comments, a ``world``
block, a schema version -- and a digest over the whole file would refuse a match
both sides actually agree on. The kit's terms are the fourteen; so is
:func:`~..shared.terms.to_terms`.
"""

import queue
from typing import Any, Protocol

from ..domain.crypto import commit_of
from ..shared.terms import to_terms

__all__ = [
    "Inbox",
    "PairingError",
    "REFUSALS",
    "check_pairing",
    "pairing_agreement",
    "pairing_call",
    "sign_terms",
]


class Inbox(Protocol):
    """The two things this dialect needs of an inbox, and nothing more.

    Narrow on purpose: a structural type keeps the gate free of an import back
    into the module that calls it, and says in one place exactly how much of the
    inbox a handshake is allowed to touch.
    """

    parameters: dict[str, Any]
    agreements: "queue.Queue[dict[str, Any]]"


class PairingError(Exception):
    """A reference-v3 handshake that must not proceed, and why."""


REFUSALS = {
    "signature": (
        "signature does not verify over the terms you sent with the nonce you sent; "
        "expected SHA256(canonical_json(terms) + '|' + nonce), a SINGLE pipe"
    ),
    "terms": "terms differ from ours by value",
    "role": "role must be 'police' or 'thief'",
}
"""Named refusals. The kit asks implementations to name the *construction* in a
signature refusal rather than only refusing, because "signature mismatch" alone
sends both teams diffing fourteen values that already agree."""


def sign_terms(terms: dict[str, Any], nonce: str) -> str:
    """Our signature over the agreed terms, in the cohort's construction."""
    return commit_of(terms, nonce)


def pairing_call(
    parameters: dict[str, Any], nonce: str, role: str, sub_game: int, identity: dict[str, Any]
) -> dict[str, Any]:
    """The arguments a reference-v3 ``negotiate`` expects, flat.

    ``sub_game_number`` and ``role`` ride *beside* the terms, never inside them:
    the terms are a flat signed set, and adding a key to them changes the
    signature every other peer computes.
    """
    terms = to_terms(parameters)
    return {
        "terms": terms,
        "nonce": nonce,
        "signature": sign_terms(terms, nonce),
        "role": role,
        "sub_game_number": sub_game,
        "identity": identity,
    }


def check_pairing(
    theirs: dict[str, Any], nonce: str, signature: str, role: str, ours: dict[str, Any]
) -> None:
    """Refuse a handshake that cannot be trusted, naming which check failed.

    Raises:
        PairingError: on a role that is not a role, terms that differ from ours
            by value, or a signature that does not verify. Checked in that
            order: the cheapest question first, and the one whose failure is
            least ambiguous.
    """
    if role not in ("police", "thief"):
        raise PairingError(f"{REFUSALS['role']}, got {role!r}")
    if theirs != to_terms(ours):
        differing = sorted(
            k for k in set(theirs) | set(to_terms(ours)) if theirs.get(k) != to_terms(ours).get(k)
        )
        raise PairingError(f"{REFUSALS['terms']}: {differing}")
    if sign_terms(theirs, nonce) != signature:
        raise PairingError(REFUSALS["signature"])


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
                "protocol_version": "reference-v3",
            },
            "sub_game_number": sub_game,
        }
    )
    return {"ok": True}
