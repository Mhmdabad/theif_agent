"""The other cohort's commitment formula, and why we can compute it.

Split out of :mod:`.crypto`, which owns the one we *send*. This is the one an
opponent may send us.

The rulebook's ``commit()`` (PDF p. 37) and the cohort's reference
implementation disagree: the book folds the nonce into the record as a field
and leaves ``ensure_ascii`` at its default, while the reference appends the
nonce after a literal pipe with ``ensure_ascii=False``. They agree on no input
at all. The book's precedence rule decides what we send; this exists so
:func:`~.crypto.verify` can also recognise a peer running the other one.

Deliberately independent of :func:`~..shared.config.canonical_bytes`. That
function is *our* canonical form and follows the book; this has to reproduce
somebody else's bytes exactly, so it spells out their flags rather than
inheriting ours and drifting the day either changes.
"""

import hashlib
import json
from typing import Any

__all__ = ["reference_commit_of"]


def reference_commit_of(payload: dict[str, Any], nonce: str) -> str:
    """The commitment the cohort's reference implementation computes.

    Not what we send. Kept so an honest opponent whose code disagrees with its
    own book is recognised as honest, rather than accused of forgery — a rule
    19 verdict is unappealable and scores zero for both sides.
    """
    canonical_text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{canonical_text}|{nonce}".encode()).hexdigest()
