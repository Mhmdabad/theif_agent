"""Command-line and private metadata for the counted reference-v3 host."""

from __future__ import annotations

import argparse
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from .counted_v3_contract import SCENT_MODEL

AUTHENTICATED = "authenticated-v3"
STANDARD = "standard-v3"


def _utc_stamp(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected UTC YYYY-MM-DDTHH:MM:SSZ") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise argparse.ArgumentTypeError("expected UTC YYYY-MM-DDTHH:MM:SSZ")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Counted reference-v3 series")
    parser.add_argument("--profile", choices=(AUTHENTICATED, STANDARD), default=AUTHENTICATED)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--public", required=True)
    parser.add_argument("--role", choices=("police", "thief"), required=True)
    parser.add_argument("--group-id", default="s82kma9e")
    parser.add_argument("--opponent-group", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", type=Path, default=Path("artefacts"))
    parser.add_argument("--games-played", type=int, required=True)
    parser.add_argument("--opponent-games-played", type=int, required=True)
    parser.add_argument("--opponent-cop-commit")
    parser.add_argument("--opponent-thief-commit")
    parser.add_argument("--scent-model", default=SCENT_MODEL, choices=(SCENT_MODEL,))
    parser.add_argument("--turn-timeout", type=float, default=30.0)
    parser.add_argument("--game-start", type=_utc_stamp)
    parser.add_argument("--manual-start", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true")
    mode.add_argument("--rehearsal", action="store_true")
    args = parser.parse_args(argv)
    if args.profile == AUTHENTICATED and not args.game_start:
        parser.error("--game-start is required for authenticated-v3")
    if args.profile == STANDARD:
        if args.send:
            parser.error("standard-v3 writes first; send later after --confirm-sha")
        if not args.opponent_cop_commit or not args.opponent_thief_commit:
            parser.error("standard-v3 requires both opponent role commits")
    return args


def private_config() -> dict[str, Any]:
    path = next(Path("config").glob("*/game.toml"))
    return tomllib.loads(path.read_text(encoding="utf-8"))


def report_config(args: argparse.Namespace, private: dict[str, Any]) -> dict[str, Any]:
    ours, theirs = private["game"], private["teams"]["them"]
    return {
        "ours": args.group_id,
        "theirs": args.opponent_group,
        "public": args.public,
        "peer": args.peer,
        "our_name": ours["group_name"],
        "our_members": ours["members"],
        "their_name": theirs["group_name"],
        "their_members": theirs["members"],
        "cop_repo": ours["repos"]["cop"],
        "thief_repo": ours["repos"]["thief"],
        "opponent_cop_repo": theirs["repos"]["cop"],
        "opponent_thief_repo": theirs["repos"]["thief"],
    }
