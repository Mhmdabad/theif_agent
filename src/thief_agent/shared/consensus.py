"""The settlement consensus signature — the release's *second* canonical form.

Every other digest in this system goes through
:func:`~.config.canonical_bytes`: sorted keys, no whitespace, native UTF-8. This
one does not. It sorts keys and keeps UTF-8 native, but uses ``json.dumps``'
**default separators** — ``", "`` and ``": "``, with the spaces — because that
is what the reference's report writer emits and therefore what every other team
recomputes when it checks our report.

A second canonical form in one codebase is normally the defect
:func:`~.config.canonical_bytes` warns about. It is carried deliberately here,
named and isolated in its own module, because the alternative is worse: a
signature only we can reproduce proves nothing to the reader it exists for.

**Sign-then-insert.** The signature is computed over the report *without* the
signature key, then the key is added. A field cannot be inside its own preimage,
so a verifier reverses it exactly: pop the key, re-serialise spaced, re-hash.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

__all__ = ["CONSENSUS_KEY", "consensus_signature", "sign_consensus", "verify_consensus"]

CONSENSUS_KEY = "חתימת_קונסנזוס_משותפת"
"""Where the signature is written. Hebrew, as the cohort's kit defines it.

The name is data, not decoration: a verifier pops *this* key and no other, so a
translated or transliterated spelling is a different field and verifies nothing.
"""


def consensus_signature(report: Mapping[str, Any]) -> str:
    """SHA-256 over the report in the spaced canonical form, key excluded."""
    body = {k: v for k, v in report.items() if k != CONSENSUS_KEY}
    spaced = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(spaced.encode("utf-8")).hexdigest()


def sign_consensus(report: Mapping[str, Any]) -> dict[str, Any]:
    """The report with its consensus signature inserted."""
    return {**report, CONSENSUS_KEY: consensus_signature(report)}


def verify_consensus(signed: Mapping[str, Any]) -> bool:
    """Whether a signed report reproduces its own signature.

    False for a report carrying no signature at all: absence is not a passing
    verification, and treating it as one would let an unsigned document through
    the check that exists to catch exactly that.
    """
    claimed = signed.get(CONSENSUS_KEY)
    return isinstance(claimed, str) and claimed == consensus_signature(signed)
