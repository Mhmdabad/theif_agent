"""Tests for the outbound half of the peer."""

import dataclasses
import tomllib
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.mcp_client import (
    OPPONENT_URL_ENV,
    ClientSettings,
    OpponentClient,
    OpponentUnreachableError,
)

SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)
REMOTE = "https://opponent-c3d4.ngrok-free.app"


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

    def test_default_backoff_uses_wall_clock_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr("thief_agent.infra.mcp_client.time.sleep", slept.append)
        transport = FakeTransport(TimeoutError(), {"ok": True})
        settings = dataclasses.replace(SETTINGS, retry_backoff_sec=5.0)
        OpponentClient(transport, settings).call("ping", {})
        assert slept == [5.0]

    def test_does_not_sleep_after_the_final_attempt(self) -> None:
        slept: list[float] = []
        transport = FakeTransport(*[TimeoutError()] * 10)
        settings = dataclasses.replace(SETTINGS, retry_backoff_sec=5.0, max_retries=1)
        with pytest.raises(OpponentUnreachableError):
            OpponentClient(transport, settings, sleep=slept.append).call("ping", {})
        assert slept == [5.0]


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
        settings = ClientSettings(opponent_url=REMOTE)
        assert (settings.response_timeout_sec, settings.max_retries) == (30.0, 3)
        assert settings.retry_backoff_sec == 5.0

    def test_it_appends_the_endpoint_a_tunnel_never_prints(self) -> None:
        """A tunnel hands out a base address; the opponent serves at ``/mcp``.

        Doing it here means the URL that gets pasted around is the one the
        tunnel actually printed, which removes the likeliest transcription
        error in the whole handshake.
        """
        assert ClientSettings(opponent_url=REMOTE).opponent_url == f"{REMOTE}/mcp"

    def test_it_refuses_a_url_it_could_never_call(self) -> None:
        with pytest.raises(ValueError, match="must use one of"):
            ClientSettings(opponent_url="opponent.ngrok-free.app")

    def test_reads_the_shipped_private_config(self) -> None:
        path = Path(__file__).parents[1] / "config/thief/game.toml"
        private = tomllib.loads(path.read_text())
        settings = ClientSettings.from_config(private["network"], environ={})
        assert settings.opponent_url.endswith("8801/mcp")

    def test_missing_opponent_url_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must define opponent_url"):
            ClientSettings.from_config({}, environ={})


class TestPointingAtTheOpponentsTunnel:
    def test_the_environment_overrides_the_committed_file(self) -> None:
        """League play is one exported variable, not an edit to revert later."""
        settings = ClientSettings.from_config(
            {"opponent_url": "http://127.0.0.1:8801/mcp"}, environ={OPPONENT_URL_ENV: REMOTE}
        )
        assert settings.opponent_url == f"{REMOTE}/mcp"

    def test_the_override_alone_is_enough(self) -> None:
        """A config with no ``opponent_url`` is fine if the environment has one."""
        assert ClientSettings.from_config({}, environ={OPPONENT_URL_ENV: REMOTE}).opponent_url == (
            f"{REMOTE}/mcp"
        )

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_a_blank_override_falls_through_to_the_file(self, blank: str) -> None:
        """An exported-but-empty variable is not an instruction to play nobody."""
        settings = ClientSettings.from_config(
            {"opponent_url": "http://127.0.0.1:8801/mcp"}, environ={OPPONENT_URL_ENV: blank}
        )
        assert settings.opponent_url.endswith("8801/mcp")

    def test_a_bad_override_raises_rather_than_falling_back(self) -> None:
        """Falling back would play localhost against a team who is not there."""
        with pytest.raises(ValueError):
            ClientSettings.from_config(
                {"opponent_url": "http://127.0.0.1:8801/mcp"},
                environ={OPPONENT_URL_ENV: "ftp://opponent"},
            )

    def test_it_reads_the_real_environment_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(OPPONENT_URL_ENV, REMOTE)
        assert ClientSettings.from_config({}).opponent_url == f"{REMOTE}/mcp"

    def test_the_committed_file_still_points_at_loopback(self) -> None:
        """Checking out this repo and running both agents must need no setup.

        The opponent's address is ephemeral — a free-tier tunnel issues a new
        one every restart — and it is theirs, not ours. A repository full of
        other teams' expired addresses is a record of nothing.
        """
        path = Path(__file__).parents[1] / "config/thief/game.toml"
        private = tomllib.loads(path.read_text())
        assert private["network"]["opponent_url"].startswith("http://127.0.0.1:")


class MutatingTransport:
    """An opponent whose transport annotates the payload it was handed.

    Not adversarial fiction: a middleware that stamps a trace id, or a caller
    reusing one dict across calls, produces exactly this.
    """

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.seen: list[dict[str, Any]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.seen.append(dict(payload))
        payload["move"] = "TAMPERED"
        payload.setdefault("trace", []).append(len(self.seen))
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError("no answer")
        return {"ok": True}


class TestARetryReSendsBytesNotAnIntention:
    def test_every_attempt_carries_the_original_payload(self) -> None:
        transport = MutatingTransport(failures=2)
        OpponentClient(transport, SETTINGS).call("receive_turn", {"move": "N", "step": 4})
        assert transport.seen == [{"move": "N", "step": 4}] * 3

    def test_a_caller_mutating_between_attempts_cannot_change_the_action(self) -> None:
        """The guarantee has to hold for call sites not yet written.

        Passing the caller's dict down the loop would look identical and be
        weaker — attempt two would become a *different action*, which is the
        fraud Commit-Reveal exists to expose.
        """
        payload = {"move": "N", "commit": "a" * 64}
        transport = FakeTransport(TimeoutError(), {"ok": True})
        client = OpponentClient(transport, SETTINGS)

        original = dict(payload)
        payload["move"] = "S"  # the caller changes its mind mid-flight
        client.call("receive_turn", original)
        assert [c["payload"] for c in transport.calls] == [original] * 2

    def test_the_transport_is_handed_a_fresh_object_each_attempt(self) -> None:
        """Two attempts sharing one object is one mutation away from divergence."""
        transport = MutatingTransport(failures=1)
        OpponentClient(transport, SETTINGS).call("receive_turn", {"move": "E"})
        assert transport.seen[0] == transport.seen[1] == {"move": "E"}

    def test_it_records_a_digest_of_what_was_sent(self) -> None:
        """Evidence at audit that the retry changed nothing."""
        client = OpponentClient(FakeTransport(TimeoutError(), {"ok": True}), SETTINGS)
        client.call("receive_turn", {"move": "N"})
        client.call("receive_turn", {"move": "N"})
        tools = [tool for tool, _ in client.sent]
        digests = [digest for _, digest in client.sent]
        assert tools == ["receive_turn", "receive_turn"]
        assert digests[0] == digests[1]
        assert len(client.sent) == 2  # two calls, four attempts

    def test_key_order_does_not_change_the_digest(self) -> None:
        """Canonical bytes, the same rule that makes config_sha256 agree."""
        client = OpponentClient(FakeTransport(), SETTINGS)
        client.call("receive_turn", {"move": "N", "step": 1})
        client.call("receive_turn", {"step": 1, "move": "N"})
        assert client.sent[0][1] == client.sent[1][1]

    def test_an_unserialisable_payload_fails_before_the_first_attempt(self) -> None:
        """A message we cannot reproduce is one we cannot prove we sent once."""
        transport = FakeTransport()
        with pytest.raises(TypeError):
            OpponentClient(transport, SETTINGS).call("receive_turn", {"move": {1, 2}})
        assert transport.calls == []


class TestOnlyTransportFailuresAreRetried:
    @pytest.mark.parametrize(
        "failure",
        [TimeoutError("no answer"), ConnectionError("refused"), OSError("network down")],
    )
    def test_a_transport_fault_is_transient_and_retried(self, failure: Exception) -> None:
        transport = FakeTransport(failure, {"ok": True})
        assert OpponentClient(transport, SETTINGS).call("receive_turn", {}) == {"ok": True}

    @pytest.mark.parametrize(
        "failure",
        [ValueError("malformed"), KeyError("missing"), RuntimeError("bug")],
    )
    def test_anything_else_is_a_bug_and_is_not_retried(self, failure: Exception) -> None:
        """Retrying a logic error sends the same broken message four times.

        It cannot succeed, and it spends the deadline budget discovering that.
        """
        transport = FakeTransport(failure)
        with pytest.raises(type(failure)):
            OpponentClient(transport, SETTINGS).call("receive_turn", {})
        assert len(transport.calls) == 1
