"""Command-line and private metadata for the counted reference-v3 host."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any

from .counted_v3_contract import SCENT_MODEL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Counted authenticated reference-v3 series")
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
    parser.add_argument("--send", action="store_true")
    return parser.parse_args()


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
