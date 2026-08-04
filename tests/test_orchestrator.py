"""Tests for the single-gateway orchestrator."""

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.handshake import Peering
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.runtime.orchestrator import PROTOCOL_VERSION, MatchAborted, Orchestrator
from thief_agent.shared.config import config_sha256

SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)
OUR_URL = "https://thief-c3d4.ngrok-free.app"
THEIR_URL = "https://cop-a1b2.ngrok-free.app"
TURN = {
    "step": 1,
    "sender": "police",
    "hint": "slipping away",
    "smell_grid": {"3,3": 0.9},
    "commit": "a" * 64,
    "timestamp": "2026-08-03T09:00:00+00:00",
}


def shipped() -> dict[str, Any]:
    text = (Path(__file__).parents[1] / "config/game.json").read_text()
    loaded: dict[str, Any] = json.loads(text)
    return loaded


class FakeTransport:
    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append({"tool": tool, "payload": payload})
        outcome = self._outcomes.pop(0) if self._outcomes else {"ok": True}
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


def orchestrator(*outcomes: object) -> tuple[Orchestrator, FakeTransport]:
    transport = FakeTransport(*outcomes)
    return Orchestrator(PeerInboxes(), OpponentClient(transport, SETTINGS)), transport


class TestSingleGateway:
    def test_inbound_reaches_the_mailboxes(self) -> None:
        orch, _ = orchestrator()
        assert orch.handle_inbound("receive_turn", TURN)["ok"] is True
        assert orch.inboxes.turns.get_nowait().step == 1

    def test_inbound_is_delegated_not_revalidated(self) -> None:
        """Two validators that disagree are worse than one."""
        orch, _ = orchestrator()
        assert orch.handle_inbound("receive_turn", None)["ok"] is False
        assert orch.inboxes.rejected

    def test_an_unknown_tool_is_refused(self) -> None:
        orch, _ = orchestrator()
        assert orch.handle_inbound("drop_tables", {})["ok"] is False

    def test_every_wire_tool_is_routed(self) -> None:
        orch, _ = orchestrator()
        for tool in ("negotiate", "receive_turn", "submit_audit", "receive_control"):
            assert "ok" in orch.handle_inbound(tool, {})

    def test_no_game_rule_lives_here(self) -> None:
        """It coordinates and does not decide."""
        import thief_agent.runtime.orchestrator as module

        source = Path(module.__file__ or "").read_text()
        for rule_word in ("legal_moves", "apply_move", "is_capture", "BOOK_SCORES"):
            assert rule_word not in source


class TestHeartbeat:
    def test_inbound_and_outbound_both_beat(self) -> None:
        orch, _ = orchestrator()
        orch.handle_inbound("receive_turn", TURN)
        orch.call_opponent("receive_turn", {})
        assert orch.heartbeats == [
            "inbound:receive_turn",
            "outbound:receive_turn",
            "attempt:receive_turn",
        ]

    def test_every_retry_attempt_beats(self) -> None:
        """Retrying is not hanging, and from outside they look the same.

        A call against a dead tunnel can occupy the process for longer than
        the watchdog's patience. Without a beat per attempt the watchdog fires
        over a recovery that was working, and a clean named timeout becomes a
        stall report.
        """
        orch, _ = orchestrator(TimeoutError(), TimeoutError(), {"ok": True})
        orch.call_opponent("receive_turn", {})
        assert orch.heartbeats.count("attempt:receive_turn") == 3

    def test_events_are_published(self) -> None:
        orch, _ = orchestrator()
        seen: list[str] = []
        orch.on_event = seen.append
        orch.handle_inbound("negotiate", {})
        assert seen == ["inbound:negotiate"]


class TestTimeoutBecomesARecordedCause:
    def test_exhausted_retries_abort_with_timeout(self) -> None:
        orch, _ = orchestrator(*[TimeoutError()] * 10)
        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("receive_turn", {})
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_the_cause_carries_detail_for_agreeing_a_result(self) -> None:
        """Both teams must agree a result; a bare failure is hard to agree on."""
        orch, _ = orchestrator(*[TimeoutError()] * 10)
        with pytest.raises(MatchAborted) as excinfo:
            orch.call_opponent("receive_turn", {})
        assert "after 4 attempts" in excinfo.value.detail

    def test_a_recoverable_failure_does_not_abort(self) -> None:
        orch, _ = orchestrator(TimeoutError(), {"ok": True})
        assert orch.call_opponent("receive_turn", {})["ok"] is True


def inbound(
    orch: Orchestrator,
    role: str = "police",
    url: str = THEIR_URL,
    version: str = PROTOCOL_VERSION,
) -> None:
    """Put an opponent greeting in the mailbox, as their push would."""
    orch.inboxes.negotiate(
        {
            "greeting": {
                "role": role,
                "group_id": "them",
                "public_url": url,
                "protocol_version": version,
            }
        }
    )


class TestHandshakeChecks:
    def test_our_greeting_takes_its_role_from_the_orchestrator(self) -> None:
        """The address we announce and the role we play cannot disagree."""
        orch, _ = orchestrator()
        assert orch.greeting(OUR_URL, "s82kma9e").role == "thief"

    def test_announcing_pushes_the_address_through_negotiate(self) -> None:
        orch, transport = orchestrator()
        orch.announce(orch.greeting(OUR_URL, "s82kma9e"))
        assert transport.calls[0]["tool"] == "negotiate"
        assert transport.calls[0]["payload"]["greeting"]["public_url"] == f"{OUR_URL}/mcp"

    def test_a_matching_protocol_and_opposite_role_passes(self) -> None:
        orch, _ = orchestrator()
        inbound(orch)
        assert orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e")).role == "police"

    def test_a_protocol_mismatch_aborts(self) -> None:
        orch, _ = orchestrator()
        inbound(orch, version="0.9")
        with pytest.raises(MatchAborted, match="wire contract must match"):
            orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))

    def test_a_duplicate_role_aborts(self) -> None:
        """Two peers claiming thief is a game with no pursuer and no ending."""
        orch, _ = orchestrator()
        inbound(orch, role="thief")
        with pytest.raises(MatchAborted, match="no capture target"):
            orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))

    @pytest.mark.parametrize("role", ["referee", "cop"])
    def test_a_role_the_wire_does_not_name_aborts(self, role: str) -> None:
        """``cop`` is the opponent's internal name; the wire says ``police``."""
        orch, _ = orchestrator()
        inbound(orch, role=role)
        with pytest.raises(MatchAborted, match="role must be one of"):
            orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))

    def test_an_unreachable_opponent_aborts_when_we_are_public(self) -> None:
        orch, _ = orchestrator()
        inbound(orch, url="http://127.0.0.1:8801")
        with pytest.raises(MatchAborted, match="routes nowhere"):
            orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))

    def test_the_newest_greeting_wins_over_a_stale_one(self) -> None:
        """A greeting says where a peer is *now*; an older one is superseded.

        Greetings genuinely accumulate — a peer whose first announcement failed
        sends a second, and a series re-greets before every sub-game. Reading
        the queue in arrival order would adopt an address already left behind.
        """
        orch, _ = orchestrator()
        inbound(orch, url="https://cop-stale.ngrok-free.app")
        inbound(orch, url="https://cop-fresh.ngrok-free.app")
        accepted = orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))
        assert accepted.public_url == "https://cop-fresh.ngrok-free.app/mcp"

    def test_the_stale_greetings_are_drained_not_left_behind(self) -> None:
        """Otherwise the next sub-game reads the one this one skipped."""
        orch, _ = orchestrator()
        inbound(orch, url="https://cop-stale.ngrok-free.app")
        inbound(orch, url="https://cop-fresh.ngrok-free.app")
        orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))
        assert orch.inboxes.agreements.empty()

    def test_a_single_greeting_still_works(self) -> None:
        orch, _ = orchestrator()
        inbound(orch)
        assert orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e")).public_url == (
            f"{THEIR_URL}/mcp"
        )

    def test_silence_is_a_timeout_not_a_longer_wait(self) -> None:
        """A handshake with no deadline deadlocks with no board to explain it."""
        orch, _ = orchestrator()
        with pytest.raises(MatchAborted, match="no greeting from the opponent") as excinfo:
            orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"), timeout=0.0)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_the_cause_is_recorded(self) -> None:
        orch, _ = orchestrator()
        inbound(orch, role="thief")
        with pytest.raises(MatchAborted) as excinfo:
            orch.accept_greeting(orch.greeting(OUR_URL, "s82kma9e"))
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION


class TestExchangingAddresses:
    def test_it_announces_before_it_waits(self, tmp_path: Path) -> None:
        """Two polite peers each waiting for the other is the deadlock."""
        orch, transport = orchestrator()
        inbound(orch)
        orch.open_series(orch.greeting(OUR_URL, "s82kma9e"), tmp_path, "g1")
        assert [c["tool"] for c in transport.calls] == ["negotiate"]

    def test_it_writes_both_addresses_into_the_declaration(self, tmp_path: Path) -> None:
        orch, _ = orchestrator()
        inbound(orch)
        peering = orch.open_series(orch.greeting(OUR_URL, "s82kma9e"), tmp_path, "g1")
        assert peering.sub_game == 1
        written = json.loads((tmp_path / "declaration_g1.json").read_text())
        assert written["mcp_addresses"]["thief"]["public_url"] == f"{OUR_URL}/mcp"
        assert written["mcp_addresses"]["police"]["public_url"] == f"{THEIR_URL}/mcp"

    def test_a_refused_greeting_writes_no_declaration(self, tmp_path: Path) -> None:
        """A declaration is a record of a match that is going to happen."""
        orch, _ = orchestrator()
        inbound(orch, role="thief")
        with pytest.raises(MatchAborted):
            orch.open_series(orch.greeting(OUR_URL, "s82kma9e"), tmp_path, "g1")
        assert not (tmp_path / "declaration_g1.json").exists()


ROTATED = "https://cop-9z8y.ngrok-free.app"


class TestSurvivingARotatedTunnel:
    def opened(self, tmp_path: Path, *outcomes: object) -> tuple[Orchestrator, Peering]:
        orch, _ = orchestrator(*outcomes)
        inbound(orch)
        return orch, orch.open_series(orch.greeting(OUR_URL, "s82kma9e"), tmp_path, "g1")

    def test_the_opening_handshake_adopts_the_announced_address(self, tmp_path: Path) -> None:
        """``opponent_url`` in the config is a bootstrap value, not the truth.

        It is how we reach them the first time. Their greeting says where they
        actually are, and that is what the declaration records — so calls that
        kept going to the configured address would contradict the file both
        teams signed.
        """
        orch, _ = self.opened(tmp_path)
        assert orch.client.opponent_url == f"{THEIR_URL}/mcp"
        assert orch.client.relocations == [("http://127.0.0.1:8801/mcp", f"{THEIR_URL}/mcp")]

    def test_an_unchanged_address_re_handshakes_quietly(self, tmp_path: Path) -> None:
        """Both peers re-greet every sub-game, whether or not anything moved.

        A re-handshake that only fires when we already know something changed
        cannot discover the thing it exists to discover — the side whose tunnel
        died is precisely the side that cannot tell us.
        """
        orch, first = self.opened(tmp_path)
        inbound(orch)
        second = orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1")
        assert second.sub_game == 2
        assert len(orch.client.relocations) == 1  # the opening adoption, nothing since

    def test_a_failed_announcement_is_tolerated_then_retried_at_the_new_address(
        self, tmp_path: Path
    ) -> None:
        """If *their* tunnel died, the address we hold died with it.

        Announcing before listening would abort on the very failure the
        re-handshake exists to recover from. Announcing *not at all* would
        strand them when it is *our* tunnel that moved. So: try, tolerate,
        listen, adopt, and try again if the first never landed.
        """
        # The opening announce lands; the re-handshake's first one exhausts
        # its whole retry budget against an address that no longer exists.
        orch, first = self.opened(tmp_path, {"ok": True}, *[ConnectionError()] * 4)
        inbound(orch, url=ROTATED)
        orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1")
        assert "announce-failed" in orch.heartbeats
        assert orch.client.opponent_url == f"{ROTATED}/mcp"

    def test_a_new_opponent_url_re_points_the_client(self, tmp_path: Path) -> None:
        orch, first = self.opened(tmp_path)
        inbound(orch, url=ROTATED)
        orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1")
        assert orch.client.opponent_url == f"{ROTATED}/mcp"
        assert orch.client.relocations[-1] == (f"{THEIR_URL}/mcp", f"{ROTATED}/mcp")

    def test_the_relocation_is_a_heartbeat_so_the_log_can_show_it(self, tmp_path: Path) -> None:
        orch, first = self.opened(tmp_path)
        inbound(orch, url=ROTATED)
        orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1")
        assert any(b.startswith("agreed-move:police:") for b in orch.heartbeats)
        assert any(b.startswith("relocated:police:") for b in orch.heartbeats)

    def test_the_declaration_records_which_sub_game_an_address_took_effect(
        self, tmp_path: Path
    ) -> None:
        """Otherwise a rotated series looks exactly like one that never moved."""
        orch, first = self.opened(tmp_path)
        inbound(orch, url=ROTATED)
        orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1")
        written = json.loads((tmp_path / "declaration_g1.json").read_text())
        assert written["mcp_addresses"]["police"] == {
            "role": "police",
            "group_id": "them",
            "public_url": f"{ROTATED}/mcp",
            "protocol_version": PROTOCOL_VERSION,
            "reachable": True,
            "since_sub_game": 2,
        }

    def test_a_different_team_at_a_new_address_is_refused(self, tmp_path: Path) -> None:
        """Not a rotated tunnel — a different peer arriving mid-series."""
        orch, first = self.opened(tmp_path)
        orch.inboxes.negotiate(
            {
                "greeting": {
                    "role": "police",
                    "group_id": "someone-else",
                    "public_url": ROTATED,
                    "protocol_version": PROTOCOL_VERSION,
                }
            }
        )
        with pytest.raises(MatchAborted, match="this is a different peer"):
            orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1")
        assert orch.client.opponent_url == f"{THEIR_URL}/mcp"

    def test_a_mid_sub_game_address_change_is_refused(self, tmp_path: Path) -> None:
        """Indistinguishable from redirecting our traffic after seeing our commit."""
        orch, first = self.opened(tmp_path)
        inbound(orch, url=ROTATED)
        with pytest.raises(MatchAborted, match="only change between sub-games"):
            orch.rehandshake(first, orch.greeting(OUR_URL, "s82kma9e"), 1, tmp_path, "g1")
        assert orch.client.opponent_url == f"{THEIR_URL}/mcp"

    def test_our_own_rotated_address_is_announced_without_re_pointing(self, tmp_path: Path) -> None:
        """Their client re-points, not ours. We only tell them where we moved."""
        orch, first = self.opened(tmp_path)
        inbound(orch)
        ours_moved = orch.greeting("https://thief-9z8y.ngrok-free.app", "s82kma9e")
        second = orch.rehandshake(first, ours_moved, 2, tmp_path, "g1")
        assert second.ours.public_url == "https://thief-9z8y.ngrok-free.app/mcp"
        assert len(orch.client.relocations) == 1  # the opening adoption only

    def test_silence_at_re_handshake_is_a_timeout(self, tmp_path: Path) -> None:
        orch, first = self.opened(tmp_path)
        with pytest.raises(MatchAborted) as excinfo:
            orch.rehandshake(
                first, orch.greeting(OUR_URL, "s82kma9e"), 2, tmp_path, "g1", timeout=0.0
            )
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT


class TestConfigAgreement:
    def test_advertises_the_digest_of_the_loaded_config(self) -> None:
        """The digest we advertise must be the one we are enforcing."""
        config = shipped()
        orch, transport = orchestrator({"ok": True})
        assert orch.agree_config(config) == config_sha256(config)
        assert transport.calls[0]["payload"]["config_sha256"] == config_sha256(config)

    def test_it_negotiates_over_the_wire_tool(self) -> None:
        orch, transport = orchestrator({"ok": True})
        orch.agree_config(shipped())
        assert transport.calls[0]["tool"] == "negotiate"

    def test_a_mismatch_aborts_rather_than_playing_on(self) -> None:
        orch, _ = orchestrator({"ok": False, "detail": "digest mismatch"})
        with pytest.raises(MatchAborted) as excinfo:
            orch.agree_config(shipped())
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert "digest mismatch" in excinfo.value.detail

    def test_a_changed_config_changes_the_advertised_digest(self) -> None:
        config = shipped()
        orch, _ = orchestrator({"ok": True}, {"ok": True})
        first = orch.agree_config(config)
        config["world"]["map_area"] = "London"
        assert orch.agree_config(config) != first


class TestMatchAbortedSurvivesPropagation:
    """An exception that loses its cause is worse than no exception at all."""

    @contextlib.contextmanager
    def turn(self) -> Iterator[None]:
        yield

    def test_it_keeps_its_cause_through_a_context_manager(self) -> None:
        """``slots=True`` on an Exception silently replaces it with a TypeError.

        A slotted class has nowhere to store ``__traceback__``, so Python
        discards the exception mid-propagation and raises a ``TypeError`` about
        class identity instead — losing precisely the named cause both teams
        must agree on before either may report a result.
        """
        with pytest.raises(MatchAborted) as excinfo, self.turn():
            raise MatchAborted(TechnicalLoss.TIMEOUT, "tunnel died at step 12")
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT
        assert excinfo.value.detail == "tunnel died at step 12"

    def test_it_can_carry_a_traceback(self) -> None:
        try:
            raise MatchAborted(TechnicalLoss.CRASH, "peer exited")
        except MatchAborted as exc:
            assert exc.__traceback__ is not None

    def test_it_survives_nested_context_managers(self) -> None:
        with pytest.raises(MatchAborted), self.turn(), self.turn():
            raise MatchAborted(TechnicalLoss.FORGERY, "commit did not match reveal")

    def test_frozen_was_the_actual_culprit_not_slots(self) -> None:
        """``frozen=True`` refuses ``__traceback__`` just as surely as slots.

        Removing only ``slots=True`` swaps a ``TypeError`` for a
        ``FrozenInstanceError`` and destroys the exception either way. The
        assertion is on the ability to carry a traceback, because that is the
        property the class needs and immutability was never one.
        """
        aborted = MatchAborted(TechnicalLoss.TIMEOUT, "detail")
        aborted.__traceback__ = None
        assert (aborted.cause, aborted.detail) == (TechnicalLoss.TIMEOUT, "detail")
