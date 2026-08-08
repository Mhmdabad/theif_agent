#!/usr/bin/env python3
"""Fail if a Python module exceeds the 150-line budget (task 0.10).

CONTRIBUTING.md asks for short modules (~150 lines) so responsibilities stay
separated. Files that already exceeded the budget when this gate landed are
listed in ``GRANDFATHERED`` with their line count at that moment as a ceiling:
they may shrink but may not grow. A new module must fit the budget outright.

The manifest polices itself: an entry whose file dropped back under the limit,
or no longer exists, fails the build until the entry is removed — the list
records debt, it does not grant exemptions forever.
"""

from __future__ import annotations

from pathlib import Path

LIMIT = 150
ROOTS = ("src", "scripts")

GRANDFATHERED: dict[str, int] = {
    "src/thief_agent/__main__.py": 367,
    "src/thief_agent/domain/belief.py": 152,
    "src/thief_agent/domain/bluff.py": 254,
    "src/thief_agent/domain/credibility.py": 184,
    "src/thief_agent/domain/crypto.py": 221,
    "src/thief_agent/domain/foci.py": 151,
    "src/thief_agent/domain/hints.py": 169,
    "src/thief_agent/domain/lock.py": 202,
    "src/thief_agent/domain/scent.py": 162,
    "src/thief_agent/domain/scent_audit.py": 287,
    "src/thief_agent/infra/artefacts.py": 176,
    "src/thief_agent/infra/ceremony.py": 822,
    "src/thief_agent/infra/config_file.py": 183,
    "src/thief_agent/infra/declaration.py": 225,
    "src/thief_agent/infra/dos_detector.py": 194,
    "src/thief_agent/infra/gatekeeper.py": 189,
    "src/thief_agent/infra/handshake.py": 269,
    "src/thief_agent/infra/inboxes.py": 500,
    "src/thief_agent/infra/latency.py": 206,
    "src/thief_agent/infra/mailer.py": 185,
    "src/thief_agent/infra/match_log.py": 229,
    "src/thief_agent/infra/mcp_client.py": 310,
    "src/thief_agent/infra/mcp_transport.py": 289,
    "src/thief_agent/infra/protocol.py": 154,
    "src/thief_agent/infra/quota.py": 195,
    "src/thief_agent/infra/report.py": 236,
    "src/thief_agent/infra/step_zero.py": 313,
    "src/thief_agent/infra/token_bucket.py": 204,
    "src/thief_agent/infra/token_store.py": 281,
    "src/thief_agent/infra/tunnel.py": 230,
    "src/thief_agent/infra/validation.py": 222,
    "src/thief_agent/runtime/driver.py": 270,
    "src/thief_agent/runtime/match.py": 427,
    "src/thief_agent/runtime/orchestrator.py": 688,
    "src/thief_agent/runtime/peer.py": 321,
    "src/thief_agent/runtime/subgame.py": 570,
    "src/thief_agent/shared/config.py": 185,
    "src/thief_agent/strategy/base.py": 154,
    "src/thief_agent/strategy/thief_brain.py": 218,
    "src/thief_agent/ui/app.py": 184,
    "src/thief_agent/ui/replay.py": 236,
    "src/thief_agent/ui/view.py": 157,
    "scripts/check_shared_drift.py": 262,
}
"""Modules over the budget when the gate landed: current count, frozen as a ceiling."""


def line_count(path: Path) -> int:
    """Physical lines, counted the way an editor shows them."""
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    problems: list[str] = []
    seen: set[str] = set()
    for root in ROOTS:
        for path in sorted(Path(root).rglob("*.py")):
            name = path.as_posix()
            seen.add(name)
            count = line_count(path)
            ceiling = GRANDFATHERED.get(name)
            if ceiling is None:
                if count > LIMIT:
                    problems.append(f"{name}: {count} lines (budget {LIMIT})")
            elif count > ceiling:
                problems.append(
                    f"{name}: grew from {ceiling} to {count} lines — grandfathered files "
                    "may shrink but not grow"
                )
            elif count <= LIMIT:
                problems.append(
                    f"{name}: now {count} lines, within budget — remove its GRANDFATHERED entry"
                )
    for name in sorted(set(GRANDFATHERED) - seen):
        problems.append(f"{name}: listed in GRANDFATHERED but absent — remove the entry")

    if problems:
        print(f"{len(problems)} line-budget problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    checked = len(seen)
    print(f"{checked} modules within the {LIMIT}-line budget ({len(GRANDFATHERED)} grandfathered)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
