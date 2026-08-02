"""Tests for this peer's server settings and startup."""

import dataclasses
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest

from thief_agent.infra.mcp_server import (
    BIND_HOST,
    DEFAULT_TRANSPORT,
    ServerSettings,
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
        serve(host, ServerSettings(port=8802))
        assert host.calls == [{"transport": "http", "host": "0.0.0.0", "port": 8802}]  # noqa: S104


class TestSettings:
    def test_is_frozen(self) -> None:
        settings = ServerSettings(port=8802)
        with pytest.raises(dataclasses.FrozenInstanceError):
            settings.port = 1  # type: ignore[misc]

    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_rejects_an_impossible_port(self, port: int) -> None:
        with pytest.raises(ValueError, match="port must be"):
            ServerSettings(port=port)

    @pytest.mark.parametrize("port", [1, 8802, 65535])
    def test_accepts_the_valid_range(self, port: int) -> None:
        assert ServerSettings(port=port).port == port


class TestFromConfig:
    def test_reads_my_port(self) -> None:
        assert ServerSettings.from_config({"my_port": 8802}).port == 8802

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
