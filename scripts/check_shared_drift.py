#!/usr/bin/env python3
"""Fail if a shared module has drifted from the sibling repository.

The cop and thief may not share a live-state module — doing so disqualifies the
solution — so the logic they both need is **deliberately duplicated** and must
be kept in lockstep by hand. That is a rule with no compiler behind it, and it
has already been broken three times: placement-reach validation existed only in
the cop repo, so this agent would have accepted a barrier on any cell of the
board; ``domain/search.py`` was simply absent here; and the Appendix F accessor
landed on the cop side only, leaving book values hard-coded here, where a
*fixed* parameter drifting is a disqualification discovered at audit.

All three were found by using the code, not by reviewing it. This turns the
next one into a build failure at the moment it appears.

The manifest is explicit rather than a glob. Some divergence is intentional —
role names, role-specific framing, the brains themselves — so a check that
guessed would either miss real drift or cry wolf about the deliberate kind.
Each intentional divergence carries its reason, making the list a statement
about the design rather than a suppression.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SIBLING_URL = "https://github.com/Mhmdabad/police_agent"
SIBLING_PACKAGE = "cop_agent"
OUR_PACKAGE = "thief_agent"

SHARED: tuple[str, ...] = (
    "domain/axes.py",
    "domain/board.py",
    "domain/crypto.py",
    "domain/rules.py",
    "domain/search.py",
    "domain/actions.py",
    "domain/scoring.py",
    "infra/inboxes.py",
    "infra/mcp_client.py",
    "infra/mcp_server.py",
    "infra/protocol.py",
    "infra/validation.py",
    "runtime/deadline.py",
    "runtime/scheduler.py",
    "runtime/state_machine.py",
    "runtime/watchdog.py",
    "shared/appendix_f.py",
    "shared/config.py",
    "shared/naming.py",
    "shared/terms.py",
)
"""Modules that must be identical once the package name is normalised."""

DIVERGENT: dict[str, str] = {
    "__init__.py": "package docstring names the role this repo implements",
    "domain/outcome.py": "capture-claim framing differs: who is obliged, and to whom",
    "runtime/orchestrator.py": "role default, and the duplicate-role failure differs by side",
    "strategy/base.py": "notes which hooks this role overrides",
    "strategy/loader.py": "reads police_class vs thief_class",
    "domain/scent.py": (
        "migrating: shared, temporarily unchecked while the Gaussian falloff lands "
        "in both repos. Restored to SHARED immediately after this."
    ),
    "strategy/barriers.py": "cop-only; the thief places no barriers",
    "strategy/containment.py": "thief-only; the cop builds the trap rather than reading it",
    "strategy/police_brain.py": "the cop's policy; no counterpart here",
    "strategy/thief_brain.py": "the thief's policy; no counterpart there",
}
"""Files that differ on purpose, each with the reason. Not a suppression list."""

_PACKAGE_RE = re.compile(rf"\b({SIBLING_PACKAGE}|{OUR_PACKAGE})\b")


def normalise(text: str) -> str:
    """Erase the package name, which is the one difference we expect."""
    return _PACKAGE_RE.sub("AGENT", text)


def clone_sibling(destination: Path, ref: str) -> Path:
    """Shallow-clone the sibling repository."""
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, SIBLING_URL, str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    return destination / "src" / SIBLING_PACKAGE


def compare(ours: Path, theirs: Path) -> list[str]:
    """Report every shared module that differs, or is missing on either side."""
    problems: list[str] = []
    for relative in SHARED:
        mine, sibling = ours / relative, theirs / relative
        if not mine.exists():
            problems.append(f"{relative}: missing here")
            continue
        if not sibling.exists():
            problems.append(f"{relative}: missing in the sibling repository")
            continue
        if normalise(mine.read_text()) != normalise(sibling.read_text()):
            problems.append(f"{relative}: drifted")
    return problems


def unlisted(ours: Path) -> list[str]:
    """Report modules that are in neither list.

    A new shared module that nobody added to the manifest is unchecked, and
    unchecked is how the last three gaps happened.
    """
    known = set(SHARED) | set(DIVERGENT)
    found = {str(p.relative_to(ours)) for p in ours.rglob("*.py")}
    return sorted(f for f in found - known if not f.endswith("__init__.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main", help="sibling branch to compare against")
    parser.add_argument("--src", default=f"src/{OUR_PACKAGE}", help="our package root")
    args = parser.parse_args()

    ours = Path(args.src)
    workspace = Path(tempfile.mkdtemp(prefix="drift-"))
    try:
        theirs = clone_sibling(workspace / "sibling", args.ref)
        problems = compare(ours, theirs)
        stray = unlisted(ours)
    except subprocess.CalledProcessError as exc:
        print(f"could not clone {SIBLING_URL}: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    if stray:
        print("modules in neither SHARED nor DIVERGENT (add them to the manifest):")
        for name in stray:
            print(f"  {name}")
    if problems:
        print(f"\nshared modules out of lockstep with {SIBLING_URL}:")
        for problem in problems:
            print(f"  {problem}")
        print(
            "\nThe two agents duplicate this logic deliberately — sharing a live-state\n"
            "module disqualifies the solution — so a change to one must land in both."
        )
    if problems or stray:
        return 1
    print(f"{len(SHARED)} shared modules in lockstep with {SIBLING_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
