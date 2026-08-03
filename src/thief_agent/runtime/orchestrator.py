"""The single gateway to every subsystem.

Appendix E rule 3: the orchestrator is the **only** entry point to the
subsystems, and peripheral modules never reference one another. That is not
architectural taste — a decision module that reaches directly into the MCP
connector cannot be replaced without touching both, and the rulebook grades
the ability to swap one component in isolation.

It **coordinates and does not decide**. No game rule lives here; move choice
belongs to the strategy module, legality to the domain layer, transport to the
connector. What lives here is the wiring between them and the conversion of a
subsystem failure into a recorded outcome.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.outcome import TechnicalLoss
from ..infra.mcp_client import OpponentClient, OpponentUnreachableError
from ..infra.tools import ToolResult, ToolSurface
from ..shared.config import config_sha256


@dataclass(frozen=True, slots=True)
class MatchAborted(Exception):
    """A subsystem failure ended the sub-game.

    Carries the cause rather than only the fact. Both teams must **agree** a
    result before either may report it, and "technical loss" with no cause is
    far harder to agree on than "timeout at step 12" — so the cause is
    recorded at the point it is known, not reconstructed afterwards.
    """

    cause: TechnicalLoss
    detail: str = ""


@dataclass
class Orchestrator:
    """Coordinates the subsystems behind one entry point."""

    tools: ToolSurface
    client: OpponentClient
    on_event: Callable[[str], None] = lambda _: None
    heartbeats: list[str] = field(default_factory=list)

    def beat(self, what: str) -> None:
        """Record liveness so the watchdog can tell stalled from slow."""
        self.heartbeats.append(what)
        self.on_event(what)

    def handle_inbound(self, tool: str, payload: object) -> ToolResult:
        """Route an opponent call through validation.

        Delegates wholesale: the orchestrator does not re-validate, because two
        validators disagreeing is worse than one.
        """
        self.beat(f"inbound:{tool}")
        return self.tools.dispatch(tool, payload)

    def call_opponent(self, tool: str, payload: dict[str, object]) -> ToolResult:
        """Call the opponent, converting exhaustion into a recorded abort.

        Raises:
            MatchAborted: with ``TechnicalLoss.TIMEOUT`` once the retry budget
                is spent. The deadline is a failure, not a reason to wait.
        """
        self.beat(f"outbound:{tool}")
        try:
            raw = self.client.call(tool, dict(payload))
        except OpponentUnreachableError as exc:
            raise MatchAborted(TechnicalLoss.TIMEOUT, str(exc)) from exc
        return ToolResult(
            ok=bool(raw.get("ok", False)),
            detail=str(raw.get("detail", "")),
            data=dict(raw.get("data", {})),
        )

    def agree_config(self, config: dict[str, object]) -> str:
        """Exchange config digests, refusing to play on any mismatch.

        The digest is computed from the **loaded** configuration rather than
        re-hashed from a file, so the value advertised is provably the one this
        peer is enforcing. Advertising a digest we are not playing by would be
        indistinguishable from cheating at audit.

        Raises:
            MatchAborted: with ``TechnicalLoss.ILLEGAL_ACTION`` on mismatch.
        """
        ours = config_sha256(config)
        self.beat("negotiate_config")
        reply = self.call_opponent("negotiate_config", {"config_sha256": ours})
        if not reply.ok:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, reply.detail)
        return ours
