from datetime import datetime
from types import SimpleNamespace

import pytest

from thief_agent import reference_v3 as _reference_v3  # noqa: F401
from thief_agent.counted_v3_evidence import add_timings, capture, require_complete
from thief_agent.infra.report import Report, Repositories, SubGameResult
from thief_agent.infra.report_parts import ReportError


class Artifacts:
    def log(self, number: int) -> int:
        return number


def test_capture_adds_real_timestamps_after_the_audit_log() -> None:
    from sparring.turnloop import SubGamePeer

    peer = object.__new__(SubGamePeer)
    peer.n = 1
    netplay = SimpleNamespace(
        _play_one=lambda current: current.n,
        ArtifactSet=Artifacts,
    )
    with capture(netplay) as timings:
        assert netplay._play_one(peer) == 1
        assert netplay.ArtifactSet().log(1) == 1
    ledger = [{"sub_game_number": 1}]
    add_timings(ledger, timings)
    assert ledger[0]["started_at"]
    assert ledger[0]["ended_at"]
    started_at = ledger[0]["started_at"]
    assert isinstance(started_at, str)
    assert datetime.fromisoformat(started_at).utcoffset() is not None


def a_report(started: str = "2026-08-17T21:00:00+03:00") -> Report:
    sub = SubGameResult(
        1,
        20,
        5,
        "a" * 40,
        opponent_commit_hash="b" * 40,
        started_at=started,
        ended_at="2026-08-17T21:01:00+03:00",
    )
    repos = Repositories("our-cop", "our-thief", "their-cop", "their-thief")
    return Report(
        "them-vs-us",
        "police",
        "us",
        "them",
        (sub,),
        0,
        True,
        repositories=repos,
        game_uid="uid",
        result_claim_sha256="digest",
    )


def test_complete_kit_shaped_report_passes() -> None:
    require_complete(a_report())


def test_empty_timestamp_blocks_a_counted_report() -> None:
    with pytest.raises(ReportError, match="started_at"):
        require_complete(a_report(""))
