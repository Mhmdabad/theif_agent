"""Pairing-specific pregame and settlement behavior for counted reference-v3."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from sparring.config import SparConfig
from sparring.transport.client import McpClient
from sparring.transport.loopback import Inboxes

from .counted_v3_args import AUTHENTICATED, STANDARD
from .counted_v3_setup import arm_consensus, save_step_zero, step_zero_spec
from .counted_v3_step0_exchange import exchange


def prepare(args: argparse.Namespace, shared: dict[str, Any]) -> None:
    if args.profile == AUTHENTICATED:
        arm_consensus(shared)
    else:
        os.environ.pop("SERIES_CONSENSUS", None)


def action(args: argparse.Namespace) -> str:
    return "authenticated Step-0" if args.profile == AUTHENTICATED else "g01 handshake"


def negotiate(
    args: argparse.Namespace,
    private: dict[str, Any],
    shared: dict[str, Any],
    cfg: SparConfig,
    commits: dict[str, str],
    client: McpClient,
    inboxes: Inboxes,
) -> dict[str, str | None]:
    peer_commits: dict[str, str | None] = {
        "police": args.opponent_cop_commit,
        "thief": args.opponent_thief_commit,
    }
    if args.profile != AUTHENTICATED:
        return peer_commits
    spec = step_zero_spec(args, private, shared, cfg.terms(), commits)
    ours, theirs, authenticated = exchange(client, inboxes, spec, args.turn_timeout)
    save_step_zero(args.out, spec.game_id, ours, theirs)
    return {role: value if value else None for role, value in authenticated.items()}


def agreed(args: argparse.Namespace) -> bool:
    return str(args.profile) == AUTHENTICATED


def basis(args: argparse.Namespace) -> str:
    return "authenticated consensus" if agreed(args) else "artifact digest"


def deliver(args: argparse.Namespace, path: Path, private: dict[str, object], digest: str) -> int:
    if args.rehearsal:
        print("authenticated rehearsal complete: uncounted and email disabled")
        return 0
    if args.profile == STANDARD:
        print(f"not sent: exchange this artifact digest with the peer first: {digest}")
        print(
            f"after it matches: uv run python -m thief_agent report --report {path} "
            f"--confirm-sha {digest} --send"
        )
        return 0
    if not args.send:
        print("not sent: final counted launch must include --send")
        return 0
    from .cli_report import report as send_report  # noqa: PLC0415

    return send_report(argparse.Namespace(report=str(path), send=True), private)
