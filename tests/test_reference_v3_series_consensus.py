from __future__ import annotations

from types import SimpleNamespace

from thief_agent import reference_v3 as _reference_v3  # noqa: F401
from thief_agent.counted_v3_report import build_report
from thief_agent.reference_v3_series_consensus import (
    settlement_scope,
    settlement_sha,
)
from thief_agent.shared.consensus import consensus_signature


def ledger() -> list[dict[str, object]]:
    return [
        {
            "sub_game_number": n,
            "role": "police" if n % 2 else "thief",
            "outcome": "survival",
            "score": 5 if n % 2 else 10,
        }
        for n in range(1, 7)
    ]


def result() -> SimpleNamespace:
    return SimpleNamespace(
        game_id="s82kma9e-vs-yamanagh",
        game_uid="89531a66-a492-75c4-fe79-37741c82f8f6",
        ledger=ledger(),
        settled=True,
    )


def test_their_spaced_serialization_golden_vector() -> None:
    scope = {
        "aggregate": {
            "series_tie": True,
            "sub_games_won": {"s82kma9e": 3, "yamanagh": 3},
            "ties": 0,
            "total_score": {"s82kma9e": 47, "yamanagh": 47},
            "winner_group": None,
        },
        "game_id": "s82kma9e-vs-yamanagh",
        "sub_games": [
            {
                "result": "survival",
                "roles": {"s82kma9e": "police", "yamanagh": "thief"},
                "score": {"s82kma9e": 0, "yamanagh": 8},
                "sub_game_number": 1,
                "winner_group": "yamanagh",
            }
        ],
    }
    assert consensus_signature(scope) == (
        "eec700497764529701164f3ef9eb494e72136c2642b0fd7c02973540615c4c14"
    )


def test_scope_derives_the_full_six_game_tie() -> None:
    scope = settlement_scope(result(), SimpleNamespace(group_id="s82kma9e"))
    assert scope["aggregate"] == {
        "total_score": {"s82kma9e": 47, "yamanagh": 47},
        "sub_games_won": {"s82kma9e": 3, "yamanagh": 3},
        "ties": 0,
        "winner_group": None,
        "series_tie": True,
    }
    assert len(scope["sub_games"]) == 6


def test_wire_digest_is_the_digest_stored_in_the_counted_report() -> None:
    played = result()
    for row in played.ledger:
        row.update(
            {
                "github_commit": "a" * 40,
                "opponent_commit": "b" * 40,
                "steps": 35,
                "audit_ok": True,
                "started_at": "2026-08-21T00:00:00+00:00",
                "ended_at": "2026-08-21T00:01:00+00:00",
            }
        )
    cfg = {
        "ours": "s82kma9e",
        "theirs": "yamanagh",
        "public": "https://ours/mcp",
        "peer": "https://theirs/mcp",
        "our_name": "s82kma9e",
        "our_members": [],
        "their_name": "yamanagh",
        "their_members": [],
        "cop_repo": "https://ours/cop",
        "thief_repo": "https://ours/thief",
        "opponent_cop_repo": "https://theirs/cop",
        "opponent_thief_repo": "https://theirs/thief",
    }
    report = build_report(played, cfg, "police", (4, 3))
    assert (
        settlement_sha(played, SimpleNamespace(group_id="s82kma9e")) == report.result_claim_sha256
    )
    rehearsal = build_report(played, cfg, "police", (4, 3), counted=False)
    assert rehearsal.to_dict()["league"] == {
        "authority": "book App. E rule 52 — the one counted series of this pairing",
        "counted": False,
        "reason": "friendly",
    }


def test_artifact_only_report_waits_for_peer_confirmation() -> None:
    played = result()
    for row in played.ledger:
        row.update(
            {
                "github_commit": "a" * 40,
                "opponent_commit": "b" * 40,
                "steps": 35,
                "audit_ok": True,
                "started_at": "2026-08-24T00:00:00+03:00",
                "ended_at": "2026-08-24T00:01:00+03:00",
            }
        )
    cfg = {
        "ours": "s82kma9e",
        "theirs": "yamanagh",
        "public": "https://ours/mcp",
        "peer": "https://theirs/mcp",
        "our_name": "s82kma9e",
        "our_members": [],
        "their_name": "yamanagh",
        "their_members": [],
        "cop_repo": "https://ours/cop",
        "thief_repo": "https://ours/thief",
        "opponent_cop_repo": "https://theirs/cop",
        "opponent_thief_repo": "https://theirs/thief",
    }
    report = build_report(played, cfg, "police", (6, 1), agreed=False)
    assert report.agreed is False
    assert report.result_claim_sha256
