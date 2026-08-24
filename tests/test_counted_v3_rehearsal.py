import argparse
import json
from pathlib import Path

import pytest

from thief_agent import cli_report
from thief_agent import counted_v3 as _counted_v3  # noqa: F401
from thief_agent.counted_v3_args import parse_args
from thief_agent.counted_v3_profiles import deliver
from thief_agent.counted_v3_report import promote_wire

BASE_ARGS = [
    "--profile",
    "authenticated-v3",
    "--peer",
    "https://peer/mcp",
    "--public",
    "https://ours/mcp",
    "--role",
    "thief",
    "--opponent-group",
    "MaRs-777",
    "--port",
    "8802",
    "--games-played",
    "5",
    "--opponent-games-played",
    "1",
    "--game-start",
    "2026-08-23T18:30:00Z",
]

STANDARD_ARGS = [
    "--profile",
    "standard-v3",
    "--peer",
    "https://peer/mcp",
    "--public",
    "https://ours/mcp",
    "--role",
    "thief",
    "--opponent-group",
    "amirmtan",
    "--port",
    "8802",
    "--games-played",
    "6",
    "--opponent-games-played",
    "1",
    "--opponent-cop-commit",
    "4" * 40,
    "--opponent-thief-commit",
    "e" * 40,
]


def test_rehearsal_and_send_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        parse_args([*BASE_ARGS, "--rehearsal", "--send"])


def test_manual_start_gate_is_available() -> None:
    assert parse_args([*BASE_ARGS, "--rehearsal", "--manual-start"]).manual_start is True


def test_game_start_requires_exact_utc_seconds() -> None:
    with pytest.raises(SystemExit):
        parse_args([*BASE_ARGS[:-1], "2026-08-23T18:30:00+00:00"])


def test_standard_v3_needs_no_game_start_and_cannot_send_immediately() -> None:
    args = parse_args(STANDARD_ARGS)
    assert args.game_start is None
    with pytest.raises(SystemExit):
        parse_args([*STANDARD_ARGS, "--send"])


def test_the_default_profile_preserves_authenticated_v3() -> None:
    without_profile = BASE_ARGS[2:]
    assert parse_args(without_profile).profile == "authenticated-v3"


def test_standard_v3_requires_both_frozen_peer_commits() -> None:
    with pytest.raises(SystemExit):
        parse_args(STANDARD_ARGS[:-2])


def test_rehearsal_delivery_cannot_call_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("mail path was called")

    monkeypatch.setattr(cli_report, "report", fail)
    args = argparse.Namespace(rehearsal=True, send=False)
    assert deliver(args, Path("result.json"), {}, "") == 0


def test_rehearsal_promotes_wire_as_uncounted(tmp_path: Path) -> None:
    source = tmp_path / ".wire" / "sparring_test"
    source.mkdir(parents=True)
    (source / "log_test_g01.json").write_text("{}", encoding="utf-8")
    promote_wire(tmp_path, {}, counted=False)
    body = json.loads((tmp_path / "log_test_g01.json").read_text(encoding="utf-8"))
    assert body["league"]["counted"] is False
    assert body["league"]["reason"] == "friendly"
