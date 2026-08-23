import argparse
import json
from pathlib import Path

import pytest

from thief_agent import cli_report, counted_v3
from thief_agent.counted_v3_args import parse_args
from thief_agent.counted_v3_report import promote_wire

BASE_ARGS = [
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
]


def test_rehearsal_and_send_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        parse_args([*BASE_ARGS, "--rehearsal", "--send"])


def test_manual_start_gate_is_available() -> None:
    assert parse_args([*BASE_ARGS, "--rehearsal", "--manual-start"]).manual_start is True


def test_rehearsal_delivery_cannot_call_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("mail path was called")

    monkeypatch.setattr(cli_report, "report", fail)
    args = argparse.Namespace(rehearsal=True, send=False)
    assert counted_v3._deliver(args, "result.json", {}) == 0


def test_rehearsal_promotes_wire_as_uncounted(tmp_path: Path) -> None:
    source = tmp_path / ".wire" / "sparring_test"
    source.mkdir(parents=True)
    (source / "log_test_g01.json").write_text("{}", encoding="utf-8")
    promote_wire(tmp_path, {}, counted=False)
    body = json.loads((tmp_path / "log_test_g01.json").read_text(encoding="utf-8"))
    assert body["league"]["counted"] is False
    assert body["league"]["reason"] == "friendly"
