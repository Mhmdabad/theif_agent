"""The sparring peer's command line.

    python -m sparring.cli selfplay        # a full six-sub-game series, zero dependencies
    python -m sparring.cli serve  --peer <url>   # a real peer over MCP  (needs fastmcp)
    python -m sparring.cli doctor --peer <url>   # is that URL a peer we can play?
    python -m sparring.cli replay  <dir>         # Verified OK / TAMPERED over log artifacts

Exit codes are distinct on purpose, so a script can tell the failures apart:

    0  clean          1  internal error        2  usage
    3  preflight refused (binding table / mail absence / vectors)
    4  handshake refused                       5  port already held
    6  played, but a sub-game ended in a technical loss or a tamper forfeit
    7  no opponent ever arrived
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sparring import CODE_VERSION, DEFAULT_GROUP_ID
from sparring.config import SparConfig
from sparring.deadlines import Budgets, BudgetError, FakeClock
from sparring.negotiate import Refused
from sparring.policies import REGISTRY
from sparring.preflight import PreflightRefused
from sparring.rules.scent import MODELS
from sparring.series import run_series

BANNER = (
    "SPARRING — UNCOUNTED (book App. E rule 52) — NO REPORT OWED — mail surface ABSENT ({scan})\n"
    "wire=reference-v3  scent={scent}  info={info}  policy={policy}  hint-lang={lang}  seed={seed}"
)

ASSUMPTIONS = (
    "  turn order: THIEF moves first — the reference implementation's own behaviour, which is\n"
    "  what wire=reference-v3 implies. The book's binding table does not settle it and the\n"
    "  wire_shape lock does not cover it: state it explicitly with a real opponent\n"
    "  (docs/PAIRING-PLAYBOOK.md stage 1)."
)


def _config(args) -> SparConfig:
    return SparConfig(
        group_id=args.group_id,
        opponent_group=args.opponent_group,
        policy=args.policy,
        scent_model=args.scent_model,
        seed=args.seed,
        lie_rate=args.lie_rate,
        hint_lang=args.hint_lang,
        natural_role="police" if args.role in ("police", "alternate") else "thief",
        budgets=Budgets(turn_timeout=args.turn_timeout, inbound_buffer_limit=args.reorder_window),
    )


def cmd_selfplay(args) -> int:
    cfg = _config(args)
    try:
        result = run_series(cfg, Path(args.artifacts), clock=FakeClock(),
                            sub_games=args.sub_games, check_vectors=not args.skip_vectors)
    except PreflightRefused as exc:
        print(exc, file=sys.stderr)
        return 3
    except BudgetError as exc:
        print(exc, file=sys.stderr)
        return 2

    from sparring.guards.no_mail import manifest_sha256
    scan = f"scan {manifest_sha256()[:8]}"
    print(BANNER.format(scan=scan, scent=cfg.scent_model, info=cfg.info_mode,
                        policy=cfg.policy, lang=cfg.hint_lang, seed=cfg.seed))
    print(ASSUMPTIONS)
    print(f"\n  game_id  {result.game_id}\n  game_uid {result.game_uid}\n")
    print("  sub  role    outcome    steps   score")
    for row in result.ledger:
        scores = "  ".join(str(v) for v in row.get("score", {}).values())
        print(f"  {row['sub_game_number']:>3}  {row.get('role',''):<7} "
              f"{row.get('outcome',''):<10} {row.get('steps',''):>5}   {scores}")
    print(f"\n  totals {result.totals}   sub-games won {result.won}   ties {result.ties}")
    print(f"  winner: {result.winner or 'series tied'}")
    print(f"\n  {len(result.artifacts)} artifacts under {Path(args.artifacts).resolve()}")
    print("  Nothing is owed for this run: sparring is not a game under App. E rules 32/35.")

    if not result.settled:
        print("\n  a sub-game never settled, so NO result artifact was written — that is the "
              "settlement\n  guard, and it is the habit that keeps rule 35 from zeroing your "
              "opponent too.", file=sys.stderr)
        return 6
    return 0 if result.clean else 6


def cmd_replay(args) -> int:
    from sparring.replay import cross_check_uid, verify_dir

    root = Path(args.path)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 2
    mismatch = cross_check_uid(root) if root.is_dir() else None
    if mismatch:
        print(f"  FAIL  {mismatch}", file=sys.stderr)
        return 6
    ok, bad, lines = verify_dir(root if root.is_dir() else root.parent)
    for line in lines:
        print(line)
    print(f"\n{ok} verified, {bad} tampered")
    return 6 if bad else 0


def cmd_doctor(args) -> int:
    try:
        from sparring.transport.client import diagnose
    except ImportError as exc:
        print(f"doctor needs the one dependency: pip install -r sparring/requirements.txt\n"
              f"  ({exc})", file=sys.stderr)
        return 2
    return diagnose(args.peer, timeout=args.turn_timeout)


def cmd_serve(args) -> int:
    try:
        from sparring.transport.server import serve
    except ImportError as exc:
        print(f"serve needs the one dependency: pip install -r sparring/requirements.txt\n"
              f"  ({exc})", file=sys.stderr)
        return 2
    try:
        cfg = _config(args)
    except BudgetError as exc:
        # A refused budget is an expected answer to a wrong flag, not a crash. It must be
        # readable in an ops window, where a traceback is the last thing anyone needs.
        print(exc, file=sys.stderr)
        return 2
    try:
        return serve(cfg, host=args.host, port=args.port, peer_url=args.peer,
                     artifacts=Path(args.artifacts), await_peer=args.await_peer)
    except PreflightRefused as exc:
        print(exc, file=sys.stderr)
        return 3
    except Refused as exc:
        print(exc, file=sys.stderr)
        return 4


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m sparring.cli", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=CODE_VERSION)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--group-id", default=DEFAULT_GROUP_ID,
                       help="must start with 'sparring-' — game_id is built from the group ids, "
                            "so this is what keeps practice artifacts distinguishable")
        p.add_argument("--opponent-group", default=None,
                       help="predeclare the paired group so game_uid is present in greeting 1")
        p.add_argument("--policy", default="greedy", choices=sorted(REGISTRY))
        p.add_argument("--scent-model", default=MODELS[0], choices=list(MODELS))
        p.add_argument("--seed", type=int, default=1234)
        p.add_argument("--lie-rate", type=float, default=0.25,
                       help="how often a hint is a declared bluff (the intent is sealed honestly)")
        p.add_argument("--hint-lang", default="mixed", choices=["en", "he", "mixed"],
                       help="'mixed' deliberately puts Hebrew and an emoji on the wire, so a "
                            "serializer that escapes non-ASCII fails here and not at an audit")
        p.add_argument("--role", default="alternate", choices=["police", "thief", "alternate"],
                       help="which side WE take in sub-game 1 — roles then alternate every "
                            "sub-game, all three choices included. 'alternate' is an alias for "
                            "'police' (police-first), kept for compatibility. Two sparring peers "
                            "playing each other need COMPLEMENTARY values: start exactly one "
                            "side with --role thief, or both open every sub-game as police and "
                            "the handshake refuses with SPAR-N07.")
        p.add_argument("--artifacts", default="runs")
        p.add_argument("--turn-timeout", type=float, default=180.0)
        p.add_argument("--reorder-window", type=int, default=4)

    p = sub.add_parser("selfplay", help="play a full series against ourselves (no dependencies)")
    common(p)
    p.add_argument("--sub-games", type=int, default=None)
    p.add_argument("--skip-vectors", action="store_true",
                   help="skip re-running the kit's vectors in preflight (CI already does)")
    p.set_defaults(func=cmd_selfplay)

    p = sub.add_parser("serve", help="run as a real peer over MCP")
    common(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8931)
    p.add_argument("--peer", default=None, help="the opponent's MCP URL")
    p.add_argument("--await-peer", action="store_true",
                   help="with --peer: poll the opponent's edge for one handshake budget "
                        "(turn-timeout) before the first greeting, so a startup race is not "
                        "read as an opponent that never arrived. Without --peer (tools-only "
                        "mode): print tunnel guidance while we listen")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("doctor", help="classify a peer URL before you agree a start time")
    p.add_argument("--peer", required=True)
    p.add_argument("--turn-timeout", type=float, default=10.0)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("replay", help="Verified OK / TAMPERED over log artifacts")
    p.add_argument("path")
    p.add_argument("--expect-clean", action="store_true")
    p.set_defaults(func=cmd_replay)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
