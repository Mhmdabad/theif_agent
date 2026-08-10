#!/usr/bin/env python3
"""Watch a match as an animated emoji board in the terminal.

The peers write their logs when the series ends, so this waits for the files
and then plays every sub-game back step by step — an instant replay in the
CLI, no display server needed. In a local rehearsal both sides' logs are on
this machine, so the board shows both pieces; that is the spectator's view,
not either agent's (each agent still only ever knew its own side).

    python scripts/watch_match.py --game-id LOCAL_01

Run it in a third terminal before or during the match; it waits patiently.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

EMPTY, WALL, COP, THIEF, BOTH = "⬜", "🧱", "🚓", "🏃", "💥"
CLEAR = "\033[H\033[2J"


def sides(thief_dir: Path, police_dir: Path, game_id: str, sub_game: int) -> list[dict]:
    name = f"log_{game_id}_g{sub_game:02d}.json"
    logs = []
    for directory in (thief_dir, police_dir):
        path = directory / name
        if path.exists():
            logs.append(json.loads(path.read_text()))
    return logs


def frame(logs: list[dict], step: int) -> tuple[str, list[str]]:
    """One board and the two hints, from whatever both sides revealed at ``step``."""
    grid_size, cop, thief, walls, hints = 8, None, None, set(), []
    for log in logs:
        for row in log.get("steps", []):
            reveal = row.get("reveal") or {}
            if row.get("step") != step or not reveal:
                continue
            state = reveal.get("state", {})
            grid_size = int(state.get("grid_size", grid_size))
            walls |= {tuple(cell) for cell in state.get("barriers", [])}
            who = reveal.get("role", log.get("role", ""))
            cell = state.get("self")
            if cell is not None:
                if who == "police":
                    cop = tuple(cell)
                else:
                    thief = tuple(cell)
            if reveal.get("hint"):
                hints.append(f"{'🚓' if who == 'police' else '🏃'} {reveal['hint']}")
    rows = []
    for r in range(grid_size):
        row = []
        for c in range(grid_size):
            here = (r, c)
            if here == cop == thief:
                row.append(BOTH)
            elif here == cop:
                row.append(COP)
            elif here == thief:
                row.append(THIEF)
            elif here in walls:
                row.append(WALL)
            else:
                row.append(EMPTY)
        rows.append("".join(row))
    return "\n".join(rows), hints


def play(thief_dir: Path, police_dir: Path, game_id: str, delay: float) -> None:
    for sub_game in range(1, 7):
        logs = sides(thief_dir, police_dir, game_id, sub_game)
        if not logs:
            continue
        steps = sorted({row.get("step", 0) for log in logs for row in log.get("steps", [])})
        for step in steps:
            if step < 1:
                continue
            board, hints = frame(logs, step)
            print(CLEAR, end="")
            print(f"🎮 {game_id} — sub-game {sub_game}/6, step {step}")
            print(board)
            for hint in hints[:2]:
                print(f"  💬 {hint}")
            time.sleep(delay)


def summary(thief_dir: Path, game_id: str) -> None:
    path = thief_dir / f"result_{game_id}.json"
    if not path.exists():
        return
    result = json.loads(path.read_text())
    series = result.get("series_result") or {}
    agreed = (
        "✅ agreed by both sides" if result.get("result_agreed_with_opponent") else "❌ NOT agreed"
    )
    print(f"\n🏁 final — {agreed}")
    for group, score in (series.get("total_score") or {}).items():
        print(f"   {group}: {score}")
    if series.get("series_tie"):
        print("   🤝 series tie — both groups take the tie score")
    elif series.get("winner_group"):
        print(f"   🏆 winner: {series['winner_group']}")


def main() -> int:
    base = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--thief", type=Path, default=base / "theif_agent" / "artefacts")
    parser.add_argument("--police", type=Path, default=base / "police_agent" / "artefacts")
    parser.add_argument("--delay", type=float, default=0.35, help="seconds per step")
    args = parser.parse_args()

    print(f"⏳ waiting for logs of {args.game_id} … (start the match in the other terminals)")
    while not sides(args.thief, args.police, args.game_id, 1):
        time.sleep(1.0)
    while not (args.thief / f"result_{args.game_id}.json").exists():
        time.sleep(1.0)  # let the series finish so every sub-game plays back in one go
    play(args.thief, args.police, args.game_id, args.delay)
    summary(args.thief, args.game_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
