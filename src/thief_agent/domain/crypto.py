"""Commit-Reveal sealing, in the rulebook's form.

Every step a peer seals its true record under
``commit = SHA256(canonical_json({**payload, "nonce": nonce}))`` and sends
**only** the commit. Nonces are withheld until the end-of-game audit, where
both sides re-verify every step, so no position or action can be rewritten
afterwards.

**The two sources we have disagree about this formula.** :mod:`.crypto_wire`
documents that and carries the other side of it; ``verify`` accepts either.
``tests/fixtures/commit_vectors.json`` lists both digests, to be exchanged
before a counted match.
"""

import hashlib
import logging
import secrets
from typing import Any

from ..shared.config import canonical_bytes
from .crypto_record import CryptoError, board_terms, step_record
from .crypto_wire import reference_commit_of

NONCE_BYTES = 16
"""Matches the reference. ``secrets.token_hex(16)`` gives a 32-char nonce."""


logger = logging.getLogger(__name__)

__all__ = [
    "NONCE_BYTES",
    "CryptoError",
    "audit",
    "board_terms",
    "canonical",
    "commit_of",
    "reference_commit_of",
    "nonce",
    "seal",
    "step_record",
    "verify",
]


def nonce() -> str:
    """A fresh 128-bit nonce, from the CSPRNG and never from :mod:`random`.

    The rulebook names the module: ``secrets``, *not* ``random``. A nonce makes
    repeating an action produce a different digest and defeats a dictionary
    attack — the move space is five moves and a handful of cells, so without one
    an opponent cracks every commitment in microseconds.

    Both jobs need the value **unguessable**, and :mod:`random` is reproducible
    by construction: a Mersenne Twister whose future follows from its state, and
    whose state follows from enough observed output. A series hands the opponent
    hundreds of nonces at the final reveal — anything that lets them predict the
    next lets them read our move before we make it.

    Sixteen bytes because the reference uses sixteen.
    """
    return secrets.token_hex(NONCE_BYTES)


def canonical(payload: dict[str, Any]) -> str:
    """The canonical JSON text a commitment is taken over.

    Delegates rather than re-deriving. This module used to serialise with
    ``ensure_ascii=False`` while :func:`~..shared.config.canonical_bytes` left
    the default — two canonical forms in one codebase, agreeing on every
    English payload and disagreeing on the first hint with a non-ASCII
    character in it.
    """
    return canonical_bytes(payload).decode("utf-8")


def commit_of(payload: dict[str, Any], nonce: str) -> str:
    """The commitment for ``payload`` under ``nonce``, in the rulebook's form.

    ``SHA-256(canonical_json({**payload, "nonce": nonce}))`` — the nonce joins
    the record as a field and the whole object is serialised once, exactly as
    the book's ``commit()`` spells it (PDF p. 37). The cohort's reference
    implementation computes something else; see :mod:`.crypto_wire`.

    Raises:
        CryptoError: if the payload already carries a ``nonce``. Merging would
            silently drop one of the two, and the one dropped decides whether
            the commitment can ever be reopened.
    """
    if "nonce" in payload:
        raise CryptoError("payload already has a 'nonce'; pass it once, as the argument")
    return hashlib.sha256(canonical_bytes({**payload, "nonce": nonce})).hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, str]:
    """Draw a fresh nonce and commit to ``payload``.

    Returns the nonce alongside the commit. Only the commit crosses the wire at
    commit time; the nonce is withheld until the final audit, so an opponent
    cannot reverse-engineer the record while the match is still running.
    """
    fresh = nonce()
    return {"nonce": fresh, "commit": commit_of(payload, fresh)}


def verify(payload: dict[str, Any], nonce: str, commit: str) -> None:
    """Re-derive the commitment, accepting either cohort convention.

    Strict out, liberal in. We send the book's form; we accept the reference's
    too, because a peer running it is honest and refusing its commitments would
    report a clean match as tampered — a rule 19 verdict with no appeal.

    This costs nothing in security: a forger still has to invert SHA-256, and
    being offered two functions to collide with does not help. What the second
    attempt buys is the difference between "our code disagrees with yours" and
    "you cheated".

    Raises:
        CryptoError: only when *neither* convention reproduces the digest.
    """
    ours = commit_of(payload, nonce)
    if secrets.compare_digest(ours, commit):
        return
    if secrets.compare_digest(reference_commit_of(payload, nonce), commit):
        logger.info("commitment opened under the reference convention, not the book's")
        return
    raise CryptoError(f"commit mismatch: declared {commit[:16]}…, recomputed {ours[:16]}…")


def audit(records: list[dict[str, Any]]) -> None:
    """Re-verify every revealed record.

    Raises:
        CryptoError: naming the first failing step, since the match is void
            from that point and the step number is what the two teams have to
            agree on when reconciling the result.
    """
    for index, record in enumerate(records):
        try:
            verify(record["payload"], record["nonce"], record["commit"])
        except KeyError as exc:
            raise CryptoError(f"record {index} is missing {exc.args[0]!r}") from exc
        except CryptoError as exc:
            step = record.get("payload", {}).get("step", index)
            raise CryptoError(f"tampering at step {step}: {exc}") from exc
