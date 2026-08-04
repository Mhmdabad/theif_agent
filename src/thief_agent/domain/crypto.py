"""Commit-Reveal sealing, in the wire form the cohort uses.

Every step a peer seals its true record under
``commit = SHA256(canonical_json(payload) | nonce)`` and sends **only** the
commit. Nonces are withheld until the end-of-game audit, where both sides
re-verify every step — so no position or action can be rewritten afterwards.

**This formula is not ours to choose.** It has to match the opponent's byte for
byte, or two peers who both played honestly produce a ``TAMPERED`` verdict on a
clean match — voided, no appeal, zero for both sides. The shape here follows the
course reference implementation, which is the only thing resembling a shared
standard across the cohort.

Three details carry that compatibility, and each is easy to get silently wrong:

``ensure_ascii=False``
    ``json.dumps`` defaults to ``True``, escaping non-ASCII to ``\\uXXXX``.
    Identical bytes for an English hint, different bytes the moment a hint
    carries a non-ASCII character — and hints are free natural language.

The nonce is **appended after a pipe**, not folded into the payload
    ``SHA256(canonical | "|" | nonce)``. Putting it inside the object changes
    both the canonical string and the digest.

``sort_keys=True`` with tight separators
    So key order and incidental whitespace cannot change the digest.
"""

import hashlib
import secrets
from typing import Any

from ..shared.config import canonical_bytes

NONCE_BYTES = 16
"""Matches the reference. ``secrets.token_hex(16)`` gives a 32-char nonce."""


class CryptoError(ValueError):
    """Raised when a revealed record does not match its commitment."""


def nonce() -> str:
    """A fresh 128-bit nonce, from the CSPRNG and never from :mod:`random`.

    The rulebook names the module: ``secrets``, *not* ``random``, which it
    calls too predictable. That is not stylistic advice.

    A nonce does two jobs. It makes repeating an action produce a different
    digest, and it defeats a dictionary attack — the move space is tiny, five
    moves and a handful of barrier cells, so without a nonce an opponent hashes
    every possibility and cracks each commitment in microseconds.

    Both jobs need the value to be **unguessable**, and :mod:`random` is
    reproducible by construction: it is a Mersenne Twister whose entire future
    follows from its state, and the state follows from enough observed output.
    A series hands the opponent hundreds of nonces at the final reveal. Anything
    that lets them predict the next one lets them pre-image our commitments and
    read our move before we make it — which is the whole thing this mechanism
    exists to prevent.

    Sixteen bytes because the reference uses sixteen. Collision resistance is
    not the point at this size — unpredictability is — but a shared length is
    one less thing for two implementations to disagree about.
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
    """The commitment for ``payload`` under ``nonce``."""
    return hashlib.sha256(f"{canonical(payload)}|{nonce}".encode()).hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, str]:
    """Draw a fresh nonce and commit to ``payload``.

    Returns the nonce alongside the commit. Only the commit crosses the wire at
    commit time; the nonce is withheld until the final audit, so an opponent
    cannot reverse-engineer the record while the match is still running.
    """
    fresh = nonce()
    return {"nonce": fresh, "commit": commit_of(payload, fresh)}


def verify(payload: dict[str, Any], nonce: str, commit: str) -> None:
    """Re-derive the commitment and compare.

    Raises:
        CryptoError: on any mismatch. There is no near-miss — SHA-256 is
            sensitive to every bit, so a difference is proof of tampering and
            costs the responsible team the match.
    """
    actual = commit_of(payload, nonce)
    if not secrets.compare_digest(actual, commit):
        raise CryptoError(f"commit mismatch: declared {commit[:16]}…, recomputed {actual[:16]}…")


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
