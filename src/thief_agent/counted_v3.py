"""Counted reference-v3 host with frozen Step-0 V2 authentication."""
# ruff: noqa: I001

from __future__ import annotations

import argparse
import threading
import time
from types import SimpleNamespace

from dotenv import load_dotenv

from . import reference_v3 as _reference_v3  # noqa: F401

from sparring import kitref
from sparring.config import SparConfig
from sparring.deadlines import Budgets
from sparring.netplay import NetResult
from sparring.transport.client import McpClient, edge_answers
from sparring.transport.loopback import Inboxes

from .counted_v3_args import parse_args, private_config, report_config
from .counted_v3_contract import TERMS_SHA, load_contract
from .counted_v3_evidence import add_timings, capture, require_complete
from .counted_v3_report import build_report, promote_wire
from .counted_v3_revisions import role_commits
from .counted_v3_setup import arm_consensus, save_step_zero, step_zero_spec
from .counted_v3_step0_exchange import exchange
from .counted_v3_wire import build_server
from .reference_v3_commits import annotate as annotate_commits
from .reference_v3_commits import configure_local
from .reference_v3_commits import reset as reset_commits


def _await_peer(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if edge_answers(url, 2.0):
            return True
        time.sleep(0.25)
    return False


def _config(args: argparse.Namespace) -> SparConfig:
    cfg = SparConfig(
        group_id=args.group_id,
        group_name=args.group_id,
        opponent_group=args.opponent_group,
        natural_role=args.role,
        policy="search",
        scent_model=args.scent_model,
        budgets=Budgets(turn_timeout=args.turn_timeout, watchdog_timeout=60.0),
    )
    if kitref.canonical_hash(cfg.terms()) != TERMS_SHA:
        raise RuntimeError("runtime terms differ from the frozen counted terms")
    return cfg


def _start_server(args: argparse.Namespace, cfg: SparConfig, inboxes: Inboxes) -> None:
    server = build_server(cfg, inboxes)
    threading.Thread(
        target=server.run,
        kwargs={
            "transport": "http",
            "host": args.host,
            "port": args.port,
            "show_banner": False,
        },
        daemon=True,
    ).start()


def _play(
    args: argparse.Namespace, cfg: SparConfig, inboxes: Inboxes, client: McpClient
) -> NetResult:
    import sparring.netplay as netplay

    netplay.assert_uncounted_group = lambda _group: None
    netplay.assert_sparring_ready = lambda _cfg: SimpleNamespace(mail_scan_sha256="counted-v3")
    with capture(netplay) as timings:
        result = netplay.play_series(cfg, client, inboxes, args.out / ".wire")
    add_timings(result.ledger, timings)
    return result


def main() -> int:
    load_dotenv()
    args, private, shared = parse_args(), private_config(), load_contract()
    reset_commits()
    commits = role_commits()
    configure_local(commits)
    cfg = _config(args)
    arm_consensus(shared)
    inboxes = Inboxes()
    _start_server(args, cfg, inboxes)
    if not _await_peer(args.peer, args.turn_timeout):
        print(f"opponent edge did not become reachable: {args.peer}")
        return 7
    client = McpClient(args.peer, timeout=cfg.budgets.connect_timeout)
    spec = step_zero_spec(args, private, shared, cfg.terms(), commits)
    try:
        ours, theirs, peer_commits = exchange(client, inboxes, spec, args.turn_timeout)
    except (RuntimeError, ValueError) as exc:
        print(f"counted Step-0 refused: {exc}")
        return 9
    save_step_zero(args.out, spec.game_id, ours, theirs)
    result = _play(args, cfg, inboxes, client)
    if not result.settled or len(result.ledger) != 6:
        return 6
    try:
        annotate_commits(result.ledger, peer_commits["police"], peer_commits["thief"])
    except ValueError as exc:
        print(f"counted report blocked: {exc}")
        return 8
    report_cfg = report_config(args, private)
    report = build_report(
        result, report_cfg, args.role, (args.games_played, args.opponent_games_played)
    )
    require_complete(report)
    promote_wire(args.out, report_cfg)
    path = args.out / report.filename
    path.write_text(report.to_json(), encoding="utf-8")
    print(f"counted result derived after authenticated consensus: {path}")
    if not args.send:
        print("not sent: final counted launch must include --send")
        return 0
    from .cli_report import report as send_report

    return send_report(argparse.Namespace(report=str(path), send=True), private)


if __name__ == "__main__":
    raise SystemExit(main())
