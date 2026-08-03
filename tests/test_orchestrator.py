"""Tests for the single-gateway orchestrator."""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.tools import PROTOCOL_VERSION, PeerIdentity, ToolSurface
from thief_agent.runtime.orchestrator import MatchAborted, Orchestrator
from thief_agent.shared.config import config_sha256

OURS = PeerIdentity(group_id="s82kma9e", role="thief")
SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)


def shipped() -> dict[str, Any]:
    return json.loads((Path(__file__).parents[1] / "config/game.json").read_text())  # type: ignore[no-any-return]


class FakeTransport:
    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append({"tool": tool, "payload": payload})
        outcome = self._outcomes.pop(0) if self._outcomes else {"ok": True, "data": {}}
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


def orchestrator(*outcomes: object) -> tuple[Orchestrator, FakeTransport]:
    transport = FakeTransport(*outcomes)
    tools = ToolSurface(OURS, config_sha256(shipped()), lambda: "deadbeef")
    return Orchestrator(tools, OpponentClient(transport, SETTINGS)), transport


class TestSingleGateway:
    def test_inbound_is_delegated_not_reimplemented(self) -> None:
        """Two validators disagreeing is worse than one."""
        orch, _ = orchestrator()
        result = orch.handle_inbound(
            "handshake",
            {"group_id": "them", "role": "cop", "protocol_version": PROTOCOL_VERSION},
        )
        assert result.ok

    def test_hostile_inbound_still_becomes_a_refusal(self) -> None:
        orch, _ = orchestrator()
        assert not orch.handle_inbound("handshake", None).ok

    def test_outbound_returns_a_structured_result(self) -> None:
        orch, _ = orchestrator({"ok": True, "detail": "", "data": {"x": 1}})
        assert orch.call_opponent("ping", {}).data == {"x": 1}

    def test_no_game_rule_lives_here(self) -> None:
        """It coordinates and does not decide."""
        import thief_agent.runtime.orchestrator as module

        source = Path(module.__file__ or "").read_text()
        for rule_word in ("legal_moves", "apply_move", "is_capture", "BOOK_SCORES"):
            assert rule_word not in source


class TestHeartbeat:
    def test_inbound_and_outbound_both_beat(self) -> None:
        orch, _ = orchestrator()
        orch.handle_inbound("ping", {})
        orch.call_opponent("ping", {})
        assert orch.heartbeats == ["inbound:ping", "outbound:ping"]

    def test_events_are_published(self) -> None:
        orch, _ = orchestrator()
        seen: list[str] = []
        orch.on_event = seen.append
        orch.handle_inbound("ping", {})
        assert seen == ["inbound:ping"]


class TestTimeoutBecomesARecordedCause:
    def test_exhausted_retries_abort_with_timeout(self) -> None:
        orch, _ = orchestrator(*[TimeoutError()] * 10)
        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("ping", {})
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_the_cause_carries_detail_for_agreeing_a_result(self) -> None:
        """Both teams must agree a result; a bare failure is hard to agree on."""
        orch, _ = orchestrator(*[TimeoutError()] * 10)
        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("ping", {})
        assert "after 4 attempts" in excinfo.value.detail

    def test_a_recoverable_failure_does_not_abort(self) -> None:
        orch, _ = orchestrator(TimeoutError(), {"ok": True, "data": {}})
        assert orch.call_opponent("ping", {}).ok


class TestConfigAgreement:
    def test_advertises_the_digest_of_the_loaded_config(self) -> None:
        """The digest we advertise must be the one we are enforcing."""
        config = shipped()
        orch, transport = orchestrator({"ok": True, "data": {}})
        assert orch.agree_config(config) == config_sha256(config)
        assert transport.calls[0]["payload"]["config_sha256"] == config_sha256(config)

    def test_a_mismatch_aborts_rather_than_playing_on(self) -> None:
        orch, _ = orchestrator({"ok": False, "detail": "digest mismatch", "data": {}})
        with pytest.raises(MatchAborted) as excinfo:
            orch.agree_config(shipped())
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert "digest mismatch" in excinfo.value.detail

    def test_a_changed_config_changes_the_advertised_digest(self) -> None:
        config = shipped()
        orch, transport = orchestrator({"ok": True, "data": {}}, {"ok": True, "data": {}})
        first = orch.agree_config(config)
        config["world"]["map_area"] = "London"
        assert orch.agree_config(config) != first
