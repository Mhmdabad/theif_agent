"""The tools this peer exposes to its opponent.

This is the whole inbound surface. Everything arriving here comes from an
agent we do not control and have no reason to trust, so each tool returns a
structured result rather than raising across the wire, and none of them mutate
game state directly — they hand work to the runtime, which decides.

The tool set is deliberately small. Every endpoint is another thing an
opponent can probe, and another thing that must behave identically on both
sides for a match to be reconcilable at audit.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "1.0"
"""Bumped when the wire contract changes. Exchanged during the handshake."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What every tool returns.

    A rejection is a *result*, not an exception. An exception crossing the wire
    tells the opponent only that something broke; a structured refusal tells
    them what and why, which is what makes a disputed result reconcilable
    rather than a stand-off.
    """

    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "data": self.data}

    @classmethod
    def accept(cls, **data: object) -> "ToolResult":
        return cls(ok=True, data=dict(data))

    @classmethod
    def refuse(cls, detail: str) -> "ToolResult":
        return cls(ok=False, detail=detail)


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    """Who we are, as announced in the handshake."""

    group_id: str
    role: str
    protocol_version: str = PROTOCOL_VERSION


class ToolSurface:
    """The inbound tools, independent of any MCP framework.

    Kept free of FastMCP so the contract can be tested directly. Registration
    with a server is a separate, thin step.
    """

    def __init__(
        self,
        identity: PeerIdentity,
        config_digest: str,
        state_digest: Callable[[], str],
    ) -> None:
        self._identity = identity
        self._config_digest = config_digest
        self._state_digest = state_digest

    def ping(self) -> ToolResult:
        """Liveness probe. Carries no game state deliberately."""
        return ToolResult.accept(protocol_version=self._identity.protocol_version)

    def handshake(self, group_id: str, role: str, protocol_version: str) -> ToolResult:
        """Exchange identity and refuse a protocol mismatch.

        A version mismatch is refused before a match starts rather than
        discovered mid-turn, where it would present as arbitrary rejections.
        """
        if protocol_version != self._identity.protocol_version:
            return ToolResult.refuse(
                f"protocol {protocol_version} != ours {self._identity.protocol_version}"
            )
        if role == self._identity.role:
            return ToolResult.refuse(f"both peers claim the role {role!r}")
        return ToolResult.accept(
            group_id=self._identity.group_id,
            role=self._identity.role,
            protocol_version=self._identity.protocol_version,
        )

    def negotiate_config(self, config_sha256: str) -> ToolResult:
        """Compare the opponent's signed config digest with ours.

        A mismatch means the two peers would enforce different physics, so the
        only safe answer is to refuse to play. Failing here costs a match that
        was never playable; failing to fail here costs a match that both sides
        thought they played correctly.
        """
        if config_sha256 != self._config_digest:
            return ToolResult.refuse(
                f"config digest mismatch: theirs {config_sha256[:12]}… "
                f"ours {self._config_digest[:12]}… — refusing to play"
            )
        return ToolResult.accept(config_sha256=self._config_digest)

    def get_state_digest(self) -> ToolResult:
        """Our view of the board, for cross-checking.

        A digest rather than the state itself: the opponent must not learn our
        position, only whether our views agree.
        """
        return ToolResult.accept(state_digest=self._state_digest())
