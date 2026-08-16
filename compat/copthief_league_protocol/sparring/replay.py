"""Headless replay verification — the book's Replay Viewer, minus the GUI.

The book makes a replay viewer a threshold deliverable (App. E rule 20): load a log, step through
it, recompute the SHA-256 over each record and compare with the stored commitment, showing
**Verified OK** or **TAMPERED**. One TAMPERED voids the game immediately, with no appeal.

This is the checkable half of that, so it can run in CI and be handed to a partner to settle an
audit dispute offline. It needs no dependencies, and it works on anyone's log file that follows
the book's shape — including yours.
"""

from __future__ import annotations

from pathlib import Path

from sparring import kitref
from sparring.audit import audit_records


def _terms_beside(path: Path) -> dict:
    """The signed terms from a config artifact in the same directory, if one is there.

    Arms the audit's physics layer offline: board bound, barrier quota, step ceiling. The
    BINDING layer (revealed vs received commits) is inherently in-play knowledge and cannot be
    reconstructed from artifacts — replay is integrity + physics; the live audit is all three.
    """
    import json

    for cfg_path in sorted(path.parent.glob("config_*.json")):
        try:
            terms = json.loads(cfg_path.read_text(encoding="utf-8")).get("terms")
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(terms, dict):
            return terms
    return {}


def verify_log(path: Path) -> tuple[bool, str]:
    """Return (ok, human-readable report) for one log artifact."""
    import json

    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc.get("records") or []
    if not records:
        return False, f"{path.name}: no records — the game left nothing to verify"

    terms = _terms_beside(path)

    def audit(recs: list[dict]):
        return audit_records(recs,
                             board_size=terms.get("board_size"),
                             barriers_max=terms.get("barriers_max"),
                             max_steps=terms.get("max_steps"))

    # A bundle may seal ONE side or BOTH. Reading only `records` and reporting "Verified OK"
    # over a two-sided log certified half a file with the other half open on the desk — found
    # against anrbj666's counted logs, 2026-08-05, which seal `opponent_records` beside their
    # own. Every sealed record in the file gets re-hashed, and the line says how many.
    halves = [("own", records)]
    if doc.get("opponent_records"):
        halves.append(("opponent", doc["opponent_records"]))

    lines, ok, total = [], True, 0
    for label, recs in halves:
        result = audit(recs)
        total += len(recs)
        if result.passed:
            continue
        ok = False
        # TAMPERED is rule 20's word and it means one thing: a record did not reproduce its
        # commitment. A physics or binding failure is a different verdict and gets a different
        # word, or an honest team is told it forged a log it did not forge.
        verdict = ("TAMPERED — steps {} do not reproduce their commitments"
                   .format(result.tampered_steps) if result.tampered_steps else
                   "ILLEGAL — every record re-hashes, but steps {} break the signed physics"
                   .format(result.failed_steps))
        lines.append(f"{path.name} ({label} records): {verdict}\n    {result.detail}")

    if ok:
        sides = "both sides'" if len(halves) > 1 else "one side's"
        return True, (f"{path.name}: Verified OK — {total} records re-hashed against their "
                      f"commitments ({sides} sealed half)")
    return False, "\n  ".join(lines)


def verify_dir(root: Path) -> tuple[int, int, list[str]]:
    lines: list[str] = []
    ok = bad = 0
    for path in sorted(root.rglob("log_*.json")):
        good, report = verify_log(path)
        lines.append(("  " if good else "  ") + report)
        ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
    return ok, bad, lines


def cross_check_uid(root: Path) -> str | None:
    """All four artifacts must carry one game_uid — the key that joins them.

    Worth doing here as well as in ``tools/check_artifacts.py``: a replay that verifies every
    record of a log belonging to a *different* match has proved nothing at all.
    """
    import json

    uids = set()
    for path in sorted(root.rglob("*.json")):
        try:
            uids.add(json.loads(path.read_text(encoding="utf-8")).get("game_uid"))
        except (ValueError, UnicodeDecodeError):
            continue
    uids.discard(None)
    if len(uids) > 1:
        return (f"artifacts carry {len(uids)} different game_uids: {sorted(uids)} — they do not "
                f"all belong to one match, so verifying them together proves nothing")
    return None
