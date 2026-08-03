"""Tests for the inbound tool surface."""

import dataclasses

import pytest

from thief_agent.infra.tools import (
    PROTOCOL_VERSION,
    PeerIdentity,
    ToolResult,
    ToolSurface,
)

OURS = PeerIdentity(group_id="s82kma9e", role="thief")
CONFIG_DIGEST = "a" * 64


def surface(state: str = "deadbeef") -> ToolSurface:
    return ToolSurface(OURS, CONFIG_DIGEST, lambda: state)


class TestToolResult:
    def test_accept_is_ok(self) -> None:
        assert ToolResult.accept(x=1).ok

    def test_refuse_carries_a_reason(self) -> None:
        result = ToolResult.refuse("nope")
        assert not result.ok
        assert result.detail == "nope"

    def test_serialises_to_a_plain_dict(self) -> None:
        assert ToolResult.accept(x=1).as_dict() == {"ok": True, "detail": "", "data": {"x": 1}}

    def test_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            ToolResult(ok=True).ok = False  # type: ignore[misc]


class TestPing:
    def test_is_ok(self) -> None:
        assert surface().ping().ok

    def test_carries_no_game_state(self) -> None:
        """A liveness probe must not leak position or belief."""
        assert set(surface().ping().data) == {"protocol_version"}


class TestHandshake:
    def test_accepts_a_matching_protocol_and_opposite_role(self) -> None:
        result = surface().handshake("them", "cop", PROTOCOL_VERSION)
        assert result.ok
        assert result.data["role"] == "thief"

    def test_refuses_a_protocol_mismatch(self) -> None:
        """Caught before a match rather than mid-turn as odd rejections."""
        result = surface().handshake("them", "cop", "0.9")
        assert not result.ok
        assert "protocol 0.9" in result.detail

    def test_refuses_a_duplicate_role(self) -> None:
        result = surface().handshake("them", "thief", PROTOCOL_VERSION)
        assert not result.ok
        assert "both peers claim" in result.detail

    def test_announces_our_group_id(self) -> None:
        assert surface().handshake("them", "cop", PROTOCOL_VERSION).data["group_id"] == "s82kma9e"


class TestNegotiateConfig:
    def test_accepts_an_identical_digest(self) -> None:
        assert surface().negotiate_config(CONFIG_DIGEST).ok

    def test_refuses_a_mismatch(self) -> None:
        """Different digests mean the two peers enforce different physics."""
        result = surface().negotiate_config("b" * 64)
        assert not result.ok
        assert "refusing to play" in result.detail

    def test_refusal_shows_both_digests_truncated(self) -> None:
        detail = surface().negotiate_config("b" * 64).detail
        assert "bbbbbbbbbbbb" in detail
        assert "aaaaaaaaaaaa" in detail

    def test_a_single_character_difference_is_refused(self) -> None:
        assert not surface().negotiate_config("a" * 63 + "b").ok


class TestStateDigest:
    def test_returns_the_digest(self) -> None:
        assert surface("cafe").get_state_digest().data["state_digest"] == "cafe"

    def test_returns_a_digest_not_the_state(self) -> None:
        """The opponent learns whether views agree, never our position."""
        data = surface().get_state_digest().data
        assert set(data) == {"state_digest"}

    def test_is_read_afresh_each_call(self) -> None:
        views = iter(["one", "two"])
        tools = ToolSurface(OURS, CONFIG_DIGEST, lambda: next(views))
        assert tools.get_state_digest().data["state_digest"] == "one"
        assert tools.get_state_digest().data["state_digest"] == "two"


class TestSurfaceIsSmall:
    def test_only_the_agreed_tools_are_exposed(self) -> None:
        """Every endpoint is another thing an opponent can probe.

        ``dispatch`` is the single validated entry point rather than a fifth
        tool: the opponent reaches the four tools only through it.
        """
        public = {n for n in dir(ToolSurface) if not n.startswith("_")}
        assert public == {
            "dispatch",
            "ping",
            "handshake",
            "negotiate_config",
            "get_state_digest",
        }

    def test_no_tool_mutates_state_directly(self) -> None:
        tools = surface()
        before = tools.get_state_digest().data["state_digest"]
        tools.ping()
        tools.handshake("them", "cop", PROTOCOL_VERSION)
        tools.negotiate_config(CONFIG_DIGEST)
        assert tools.get_state_digest().data["state_digest"] == before
