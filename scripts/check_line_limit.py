#!/usr/bin/env python3
"""Fail if any Python module in ``src/`` is longer than 149 lines (task 0.10).

CONTRIBUTING.md asks for short modules (~150 lines) so responsibilities stay
separated. This gate is strict: there is no exemption list, and a file at 150
lines or more fails the build until it is split.
"""

from __future__ import annotations

from pathlib import Path

MAX_LINES = 149


def line_count(path: Path) -> int:
    """Physical lines, counted the way an editor shows them."""
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    over: list[tuple[int, str]] = []
    checked = 0
    for path in sorted(Path("src").rglob("*.py")):
        checked += 1
        count = line_count(path)
        if count > MAX_LINES:
            over.append((count, path.as_posix()))

    if over:
        print(f"{len(over)} module(s) over the {MAX_LINES}-line budget (split them):")
        for count, name in sorted(over, reverse=True):
            print(f"  {count:5d}  {name}")
        return 1
    print(f"{checked} modules all within the {MAX_LINES}-line budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
