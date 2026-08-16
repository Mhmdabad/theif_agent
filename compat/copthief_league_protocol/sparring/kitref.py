"""The one seam between this peer and the kit's pinned constructions.

Every hash this peer computes comes from ``verify_vectors.py`` — the same reference functions the
fixtures under ``vectors/`` are generated from and checked against. That is deliberate, and it is
the reason the peer's bytes cannot drift from the kit's:

* ``hashlib`` is imported nowhere else under ``sparring/`` (``guards/purity.py`` enforces it), so
  the peer physically cannot hand-roll a commit;
* if the peer and the kit ever disagree, the fixtures fail first, in CI, with no game at stake.

The honest limit of that arrangement: a bug *inside* ``verify_vectors.py`` is invisible from here.
This peer is a third independent implementation of the **game layer**, not of the crypto.

Four functions are deliberately NOT re-exported, and their absence is checked:

* ``ref_report_consensus_signature`` — it exists only to sign an emailed settlement report, and
  this peer has no mail and owes no report. Not importing it is that rule expressed in code.
* ``ref_share_commit``, ``ref_joint_seed``, ``ref_derive_starts`` — opt-in enhancements
  (SPEC Appendix A). No sparring run has signed them, so the peer must not quietly use them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MISSING = (
    "the sparring peer must run from inside the interop kit — it deliberately does not vendor "
    "the crypto (SPEC §1), it imports the kit's own reference constructions so its bytes cannot "
    "drift from the published vectors.\n"
    "  Run it as:  python -m sparring.cli ...   from the repository root,\n"
    "  or set COPTHIEF_KIT_ROOT to the directory holding verify_vectors.py."
)


def _kit_root() -> Path:
    override = os.environ.get("COPTHIEF_KIT_ROOT")
    return Path(override) if override else Path(__file__).resolve().parent.parent


_ROOT = _kit_root()
if not (_ROOT / "verify_vectors.py").is_file():
    raise ImportError(f"{_MISSING}\n  looked in: {_ROOT}")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import verify_vectors as _kit  # noqa: E402  (path is set immediately above, by design)

KIT_ROOT = _ROOT

# --- the pinned constructions, under peer-local names --------------------------------------

canonical_str = _kit._canonical_str          # SPEC §2
canonical_bytes = _kit.canonical_bytes
canonical_hash = _kit.canonical_hash
commit = _kit.ref_commit                     # SPEC §3  SHA256(canonical(payload)|nonce)
terms_signature = _kit.ref_terms_signature   # SPEC §4
game_uid = _kit.ref_game_uid                 # SPEC §4
game_id = _kit.ref_game_id                   # SPEC §4  sorted, never self-first
smell_emit = _kit.ref_smell_emit             # SPEC §5  subtractive_chebyshev_v1
smell_decay = _kit.ref_smell_decay
book_full_turn = _kit.ref_book_full_turn     # SPEC §5.1 multiplicative_book_v1
BOOK_KERNEL = _kit.BOOK_KERNEL
lock_doc = _kit.ref_lock_doc                 # SPEC §7
lock_hash = _kit.ref_lock_hash
lock_decision = _kit.ref_lock_decision
pairing_decision = _kit.ref_pairing_decision      # SPEC §7.2
uid_declaration_decision = _kit.ref_uid_declaration_decision  # SPEC §7.3
delivery_decision = _kit.ref_delivery_decision    # SPEC §7.1
deadline_decision = _kit.ref_deadline_decision
LOCK_FAMILIES = _kit.LOCK_FAMILIES
LOCK_DOC_KEYS = _kit.LOCK_DOC_KEYS

# Names this peer must never reach for. `guards/purity.py` asserts they appear nowhere under
# sparring/, so the rule is checked rather than remembered.
WITHHELD = (
    "ref_report_consensus_signature",
    "ref_share_commit",
    "ref_joint_seed",
    "ref_derive_starts",
)


def verify_core_vectors() -> int:
    """Run the kit's own checker. 0 means this Python reproduces every published vector.

    Called from preflight: a runtime whose float repr or `ensure_ascii` handling is off should
    never reach a wire, and finding that out in the first second is much cheaper than finding it
    out in an opponent's audit.
    """
    return _kit.run()
