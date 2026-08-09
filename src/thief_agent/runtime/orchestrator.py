"""The single gateway to every subsystem.

Appendix E rule 3: the orchestrator is the **only** entry point to the
subsystems, and no peripheral subsystem *drives* another — none of them calls
into another to make something happen; that traffic goes through here. That is
not architectural taste — a decision module that reaches directly into the MCP
connector cannot be replaced without touching both, and the rulebook grades
the ability to swap one component in isolation.

What the rule does not forbid is a passive dependency on a lower layer: the
strategy, ui and infra modules all read shared vocabulary out of ``domain``
and ``shared``, and ``ui/banner.py`` reads a ceremony's state to decide whether
the window may still accept a click. Those are one-directional reads with no
control flow, and none of them is a route around this gateway. Stating the rule
as "peripheral modules never reference one another" overstates it, and an
overstated rule is one that quietly stops being checked.

It **coordinates and does not decide**. No game rule lives here; move choice
belongs to the strategy module, legality to the domain layer, transport to the
connector. What lives here is the wiring between them and the conversion of a
subsystem failure into a recorded outcome.

Inbound traffic goes to :class:`~..infra.inboxes.PeerInboxes`, which is the
surface an opponent actually calls. The orchestrator routes into those
mailboxes; it does not re-validate, because two validators that disagree are
worse than one.

The methods themselves live in the ``orchestrator_*`` siblings and are mixed in
below. They are mixins rather than helper objects on purpose: ``self.client``
is re-pointed when a tunnel moves and ``self.beat`` feeds the watchdog, so both
have to be read off the live orchestrator at call time. A helper that captured
either at construction would keep calling a dead address and stop feeding the
watchdog, with every unit test still green.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import OpponentClient
from .orchestrator_book import (
    CONFIG_TIMEOUT_SEC,
    GREETING_TIMEOUT_SEC,
    PROTOCOL_VERSION,
    RESULT_TIMEOUT_SEC,
    SCENT_TIMEOUT_SEC,
)
from .orchestrator_config import ConfigMixin
from .orchestrator_core import MatchAborted, OrchestratorCore
from .orchestrator_result import ResultMixin
from .orchestrator_rotation import RotationMixin
from .orchestrator_scent import ScentMixin

__all__ = [
    "CONFIG_TIMEOUT_SEC",
    "GREETING_TIMEOUT_SEC",
    "PROTOCOL_VERSION",
    "RESULT_TIMEOUT_SEC",
    "SCENT_TIMEOUT_SEC",
    "MatchAborted",
    "Orchestrator",
]


@dataclass
class Orchestrator(RotationMixin, ConfigMixin, ScentMixin, ResultMixin, OrchestratorCore):
    """Coordinates the subsystems behind one entry point."""

    inboxes: PeerInboxes
    client: OpponentClient
    role: str = "thief"
    on_event: Callable[[str], None] = lambda _: None
    heartbeats: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Route the connector's liveness into this orchestrator's heartbeats.

        Appendix E rule 3 makes this the only entry point to the subsystems, so
        it is also the only place that can join them up. Without this, a client
        retrying against a dead tunnel is silent for longer than the watchdog's
        patience, and the watchdog reports a stall over a recovery that was
        working exactly as designed.
        """
        self.client.on_attempt = lambda tool: self.beat(f"attempt:{tool}")
