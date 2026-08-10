"""Commit-Reveal sealing, in the cohort's wire form.

Every step a peer seals its true record under
``commit = SHA-256(canonical_json(payload) + "|" + nonce)`` — the course
reference implementation's exact construction — and sends **only** the
commit. Nonces are withheld until the end-of-game audit, where both sides
re-verify every step, so no position or action can be rewritten afterwards.

The rulebook's p. 37 listing seals differently (nonce folded into the
record). :mod:`.crypto_wire` carries that form and the history of the choice;
``verify`` accepts either. ``tests/fixtures/commit_vectors.json`` lists both
digests per record, to be exchanged before a counted match.
"""

import hashlib
import json
import logging
import secrets
from typing import Any

from ..shared.config import canonical_bytes
from .crypto_record import CryptoError, board_terms, step_record
from .crypto_wire import book_commit_of

NONCE_BYTES = 16
"""Matches the reference. ``secrets.token_hex(16)`` gives a 32-char nonce."""


logger = logging.getLogger(__name__)

__all__ = [
    "NONCE_BYTES",
    "CryptoError",
    "audit",
    "board_terms",
    "book_commit_of",
    "canonical",
    "commit_of",
    "nonce",
    "seal",
    "step_record",
    "verify",
]


def nonce() -> str:
    """A fresh 128-bit nonce, from the CSPRNG and never from :mod:`random`.

    The rulebook names the module: ``secrets``, *not* ``random``. A nonce makes
    repeating an action produce a different digest and defeats a dictionary
    attack over the tiny move space. It must be **unguessable**, and
    :mod:`random` is a Mersenne Twister — reproducible from enough observed
    output, and the final reveal hands the opponent hundreds of draws.
    Sixteen bytes because the reference uses sixteen.
    """
    return secrets.token_hex(NONCE_BYTES)


def canonical(payload: dict[str, Any]) -> str:
    """Our own canonical JSON text — the config digest, the locks, the logs.

    Delegates to :func:`~..shared.config.canonical_bytes` rather than
    re-deriving, so everything *we* alone hash goes through one form. Step
    commitments are the deliberate exception: they are shared with the
    opponent, so :func:`commit_of` reproduces the reference implementation's
    serialisation — ``ensure_ascii=False``, where this form escapes — flag for
    flag instead of inheriting ours.
    """
    return canonical_bytes(payload).decode("utf-8")


def commit_of(payload: dict[str, Any], nonce: str) -> str:
    """The commitment for ``payload`` under ``nonce``, as the cohort computes it.

    ``SHA-256(json + "|" + nonce)`` over the reference implementation's exact
    serialisation: ``sort_keys=True``, ``ensure_ascii=False``, compact
    separators. Spelled out here rather than through :func:`canonical` because
    the first Hebrew hint would expose the difference between the two.

    Total over dicts on purpose — no guard, exactly like the reference —
    because :func:`verify` recomputes *opponents'* payloads through here, and
    refusing a shape their sealer accepted would turn a parse quirk into a
    tampering verdict. Our own sealing is guarded at :func:`seal`.
    """
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{text}|{nonce}".encode()).hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, str]:
    """Draw a fresh nonce and commit to ``payload``.

    Returns the nonce alongside the commit. Only the commit crosses the wire at
    commit time; the nonce is withheld until the final audit, so an opponent
    cannot reverse-engineer the record while the match is still running.

    Raises:
        CryptoError: if the payload already carries a ``nonce`` — sealing
            draws its own, so better refused than silently double-nonced.
    """
    if "nonce" in payload:
        raise CryptoError("payload already has a 'nonce'; sealing draws its own")
    fresh = nonce()
    return {"nonce": fresh, "commit": commit_of(payload, fresh)}


def verify(payload: dict[str, Any], nonce: str, commit: str) -> None:
    """Re-derive the commitment, accepting either cohort convention.

    Strict out, liberal in. We send the reference implementation's form — the
    one an auditor derived from the cohort's code recomputes — and accept the
    book's p. 37 form too, because a peer that implemented the book literally
    is honest, and refusing its commitments would report a clean match as
    tampered: a rule 19 verdict with no appeal.

    This costs nothing in security: a forger still has to invert SHA-256, and
    being offered two functions to collide with does not help.

    Raises:
        CryptoError: only when *neither* convention reproduces the digest.
    """
    ours = commit_of(payload, nonce)
    if secrets.compare_digest(ours, commit):
        return
    try:
        book = book_commit_of(payload, nonce)
    except CryptoError:  # a payload carrying "nonce" has no book form at all
        book = ""
    if book and secrets.compare_digest(book, commit):
        logger.info("commitment opened under the book's convention, not the wire's")
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
