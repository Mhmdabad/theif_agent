"""Counted reference-v3 host: proven wire, real identity, normal report."""
# ruff: noqa: I001

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import reference_v3 as _reference_v3  # noqa: F401 - exposes vendored sparring

from sparring.config import SparConfig
from sparring.deadlines import Budgets
from sparring.transport.client import McpClient, edge_answers
from sparring.transport.loopback import Inboxes
from sparring.transport.server import build_server

from .counted_v3_report import agreement, build_report, promote_wire
from .infra.report import Report


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--turn-timeout", type=float, default=180.0)
    parser.add_argument("--send", action="store_true")
    return parser.parse_args()


def _private() -> dict[str, Any]:
    import tomllib

    path = Path("config/thief/game.toml")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _report_cfg(args: argparse.Namespace, private: dict[str, Any]) -> dict[str, Any]:
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


def _settle(client: McpClient, inboxes: Inboxes, report: Report, timeout: float) -> bool:
    claim, digest = agreement(report)
    client.negotiate({"final_result": claim, "result_sha256": digest, "game_uid": report.game_uid})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if inboxes.agreements:
            other = inboxes.agreements.popleft()
            if "result_sha256" not in other:
                continue
            return bool(
                other.get("game_uid") == report.game_uid and other.get("result_sha256") == digest
            )
        time.sleep(0.1)
    return False


def _await_peer(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if edge_answers(url, 2.0):
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    args, private = _args(), _private()
    cfg = SparConfig(
        group_id=args.group_id,
        group_name=args.group_id,
        natural_role=args.role,
        policy="search",
        budgets=Budgets(turn_timeout=args.turn_timeout),
    )
    server_inboxes = Inboxes()
    server = build_server(cfg, server_inboxes)
    threading.Thread(
        target=server.run,
        kwargs={"transport": "http", "host": args.host, "port": args.port, "show_banner": False},
        daemon=True,
    ).start()
    if not _await_peer(args.peer, args.turn_timeout):
        print(f"opponent edge did not become reachable: {args.peer}")
        return 7
    client = McpClient(args.peer, timeout=cfg.budgets.connect_timeout)
    import sparring.netplay as netplay

    netplay.assert_uncounted_group = lambda _group: None
    netplay.assert_sparring_ready = lambda _cfg: SimpleNamespace(mail_scan_sha256="counted-v3")
    result = netplay.play_series(cfg, client, server_inboxes, args.out / ".wire")
    if not result.settled or len(result.ledger) != 6:
        return 6
    report_cfg = _report_cfg(args, private)
    report = build_report(
        result, report_cfg, args.role, (args.games_played, args.opponent_games_played)
    )
    if not _settle(client, server_inboxes, report, args.turn_timeout):
        print("result consensus failed; refusing to write or send a counted report")
        return 8
    promote_wire(args.out, report_cfg)
    path = args.out / report.filename
    path.write_text(report.to_json(), encoding="utf-8")
    print(f"counted result agreed and written: {path}")
    if args.send:
        from .cli_report import report as send_report

        return send_report(argparse.Namespace(report=str(path), send=True), private)
    print("not sent: rerun report --send only after inspecting both teams' artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
