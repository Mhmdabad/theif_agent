from thief_agent.infra.report_parts import SubGameResult
from thief_agent.infra.report_reference import by_group
from thief_agent.reference_v3 import PoliceSearchPolicy  # noqa: F401
from thief_agent.reference_v3_commits import annotate, configure_local, local_commit, reset

COP = "a" * 40
THIEF = "b" * 40


def test_legacy_peer_commits_are_applied_by_opponent_role() -> None:
    ledger = [
        {"sub_game_number": 1, "role": "thief"},
        {"sub_game_number": 2, "role": "police"},
    ]
    reset()
    annotate(ledger, COP, THIEF)
    assert [row["opponent_commit"] for row in ledger] == [COP, THIEF]
    assert all(row["github_commit"] == local_commit() for row in ledger)


def test_report_row_carries_both_declared_commits() -> None:
    sub = SubGameResult(1, 20, 5, "c" * 40, opponent_commit_hash="d" * 40)
    row = by_group(sub, "us", "them", "police", "us-vs-them")
    assert row["github_commit"] == {"us": "c" * 40, "them": "d" * 40}


def test_local_rows_are_attributed_to_the_role_repository() -> None:
    ledger = [
        {"sub_game_number": 1, "role": "thief"},
        {"sub_game_number": 2, "role": "police"},
    ]
    reset()
    configure_local({"police": COP, "thief": THIEF})
    annotate(ledger, COP, THIEF)
    assert [row["github_commit"] for row in ledger] == [THIEF, COP]
    reset()


def test_reference_greeting_declares_the_running_commit() -> None:
    import sparring.netplay as netplay
    from sparring.config import SparConfig

    cfg = SparConfig(group_id="sparring-s82kma9e", natural_role="police")
    greeting = netplay.our_greeting(cfg, "police", 1, "1" * 32, {})
    assert greeting.to_wire()["github_commit"] == local_commit()


def test_configured_pairing_declares_uid_in_first_greeting() -> None:
    import sparring.netplay as netplay
    from sparring import kitref
    from sparring.cli import _config, build_parser

    args = build_parser().parse_args(
        ["serve", "--group-id", "sparring-s82kma9e", "--opponent-group", "sparring-yamanagh"]
    )
    cfg = _config(args)
    greeting = netplay.our_greeting(
        cfg, "police", 1, "1" * 32, {}, opponent_group=cfg.opponent_group
    )
    assert greeting.game_uid == kitref.game_uid(
        cfg.terms(), "sparring-s82kma9e", "sparring-yamanagh"
    )
