"""Tests for this peer's server settings and startup."""

import asyncio
import dataclasses
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastmcp import Client, FastMCP

from thief_agent.infra.inboxes import TOOL_NAMES, PeerInboxes
from thief_agent.infra.mcp_server import (
    BIND_HOST,
    DEFAULT_TRANSPORT,
    SERVER_NAME,
    ServerSettings,
    build,
    serve,
)

F = TypeVar("F", bound=Callable[..., object])


class RecordingHost:
    """A stand-in for FastMCP that records how it was run."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def tool(self, fn: F) -> F:
        return fn

    def run(self, *, transport: str, host: str, port: int) -> None:
        self.calls.append({"transport": transport, "host": host, "port": port})


class TestBinding:
    def test_binds_all_interfaces_so_a_tunnel_can_reach_it(self) -> None:
        """Loopback would work locally and fail on first contact with a team."""
        assert BIND_HOST == "0.0.0.0"  # noqa: S104

    def test_transport_is_http(self) -> None:
        assert DEFAULT_TRANSPORT == "http"

    def test_serve_passes_the_settings_through(self) -> None:
        host = RecordingHost()
        serve(host, ServerSettings(port=8801))
        assert host.calls == [{"transport": "http", "host": "0.0.0.0", "port": 8801}]  # noqa: S104


class TestSettings:
    def test_is_frozen(self) -> None:
        settings = ServerSettings(port=8801)
        with pytest.raises(dataclasses.FrozenInstanceError):
            settings.port = 1  # type: ignore[misc]

    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_rejects_an_impossible_port(self, port: int) -> None:
        with pytest.raises(ValueError, match="port must be"):
            ServerSettings(port=port)

    @pytest.mark.parametrize("port", [1, 8801, 65535])
    def test_accepts_the_valid_range(self, port: int) -> None:
        assert ServerSettings(port=port).port == port


class TestFromConfig:
    def test_reads_my_port(self) -> None:
        assert ServerSettings.from_config({"my_port": 8801}).port == 8801

    def test_missing_my_port_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must define my_port"):
            ServerSettings.from_config({})

    def test_reads_the_shipped_private_config(self) -> None:
        path = Path(__file__).parents[1] / "config/thief/game.toml"
        private = tomllib.loads(path.read_text())
        settings = ServerSettings.from_config(private["network"])
        assert settings.port == 8802

    def test_our_port_differs_from_the_cops(self) -> None:
        """Both peers run side by side during local development."""
        path = Path(__file__).parents[1] / "config/thief/game.toml"
        private = tomllib.loads(path.read_text())
        assert "8801" in private["network"]["opponent_url"]
        assert private["network"]["my_port"] == 8802


class TestARealFastMcpServer:
    """The first code in this project that builds an actual MCP server."""

    @staticmethod
    def inboxes() -> PeerInboxes:
        return PeerInboxes()

    @staticmethod
    async def tools_of(host: FastMCP) -> list[str]:
        async with Client(host) as client:
            return sorted(tool.name for tool in await client.list_tools())

    def test_it_registers_exactly_the_four_protocol_tools(self) -> None:
        host = build(self.inboxes())
        assert asyncio.run(self.tools_of(host)) == sorted(TOOL_NAMES)

    def test_the_names_are_the_ones_the_opponent_will_call(self) -> None:
        """A rename here fails at first contact with another team."""
        assert sorted(TOOL_NAMES) == [
            "negotiate",
            "receive_control",
            "receive_turn",
            "submit_audit",
        ]

    def test_a_real_call_reaches_our_inboxes(self) -> None:
        """End to end through FastMCP: client → server → PeerInboxes → back."""
        inboxes = self.inboxes()

        async def call() -> dict[str, object]:
            async with Client(build(inboxes)) as client:
                result = await client.call_tool(
                    "receive_control", {"message": {"kind": "status", "sender": "thief"}}
                )
                return dict(result.data)

        answer = asyncio.run(call())
        assert answer["ok"] is True

    def test_the_parameter_name_is_message_not_something_else(self) -> None:
        """The reference sends {"message": ...}; a mismatch fails at first contact."""

        async def call() -> dict[str, object]:
            async with Client(build(self.inboxes())) as client:
                result = await client.call_tool(
                    "negotiate", {"message": {"sender": "thief", "terms": {}}}
                )
                return dict(result.data)

        assert "ok" in asyncio.run(call())

    def test_submit_audit_takes_payload_rather_than_message(self) -> None:
        """The one tool the reference names differently. Pinned deliberately."""

        async def call() -> dict[str, object]:
            async with Client(build(self.inboxes())) as client:
                result = await client.call_tool(
                    "submit_audit", {"payload": {"sender": "thief", "nonces": {}}}
                )
                return dict(result.data)

        assert "ok" in asyncio.run(call())

    def test_a_refusal_comes_back_rather_than_an_exception(self) -> None:
        """The opponent gets our answer, not a transport error."""

        async def call() -> dict[str, object]:
            async with Client(build(self.inboxes())) as client:
                result = await client.call_tool("receive_control", {"message": {"kind": "nope"}})
                return dict(result.data)

        answer = asyncio.run(call())
        assert answer["ok"] is False

    def test_the_server_is_named_for_this_agent(self) -> None:
        assert SERVER_NAME == "thief-agent"

    def test_building_does_not_bind_a_socket(self) -> None:
        """Assembling and running are separate, so tests never listen."""
        build(self.inboxes())
        build(self.inboxes())
