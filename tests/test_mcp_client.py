"""Tests for the outbound half of the peer."""

import dataclasses
import tomllib
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.mcp_client import (
    ClientSettings,
    OpponentClient,
    OpponentUnreachableError,
)

SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)


class FakeTransport:
    """Replays a scripted sequence of outcomes."""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "tool": tool, "payload": payload, "timeout": timeout})
        outcome = self._outcomes.pop(0) if self._outcomes else {"ok": True}
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


class TestHappyPath:
    def test_returns_the_response(self) -> None:
        client = OpponentClient(FakeTransport({"accepted": True}), SETTINGS)
        assert client.call("receive_move", {"move": "N"}) == {"accepted": True}

    def test_sends_to_the_configured_url_with_the_deadline(self) -> None:
        transport = FakeTransport({"ok": True})
        OpponentClient(transport, SETTINGS).call("ping", {})
        assert transport.calls[0]["url"] == "http://127.0.0.1:8801/mcp"
        assert transport.calls[0]["timeout"] == 30.0

    def test_succeeds_on_the_first_attempt(self) -> None:
        client = OpponentClient(FakeTransport({"ok": True}), SETTINGS)
        client.call("ping", {})
        assert client.attempts == 1


class TestRetryBudget:
    def test_recovers_from_a_transient_failure(self) -> None:
        transport = FakeTransport(TimeoutError(), {"ok": True})
        client = OpponentClient(transport, SETTINGS)
        assert client.call("ping", {}) == {"ok": True}
        assert client.attempts == 2

    def test_gives_up_once_the_budget_is_spent(self) -> None:
        transport = FakeTransport(*[TimeoutError()] * 10)
        client = OpponentClient(transport, SETTINGS)
        with pytest.raises(OpponentUnreachableError, match="after 4 attempts"):
            client.call("ping", {})
        assert client.attempts == 4

    def test_backs_off_between_attempts(self) -> None:
        slept: list[float] = []
        transport = FakeTransport(TimeoutError(), TimeoutError(), {"ok": True})
        settings = dataclasses.replace(SETTINGS, retry_backoff_sec=5.0)
        OpponentClient(transport, settings, sleep=slept.append).call("ping", {})
        assert slept == [5.0, 5.0]

    def test_does_not_sleep_after_the_final_attempt(self) -> None:
        slept: list[float] = []
        transport = FakeTransport(*[TimeoutError()] * 10)
        settings = dataclasses.replace(SETTINGS, retry_backoff_sec=5.0, max_retries=1)
        with pytest.raises(OpponentUnreachableError):
            OpponentClient(transport, settings, sleep=slept.append).call("ping", {})
        assert slept == [5.0]

    @pytest.mark.parametrize("failure", [TimeoutError(), ConnectionError(), OSError()])
    def test_transport_failures_are_retried(self, failure: Exception) -> None:
        transport = FakeTransport(failure, {"ok": True})
        assert OpponentClient(transport, SETTINGS).call("ping", {}) == {"ok": True}

    def test_a_logic_error_is_not_retried(self) -> None:
        """Only transport faults are transient; a bad payload is not."""
        transport = FakeTransport(ValueError("malformed"))
        with pytest.raises(ValueError, match="malformed"):
            OpponentClient(transport, SETTINGS).call("ping", {})


class TestRetryResendsTheSamePayload:
    def test_every_attempt_carries_identical_bytes(self) -> None:
        """A retry is never a chance to send a different move."""
        transport = FakeTransport(TimeoutError(), TimeoutError(), {"ok": True})
        payload = {"move": "N", "commit": "abc123"}
        OpponentClient(transport, SETTINGS).call("receive_move", payload)
        assert [c["payload"] for c in transport.calls] == [payload] * 3


class TestSettings:
    def test_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            SETTINGS.opponent_url = "x"  # type: ignore[misc]

    def test_empty_url_is_refused(self) -> None:
        with pytest.raises(ValueError, match="opponent_url must be set"):
            ClientSettings(opponent_url="")

    @pytest.mark.parametrize("timeout", [0, -1.0])
    def test_non_positive_timeout_is_refused(self, timeout: float) -> None:
        with pytest.raises(ValueError, match="response_timeout_sec"):
            ClientSettings(opponent_url="u", response_timeout_sec=timeout)

    def test_negative_retries_are_refused(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            ClientSettings(opponent_url="u", max_retries=-1)

    def test_defaults_follow_appendix_f(self) -> None:
        settings = ClientSettings(opponent_url="u")
        assert (settings.response_timeout_sec, settings.max_retries) == (30.0, 3)
        assert settings.retry_backoff_sec == 5.0

    def test_reads_the_shipped_private_config(self) -> None:
        path = Path(__file__).parents[1] / "config/thief/game.toml"
        private = tomllib.loads(path.read_text())
        assert ClientSettings.from_config(private["network"]).opponent_url.endswith("8801/mcp")

    def test_missing_opponent_url_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must define opponent_url"):
            ClientSettings.from_config({})
