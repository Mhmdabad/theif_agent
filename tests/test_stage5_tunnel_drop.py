"""Stage 5 acceptance: the tunnel dies mid-match.

This is not a hypothetical. Free-tier tunnels drop, laptops sleep, wifi moves
between access points — and the rulebook says so in as many words: *if one
tunnel falls, the opposite side loses the ability to verify moves and would
deadlock on turn scheduling*.

What is being asserted is **not** that we survive it. We do not; nobody can.
What is asserted is the difference between the two ways of not surviving:

* a **hang** — no error, no result, no story to tell an opponent, and a match
  that has to be abandoned by hand;
* a **technical loss with a named cause** — agreed with the opponent, reported,
  and closed out.

Both score zero on the board. Only one of them can be finished. That is the
entire subject of this file, and it is why the assertions are about terminal
states, causes and elapsed time rather than about recovery.

Every clock here is injected. A test that proved timeout behaviour by actually
waiting two minutes would be a test nobody runs.
"""

from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.outcome import TechnicalLoss, technical_loss_scores
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.transport_log import CONNECT, RETRY, SENT, TIMEOUT, UNREACHABLE, TransportLog
from thief_agent.runtime.deadline import DEFAULT_RESPONSE_TIMEOUT_SEC
from thief_agent.runtime.orchestrator import MatchAborted, Orchestrator
from thief_agent.runtime.state_machine import GamePhaseMachine, Phase
from thief_agent.runtime.watchdog import DEFAULT_WATCHDOG_TIMEOUT_SEC, Watchdog, WatchdogVerdict

LIVE_URL = "https://opponent-c3d4.ngrok-free.app/mcp"
TURN = {
    "step": 4,
    "sender": "police",
    "hint": "gone quiet",
    "smell_grid": {"3,3": 0.9},
    "commit": "a" * 64,
    "timestamp": "2026-08-04T09:00:00+00:00",
}


class Tunnel:
    """A tunnel that answers until it is killed, then refuses forever.

    Refusing rather than hanging is the honest simulation: a dropped ngrok
    tunnel returns an error from the edge, it does not black-hole traffic. The
    slower case — where every attempt burns the full response timeout — is
    covered by the elapsed-time assertions instead.
    """

    def __init__(self, elapsed: list[float] | None = None) -> None:
        self.alive = True
        self.calls = 0
        self.elapsed = elapsed if elapsed is not None else []

    def kill(self) -> None:
        self.alive = False

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls += 1
        if not self.alive:
            self.elapsed.append(timeout)  # a real drop can burn the whole window
            raise ConnectionError(f"tunnel at {url} is gone")
        return {"ok": True}


def peer(tunnel: Tunnel, slept: list[float] | None = None) -> Orchestrator:
    settings = ClientSettings(opponent_url=LIVE_URL)
    client = OpponentClient(
        tunnel,
        settings,
        sleep=(slept.append if slept is not None else (lambda _: None)),
        log=TransportLog(),
    )
    return Orchestrator(PeerInboxes(), client)


class TestTheKillProducesAResultRatherThanASilence:
    def test_the_match_was_alive_first(self) -> None:
        """Otherwise the test proves nothing about a *drop*."""
        tunnel = Tunnel()
        orch = peer(tunnel)
        assert orch.call_opponent("receive_turn", TURN)["ok"] is True
        assert orch.client.log.of_kind(CONNECT)

    def test_the_kill_aborts_with_a_named_cause(self) -> None:
        tunnel = Tunnel()
        orch = peer(tunnel)
        orch.call_opponent("receive_turn", TURN)
        tunnel.kill()

        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("receive_turn", {**TURN, "step": 5})
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT
        assert "after 4 attempts" in excinfo.value.detail
        assert LIVE_URL in excinfo.value.detail

    def test_the_cause_survives_propagation(self) -> None:
        """The bug that made this untrue is #218; the regression guard is here.

        A cause destroyed in flight is a technical loss nobody can agree on,
        and agreement is required before either team may report a result.
        """
        tunnel = Tunnel()
        orch = peer(tunnel)
        tunnel.kill()
        try:
            orch.call_opponent("receive_turn", TURN)
        except MatchAborted as aborted:
            assert (aborted.cause, bool(aborted.detail)) == (TechnicalLoss.TIMEOUT, True)
        else:  # pragma: no cover - the call above always raises
            pytest.fail("a dead tunnel must abort")

    def test_it_gives_up_rather_than_retrying_forever(self) -> None:
        """The budget expressed in the settings *is* the whole allowance."""
        tunnel = Tunnel()
        orch = peer(tunnel)
        tunnel.kill()
        with pytest.raises(MatchAborted):
            orch.call_opponent("receive_turn", TURN)
        assert tunnel.calls == 4

    def test_the_state_machine_reaches_a_terminal_phase(self) -> None:
        """A hang leaves the machine mid-turn with no phase that can end it."""
        machine = GamePhaseMachine(Phase.COMPUTING_MOVE)
        tunnel = Tunnel()
        orch = peer(tunnel)
        tunnel.kill()
        try:
            orch.call_opponent("receive_turn", TURN)
        except MatchAborted as aborted:
            machine.abort(str(aborted.cause))
        assert machine.phase is Phase.TECHNICAL_LOSS
        assert machine.is_terminal

    def test_the_scoreboard_is_zero_for_both_sides(self) -> None:
        """Which is why a dropped tunnel destroys a winning position too."""
        assert technical_loss_scores() == (0, 0)


class TestItStaysInsideTheDeadlineBudget:
    def test_the_backoff_is_bounded_by_the_retry_count(self) -> None:
        slept: list[float] = []
        tunnel = Tunnel()
        orch = peer(tunnel, slept=slept)
        tunnel.kill()
        with pytest.raises(MatchAborted):
            orch.call_opponent("receive_turn", TURN)
        assert slept == [5.0, 5.0, 5.0]  # three gaps between four attempts

    def test_no_attempt_waits_longer_than_the_response_timeout(self) -> None:
        """Every attempt carries the deadline; none of them waits unbounded."""
        windows: list[float] = []
        tunnel = Tunnel(elapsed=windows)
        orch = peer(tunnel)
        tunnel.kill()
        with pytest.raises(MatchAborted):
            orch.call_opponent("receive_turn", TURN)
        assert windows == [DEFAULT_RESPONSE_TIMEOUT_SEC] * 4

    def test_the_worst_case_is_stated_rather_than_discovered(self) -> None:
        settings = ClientSettings(opponent_url=LIVE_URL)
        assert settings.worst_case_seconds == 4 * 30.0 + 3 * 5.0

    def test_the_worst_case_outlives_the_watchdog_and_that_is_the_point(self) -> None:
        """135 seconds of retrying against 60 seconds of patience.

        Not a bug in either number. It is why a retrying client has to *say*
        it is retrying — otherwise the watchdog cannot tell it from a process
        that has stopped, and shuts the match down over a recovery that was
        working exactly as designed.
        """
        settings = ClientSettings(opponent_url=LIVE_URL)
        assert settings.worst_case_seconds > DEFAULT_WATCHDOG_TIMEOUT_SEC

    def test_raising_max_retries_moves_the_worst_case(self) -> None:
        """``max_retries`` is a raisable minimum, so this number is not fixed."""
        settings = ClientSettings(opponent_url=LIVE_URL, max_retries=6)
        assert settings.worst_case_seconds == 7 * 30.0 + 6 * 5.0


class TestTheWatchdogSeesRetryingRatherThanStalling:
    def test_a_retrying_client_keeps_the_watchdog_satisfied(self) -> None:
        now = [0.0]
        dog = Watchdog(clock=lambda: now[0])
        tunnel = Tunnel()
        orch = peer(tunnel)
        orch.on_event = lambda _: dog.beat()
        tunnel.kill()

        with pytest.raises(MatchAborted):
            orch.call_opponent("receive_turn", TURN)
        now[0] = 50.0  # well into the 135s a real drop would take
        assert dog.check() is WatchdogVerdict.ALIVE
        assert dog.beats >= 4  # one per attempt, at least

    def test_without_the_beats_the_watchdog_would_fire(self) -> None:
        """The counterfactual, so the wiring is not mistaken for decoration.

        A watchdog shutdown is *a* controlled outcome, but it reports a stall
        rather than a timeout — a worse story to hand an opponent who has to
        agree the result before either side may report it.
        """
        now = [0.0]
        dog = Watchdog(clock=lambda: now[0])
        now[0] = DEFAULT_WATCHDOG_TIMEOUT_SEC + 1
        assert dog.check() is WatchdogVerdict.SHUTDOWN


class TestTheLogTellsTheStory:
    def dropped(self) -> Orchestrator:
        tunnel = Tunnel()
        orch = peer(tunnel)
        orch.call_opponent("receive_turn", TURN)
        tunnel.kill()
        with pytest.raises(MatchAborted):
            orch.call_opponent("receive_turn", {**TURN, "step": 5})
        return orch

    def test_it_shows_the_tunnel_alive_then_gone(self) -> None:
        log = self.dropped().client.log
        assert [event.kind for event in log.events] == [
            SENT,
            CONNECT,
            SENT,
            TIMEOUT,
            RETRY,
            TIMEOUT,
            RETRY,
            TIMEOUT,
            RETRY,
            TIMEOUT,
            UNREACHABLE,
        ]

    def test_the_summary_is_readable_by_a_person(self) -> None:
        rendered = self.dropped().client.log.render()
        assert "unreachable 1" in rendered
        assert "is gone" in rendered

    def test_it_can_be_written_beside_the_match(self, tmp_path: Path) -> None:
        """Evidence for a result that has no board to point at."""
        path = self.dropped().client.log.write(tmp_path / "transport_g1_g01.log")
        assert LIVE_URL in path.read_text()
