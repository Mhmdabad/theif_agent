"""This peer's FastMCP server.

Each agent is **simultaneously** a server and a client: it exposes tools the
opponent calls, and calls the opponent's tools in turn. There is no strong side
and no weak side, and no central server between them.

The server binds ``0.0.0.0`` from the outset. League play requires exposure to
the public internet through a tunnel, and binding the loopback address would
mean the tunnel could not reach it — a change that would otherwise be
discovered at the point of first contact with another team.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from fastmcp import FastMCP

from .inboxes import PeerInboxes, register

F = TypeVar("F", bound=Callable[..., object])

BIND_HOST = "0.0.0.0"  # noqa: S104 - deliberate: a tunnel must be able to reach us
"""Bound so a tunnel can expose this server. See module docstring."""

DEFAULT_TRANSPORT = "http"


SERVER_NAME = __name__.split(".")[0].replace("_", "-")
"""Names this peer in the MCP handshake. Derived, so the two agents differ."""


class ToolHost(Protocol):
    """The slice of ``FastMCP`` this module depends on.

    Declared as a protocol so the server can be assembled and inspected in
    tests without binding a socket. Starting a real listener to assert that a
    tool was registered would make the suite slow and flaky for no gain.

    :class:`FastMCP` satisfies it. The protocol stays because it is the seam
    the retry and deadline tests need, and because a concrete class in a
    signature would make every one of them start a server.
    """

    def tool(self, fn: F) -> F: ...
    def run(self, *, transport: str, host: str, port: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """How this peer's server is exposed."""

    port: int
    host: str = BIND_HOST
    transport: str = DEFAULT_TRANSPORT

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError(f"port must be 1..65535, got {self.port}")

    @classmethod
    def from_config(cls, network: dict[str, Any]) -> "ServerSettings":
        """Read ``my_port`` from the private per-peer config.

        The port is local and not negotiated, so it comes from the private
        TOML rather than the signed shared file.
        """
        if "my_port" not in network:
            raise ValueError("private config [network] must define my_port")
        return cls(port=int(network["my_port"]))


def build(inboxes: PeerInboxes, name: str = SERVER_NAME) -> FastMCP:
    """A real FastMCP server with this peer's four tools registered.

    Assembling and running are separate on purpose. Everything worth checking
    about the server — that all four tools exist, under the names and parameter
    names the opponent will use, and that they route to our inboxes — is true
    before a socket is bound, and can be checked with FastMCP's in-memory
    client. A test that had to start a listener to learn any of it would be
    slower, flakier, and no more convincing.
    """
    host = FastMCP(name)
    register(host, inboxes)
    return host


def serve(host: ToolHost, settings: ServerSettings) -> None:
    """Run the server until it is stopped.

    Blocks. The caller owns the thread this runs on, because an agent that
    started its own is an agent whose shutdown nobody can reason about.
    """
    host.run(transport=settings.transport, host=settings.host, port=settings.port)
