"""Stage 2 resilience: the three failures that end matches.

The unit tests prove each mechanism in isolation. These prove the three
scenarios the rulebook names — an illegal transition, an opponent that dies
mid-turn, and a frozen loop — reach a **controlled terminal state with a
recorded cause**, rather than hanging.

That distinction is the whole point of Stage 2. A hang produces no error, no
result and no story to tell an opponent; a technical loss with a named cause
can be agreed and reported. Both score zero on the board, but only one of them
can be closed out.
"""

import pytest

from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.tools import PeerIdentity, ToolSurface
from thief_agent.runtime.deadline import DeadlineExpiredError, DeadlineTracker
from thief_agent.runtime.orchestrator import MatchAborted, Orchestrator
from thief_agent.runtime.scheduler import OutOfTurnError, TurnScheduler
from thief_agent.runtime.state_machine import (
    GamePhaseMachine,
    IllegalTransitionError,
    Phase,
)
from thief_agent.runtime.watchdog import Watchdog, WatchdogVerdict

SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class DeadTransport:
    """An opponent that stopped responding mid-turn."""

    def __init__(self, alive_calls: int = 0) -> None:
        self.remaining = alive_calls
        self.calls = 0

    def call(
        self, url: str, tool: str, payload: dict[str, object], timeout: float
    ) -> dict[str, object]:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            return {"ok": True, "data": {}}
        raise ConnectionError("peer went away")


def orchestrator(transport: DeadTransport) -> Orchestrator:
    tools = ToolSurface(PeerIdentity("s82kma9e", "thief"), "a" * 64, lambda: "digest")
    return Orchestrator(tools, OpponentClient(transport, SETTINGS))


class TestIllegalTransition:
    def test_it_raises_rather_than_stalling(self) -> None:
        machine = GamePhaseMachine()
        with pytest.raises(IllegalTransitionError):
            machine.to(Phase.AWAITING_REVEAL)

    def test_the_phase_is_unchanged_after_a_refusal(self) -> None:
        """A rejected transition must not leave the machine half-moved."""
        machine = GamePhaseMachine()
        with pytest.raises(IllegalTransitionError):
            machine.to(Phase.AWAITING_REVEAL)
        assert machine.phase is Phase.WAITING_FOR_OPPONENT

    def test_acting_out_of_turn_raises_too(self) -> None:
        with pytest.raises(OutOfTurnError):
            TurnScheduler().record("thief")

    def test_the_machine_can_still_abort_cleanly_afterwards(self) -> None:
        machine = GamePhaseMachine()
        with pytest.raises(IllegalTransitionError):
            machine.to(Phase.VERIFYING)
        assert machine.abort("gave up") is Phase.TECHNICAL_LOSS


class TestOpponentKilledMidTurn:
    def test_the_retry_budget_is_spent_then_the_match_aborts(self) -> None:
        transport = DeadTransport()
        with pytest.raises(MatchAborted) as excinfo:
            orchestrator(transport).call_opponent("ping", {})
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT
        assert transport.calls == 4

    def test_the_abort_carries_a_cause_that_can_be_agreed(self) -> None:
        """A hang has no story; a named cause can be reported and agreed."""
        with pytest.raises(MatchAborted) as excinfo:
            orchestrator(DeadTransport()).call_opponent("ping", {})
        assert "after 4 attempts" in excinfo.value.detail

    def test_dying_partway_through_still_terminates(self) -> None:
        transport = DeadTransport(alive_calls=1)
        orch = orchestrator(transport)
        assert orch.call_opponent("ping", {}).ok
        with pytest.raises(MatchAborted):
            orch.call_opponent("ping", {})

    def test_the_phase_machine_can_record_the_loss(self) -> None:
        machine = GamePhaseMachine()
        machine.to(Phase.COMPUTING_MOVE)
        machine.to(Phase.COMMITTING)
        machine.to(Phase.AWAITING_REVEAL)
        assert machine.abort("opponent gone") is Phase.TECHNICAL_LOSS
        assert machine.is_terminal


class TestWatchdogFreeze:
    def test_a_frozen_loop_shuts_down_controlled(self) -> None:
        clock = FakeClock()
        events: list[str] = []
        dog = Watchdog(
            timeout_sec=60.0,
            clock=clock,
            persist_state=lambda: events.append("persist"),
            shutdown=lambda: events.append("shutdown"),
        )
        clock.advance(61.0)
        assert dog.check() is WatchdogVerdict.SHUTDOWN
        assert events == ["persist", "shutdown"]

    def test_state_is_persisted_before_the_process_stops(self) -> None:
        """A recoverable sub-game is worth more than a crashed one."""
        clock = FakeClock()
        events: list[str] = []
        dog = Watchdog(
            timeout_sec=10.0,
            clock=clock,
            persist_state=lambda: events.append("persist"),
            shutdown=lambda: events.append("shutdown"),
        )
        clock.advance(999.0)
        dog.check()
        assert events.index("persist") < events.index("shutdown")

    def test_a_busy_loop_is_never_mistaken_for_a_frozen_one(self) -> None:
        clock = FakeClock()
        dog = Watchdog(timeout_sec=60.0, clock=clock)
        for _ in range(50):
            clock.advance(59.0)
            dog.beat()
        assert dog.check() is WatchdogVerdict.ALIVE


class TestDeadlinesAndWatchdogAreDifferentGuards:
    def test_a_deadline_fires_while_the_loop_is_healthy(self) -> None:
        """One slow request does not mean the process has stalled."""
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=30.0, clock=clock)
        dog = Watchdog(timeout_sec=60.0, clock=clock)
        deadline = tracker.start("commit")
        clock.advance(31.0)
        dog.beat()
        with pytest.raises(DeadlineExpiredError):
            tracker.check(deadline)
        assert dog.check() is WatchdogVerdict.ALIVE

    def test_the_watchdog_fires_with_no_request_outstanding(self) -> None:
        """A stall with nothing pending is invisible to deadlines."""
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=30.0, clock=clock)
        dog = Watchdog(timeout_sec=60.0, clock=clock)
        clock.advance(61.0)
        assert tracker.expired_count() == 0
        assert dog.check() is WatchdogVerdict.SHUTDOWN


class TestHostileInputDoesNotCrash:
    def test_a_malformed_payload_is_refused_not_raised(self) -> None:
        """A crash mid-turn would void a match we might be winning."""
        orch = orchestrator(DeadTransport(alive_calls=1))
        assert not orch.handle_inbound("handshake", None).ok

    def test_an_unknown_tool_is_refused(self) -> None:
        orch = orchestrator(DeadTransport(alive_calls=1))
        assert not orch.handle_inbound("drop_tables", {}).ok
