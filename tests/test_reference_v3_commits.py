from thief_agent.infra.report_parts import SubGameResult
from thief_agent.infra.report_reference import by_group
from thief_agent.reference_v3 import PoliceSearchPolicy  # noqa: F401
from thief_agent.reference_v3_commits import annotate, local_commit, reset

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


def test_reference_greeting_declares_the_running_commit() -> None:
    import sparring.netplay as netplay
    from sparring.config import SparConfig

    cfg = SparConfig(group_id="sparring-s82kma9e", natural_role="police")
    greeting = netplay.our_greeting(cfg, "police", 1, "1" * 32, {})
    assert greeting.to_wire()["github_commit"] == local_commit()
