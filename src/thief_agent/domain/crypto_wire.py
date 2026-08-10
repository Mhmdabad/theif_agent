"""The rulebook's commitment formula, and why it is no longer the one we send.

Split out of :mod:`.crypto`, which owns the form on the wire — the cohort
reference implementation's, ``SHA-256(json + "|" + nonce)`` with
``ensure_ascii=False``. This module carries the book's p. 37 ``commit()``:
the nonce folded into the record as a field, serialised once, non-ASCII
escaped. The two agree on no input at all.

We used to send the book's form, on the book's own precedence rule. Two facts
reversed that. The reference's auditor recomputes **only** its own form, so a
reference-derived opponent auditing book-form records fails every step and
reports a clean match as tampered — a rule 19 verdict, unappealable, zero for
both sides — and the asymmetry ran one way: our ``verify`` accepted them,
theirs would never accept us. And the book's p. 37 listing itself concedes the
operational record to the reference — *"the reference code seals a richer
record … the core is shown"* — the same settlement the contradiction table
reaches for the agreement keys: the opponent's parser owns the wire.

Deliberately built on :func:`~..shared.config.canonical_bytes`: that function
is the book-faithful serialisation this formula calls for, and the pairing is
pinned by ``test_crypto``'s canonical-form tests.
"""

import hashlib
from typing import Any

from ..shared.config import canonical_bytes
from .crypto_record import CryptoError

__all__ = ["book_commit_of"]


def book_commit_of(payload: dict[str, Any], nonce: str) -> str:
    """The commitment the rulebook's p. 37 ``commit()`` computes.

    Not what we send. Kept so an honest opponent who implemented the book
    literally is recognised as honest, rather than accused of forgery.

    Raises:
        CryptoError: if the payload already carries a ``nonce``. This form
            merges the nonce into the record, and merging would silently drop
            one of the two values — the one dropped decides whether the
            commitment can ever be reopened.
    """
    if "nonce" in payload:
        raise CryptoError("payload already has a 'nonce'; pass it once, as the argument")
    return hashlib.sha256(canonical_bytes({**payload, "nonce": nonce})).hexdigest()
