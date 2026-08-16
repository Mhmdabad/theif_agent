"""PROBE A1/A2/A3 — the commit-reveal loop is not closed by the audit.

Findings this reproduces (anrbj666 audit, 2026-08-04):
  A1  the audit never compares revealed commits against the commits RECEIVED in play
  A2  revealed payloads are never physics-checked
  A3  (partial) inbound barrier quota unchecked — see the second probe below

Run:  python probe_a1_audit_chain.py [path-to-kit-repo]
Expect (pre-fix): both probes print REPRODUCED. Post-fix: both print FIXED.

ADAPTED when committed (2026-08-04, imreeyal — the only probe of the four that needed it):
the original encoded the pre-fix API shape — a bare `audit_records(records)` call and a
positional-argument count — both of which stay true under the fix, because the closure armed
the new layers as KEYWORD-ONLY parameters (`played=`, `board_size=`, ...). The fabricated-log
call now arms the physics layer the way a live caller does, and the structural check asks for
the `played` parameter's existence instead of counting positionals. Original probe by
anrbj666; the finding and its verdict semantics are unchanged.
"""

import sys
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else
           str(Path(__file__).resolve().parents[2]))  # P5-16: relative default
sys.path.insert(0, str(KIT))

from sparring import kitref                                    # noqa: E402
from sparring.audit import audit_records                       # noqa: E402


def probe_fabricated_log_passes() -> bool:
    """A1+A2: a game that was NEVER PLAYED, revealed as if it were.

    Every record is internally self-consistent — commit == SHA256(canonical(payload)|nonce) —
    so re-hashing each record against its OWN embedded commit succeeds. Nothing compares these
    commits to what arrived on the wire during play (Inbox.played), and nothing inspects the
    payloads, so the moves may be physically impossible.
    """
    records = []
    for step in (1, 2, 3):
        payload = {"step": step,
                   "position": [9, 9],          # off a 7x7 board
                   "move": "MOVE:NE",           # diagonal: not in the book's move set
                   "intent": "truth"}
        nonce = "f" * 32
        records.append({"payload": payload, "nonce": nonce,
                        "commit": kitref.commit(payload, nonce)})

    result = audit_records(records, board_size=7, barriers_max=14, max_steps=35)
    print(f"  fabricated 3-step log -> passed={result.passed} "
          f"verified_steps={result.verified_steps}")
    print( "  payloads carry MOVE:NE (diagonal) at [9, 9] (off-board on 7x7)")
    return result.passed


def probe_audit_signature() -> bool:
    """A1, structurally: can audit_records be GIVEN the received commits at all?

    Pre-fix it had one parameter — the revealed list — so the comparison the docstring
    promised was impossible. Post-fix, `played` exists (keyword-only)."""
    code = audit_records.__code__
    names = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]
    print(f"  audit_records parameters: {names}")
    return "played" not in names


if __name__ == "__main__":
    print("PROBE A1/A2 — fabricated log vs the audit")
    fabricated = probe_fabricated_log_passes()
    print()
    print("PROBE A1 — the audit is never given the received commits")
    unbound = probe_audit_signature()
    print()
    verdict = "REPRODUCED (the loop is open)" if (fabricated and unbound) else "FIXED"
    print(f"VERDICT: {verdict}")
    raise SystemExit(0 if not (fabricated and unbound) else 1)
