"""Tests for the single-gateway orchestrator."""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.runtime.orchestrator import PROTOCOL_VERSION, MatchAborted, Orchestrator
from thief_agent.shared.config import config_sha256

SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)
TURN = {
    "step": 1,
    "sender": "police",
    "hint": "slipping away",
    "smell_grid": {"3,3": 0.9},
    "commit": "a" * 64,
    "timestamp": "2026-08-03T09:00:00+00:00",
}


def shipped() -> dict[str, Any]:
    text = (Path(__file__).parents[1] / "config/game.json").read_text()
    loaded: dict[str, Any] = json.loads(text)
    return loaded


class FakeTransport:
    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append({"tool": tool, "payload": payload})
        outcome = self._outcomes.pop(0) if self._outcomes else {"ok": True}
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


def orchestrator(*outcomes: object) -> tuple[Orchestrator, FakeTransport]:
    transport = FakeTransport(*outcomes)
    return Orchestrator(PeerInboxes(), OpponentClient(transport, SETTINGS)), transport


class TestSingleGateway:
    def test_inbound_reaches_the_mailboxes(self) -> None:
        orch, _ = orchestrator()
        assert orch.handle_inbound("receive_turn", TURN)["ok"] is True
        assert orch.inboxes.turns.get_nowait().step == 1

    def test_inbound_is_delegated_not_revalidated(self) -> None:
        """Two validators that disagree are worse than one."""
        orch, _ = orchestrator()
        assert orch.handle_inbound("receive_turn", None)["ok"] is False
        assert orch.inboxes.rejected

    def test_an_unknown_tool_is_refused(self) -> None:
        orch, _ = orchestrator()
        assert orch.handle_inbound("drop_tables", {})["ok"] is False

    def test_every_wire_tool_is_routed(self) -> None:
        orch, _ = orchestrator()
        for tool in ("negotiate", "receive_turn", "submit_audit", "receive_control"):
            assert "ok" in orch.handle_inbound(tool, {})

    def test_no_game_rule_lives_here(self) -> None:
        """It coordinates and does not decide."""
        import thief_agent.runtime.orchestrator as module

        source = Path(module.__file__ or "").read_text()
        for rule_word in ("legal_moves", "apply_move", "is_capture", "BOOK_SCORES"):
            assert rule_word not in source


class TestHeartbeat:
    def test_inbound_and_outbound_both_beat(self) -> None:
        orch, _ = orchestrator()
        orch.handle_inbound("receive_turn", TURN)
        orch.call_opponent("receive_turn", {})
        assert orch.heartbeats == ["inbound:receive_turn", "outbound:receive_turn"]

    def test_events_are_published(self) -> None:
        orch, _ = orchestrator()
        seen: list[str] = []
        orch.on_event = seen.append
        orch.handle_inbound("negotiate", {})
        assert seen == ["inbound:negotiate"]


class TestTimeoutBecomesARecordedCause:
    def test_exhausted_retries_abort_with_timeout(self) -> None:
        orch, _ = orchestrator(*[TimeoutError()] * 10)
        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("receive_turn", {})
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_the_cause_carries_detail_for_agreeing_a_result(self) -> None:
        """Both teams must agree a result; a bare failure is hard to agree on."""
        orch, _ = orchestrator(*[TimeoutError()] * 10)
        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("receive_turn", {})
        assert "after 4 attempts" in excinfo.value.detail

    def test_a_recoverable_failure_does_not_abort(self) -> None:
        orch, _ = orchestrator(TimeoutError(), {"ok": True})
        assert orch.call_opponent("receive_turn", {})["ok"] is True


class TestHandshakeChecks:
    def test_a_matching_protocol_and_opposite_role_passes(self) -> None:
        orch, _ = orchestrator()
        orch.check_handshake("police", PROTOCOL_VERSION)

    def test_a_protocol_mismatch_aborts(self) -> None:
        orch, _ = orchestrator()
        with pytest.raises(MatchAborted, match="protocol 0.9"):
            orch.check_handshake("police", "0.9")

    def test_a_duplicate_role_aborts(self) -> None:
        """Two peers claiming thief is a game with no pursuer."""
        orch, _ = orchestrator()
        with pytest.raises(MatchAborted, match="both peers claim"):
            orch.check_handshake("thief", PROTOCOL_VERSION)

    def test_an_unknown_role_aborts(self) -> None:
        orch, _ = orchestrator()
        with pytest.raises(MatchAborted, match="unknown role"):
            orch.check_handshake("referee", PROTOCOL_VERSION)

    def test_cop_is_not_a_valid_wire_role(self) -> None:
        """Our internal name; the wire says police."""
        orch, _ = orchestrator()
        with pytest.raises(MatchAborted, match="unknown role"):
            orch.check_handshake("cop", PROTOCOL_VERSION)

    def test_the_cause_is_recorded(self) -> None:
        orch, _ = orchestrator()
        with pytest.raises(MatchAborted) as excinfo:
            orch.check_handshake("thief", PROTOCOL_VERSION)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION


class TestConfigAgreement:
    def test_advertises_the_digest_of_the_loaded_config(self) -> None:
        """The digest we advertise must be the one we are enforcing."""
        config = shipped()
        orch, transport = orchestrator({"ok": True})
        assert orch.agree_config(config) == config_sha256(config)
        assert transport.calls[0]["payload"]["config_sha256"] == config_sha256(config)

    def test_it_negotiates_over_the_wire_tool(self) -> None:
        orch, transport = orchestrator({"ok": True})
        orch.agree_config(shipped())
        assert transport.calls[0]["tool"] == "negotiate"

    def test_a_mismatch_aborts_rather_than_playing_on(self) -> None:
        orch, _ = orchestrator({"ok": False, "detail": "digest mismatch"})
        with pytest.raises(MatchAborted) as excinfo:
            orch.agree_config(shipped())
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert "digest mismatch" in excinfo.value.detail

    def test_a_changed_config_changes_the_advertised_digest(self) -> None:
        config = shipped()
        orch, _ = orchestrator({"ok": True}, {"ok": True})
        first = orch.agree_config(config)
        config["world"]["map_area"] = "London"
        assert orch.agree_config(config) != first
