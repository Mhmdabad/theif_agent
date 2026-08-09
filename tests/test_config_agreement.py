"""P0-1: the opponent's config digest is a gate, not a courtesy.

Appendix E rule 11 fixes byte-identical configuration on both sides and prices a
deviation at *match void*; Chapter 9 makes ``agree_config`` the gate for a shared
result. Before this module the digest was **sent** and the opponent's copy was
**filed** and never read — ``PeerInboxes.digests`` had one producer and no
consumer — so two peers on different physics played a whole series and produced
two logs nobody could reconcile, which scores zero for both.

Worse, the ``ok`` we were reading meant nothing: ``negotiate`` answers ``{"ok":
True}`` to any well-formed message, so a peer that had never looked at our
digest acknowledged it exactly as one that agreed with it would.

Everything here runs against the real path — two FastMCP servers on two sockets,
two ``PeerInboxes``, two ``Orchestrator``s and the real ``negotiate`` tool —
because the one property a mock cannot demonstrate is the one that matters most:
both peers run this gate **at the same time**, each waiting for a message only
the other can send, and neither may wait before it speaks.
"""

import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from test_localhost_match import (  # noqa: E402
    WHEN,
    PlaysItsOwnPiece,
    build_declaration,
    free_port,
    parameters,
    wait_for,
)
from test_match import a_peering  # noqa: E402
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.mcp_server import ServerSettings, build, serve
from thief_agent.infra.mcp_transport import FastMcpTransport
from thief_agent.infra.protocol import TurnMessage
from thief_agent.runtime.match import MatchRunner
from thief_agent.runtime.orchestrator import MatchAborted, Orchestrator
from thief_agent.shared.config import config_sha256, digests_agree

GAME_UID = "u-0001"
"""The series these tests negotiate. Matches the declaration they build."""

OTHER_UID = "u-0002"
"""A different series. A digest bound to it is not an answer about this one."""

GAME_ID = "uoh26-s82kma9e"

OUR_ROLE = "thief"
"""The role this repository plays. The sibling names the other one."""

THEIR_ROLE = "police"
PATIENCE = 20.0
"""Long enough for two local sockets, short enough that a hang is a failure."""

BRIEF = 1.5
"""The window used when the point of the test is that nothing ever arrives."""


def altered() -> dict[str, Any]:
    """The shipped parameters with one value changed: different physics.

    A single field, because the digest is over the whole file and the failure
    this guards against is exactly the one-line divergence nobody notices.
    """
    config = parameters()
    config["world"]["map_area"] = "London"
    return config


def agreed_digest() -> str:
    return config_sha256(parameters())


@dataclass
class Side:
    """One agent: its mailboxes, its orchestrator, its own socket."""

    role: str
    inboxes: PeerInboxes
    orchestrator: Orchestrator

    def clear(self) -> None:
        """Forget every message from the previous test.

        The two servers are built once for the module because binding sockets
        per test would dominate the runtime; the mailboxes behind them are
        therefore shared and have to be emptied between tests, or a digest one
        test sent would answer the next one's gate.
        """
        self.inboxes.agreements = queue.Queue[dict[str, Any]]()
        self.inboxes.digests = queue.Queue[dict[str, Any]]()
        self.inboxes.scent_locks = queue.Queue[dict[str, Any]]()
        self.inboxes.results = queue.Queue[dict[str, Any]]()
        self.inboxes.turns = queue.Queue[TurnMessage]()
        self.inboxes.accepted_turns.clear()
        self.inboxes.rejected.clear()

    def send(self, body: dict[str, Any]) -> dict[str, Any]:
        """Push a raw negotiation body at the opponent, over the real wire.

        The opponent here is another team's agent, so this is how a hostile or
        merely wrong message actually arrives: as JSON at a registered tool,
        not as a Python object handed to an inbox.
        """
        return self.orchestrator.call_opponent("negotiate", {"message": body})


def a_side(role: str, opponent_port: int) -> Side:
    inboxes = PeerInboxes()
    client = OpponentClient(
        transport=FastMcpTransport(),
        settings=ClientSettings(
            opponent_url=f"http://127.0.0.1:{opponent_port}/mcp",
            response_timeout_sec=10.0,
            max_retries=1,
            retry_backoff_sec=0.5,
        ),
    )
    return Side(
        role=role,
        inboxes=inboxes,
        orchestrator=Orchestrator(inboxes=inboxes, client=client, role=role),
    )


@pytest.fixture(scope="module")
def wire() -> Iterator[tuple[Side, Side]]:
    """This agent and its opponent on two real servers, pointed at each other."""
    our_port, their_port = free_port(), free_port()
    ours, theirs = a_side(OUR_ROLE, their_port), a_side(THEIR_ROLE, our_port)
    for side, port in ((ours, our_port), (theirs, their_port)):
        host = build(side.inboxes, name=f"{side.role}-config-gate")
        threading.Thread(
            target=serve,
            args=(host, ServerSettings(port=port, host="127.0.0.1")),
            daemon=True,
        ).start()
        wait_for(port)
    yield ours, theirs


def fresh(wire: tuple[Side, Side]) -> tuple[Side, Side]:
    """Both sides, with every mailbox emptied."""
    for side in wire:
        side.clear()
    return wire


def concurrently(work: dict[str, Callable[[], Any]], patience: float = 60.0) -> dict[str, Any]:
    """Run one call per side at once, keeping whatever each produced.

    Both sides have to run together: each blocks on a message only the other
    can send. Running them one after the other would time out on the first and
    prove nothing about the pair — and a gate that listened before it spoke
    would deadlock here rather than in front of another team.

    Returns the return value per side, or the exception it raised, so a test
    can assert on both outcomes rather than on whichever thread failed first.
    """
    done: dict[str, Any] = {}

    def run(name: str, call: Callable[[], Any]) -> None:
        try:
            done[name] = call()
        except BaseException as exc:  # noqa: BLE001 - reported below, not swallowed
            done[name] = exc

    threads = [threading.Thread(target=run, args=(n, c)) for n, c in work.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=patience)
    assert not [t for t in threads if t.is_alive()], (
        "a side never returned; the two peers deadlocked waiting for each other"
    )
    return done


def gate(side: Side, config: dict[str, Any], timeout: float = PATIENCE) -> Callable[[], str]:
    return lambda: side.orchestrator.agree_config(config, game_uid=GAME_UID, timeout=timeout)


def both_run(
    wire: tuple[Side, Side],
    our_config: dict[str, Any],
    their_config: dict[str, Any],
    timeout: float = PATIENCE,
) -> dict[str, Any]:
    ours, theirs = fresh(wire)
    return concurrently(
        {"ours": gate(ours, our_config, timeout), "theirs": gate(theirs, their_config, timeout)}
    )


def a_runner(side: Side, config: dict[str, Any], directory: Path) -> MatchRunner:
    """A real match runner on this side, whose first step is the gate."""
    return MatchRunner(
        orchestrator=side.orchestrator,
        declaration=build_declaration(side.role, GAME_ID, GAME_UID),
        parameters=config,
        brain=PlaysItsOwnPiece("cop" if side.role == "police" else "thief"),  # type: ignore[arg-type]
        axes=AxisConvention(),
        start=BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0),
        max_steps=3,
        directory=directory,
        now=lambda: WHEN,
        peering=a_peering(side.role),
    )


class TestMatchingConfigsOpenTheSeries:
    """Byte-identical parameters on both sides: the series opens, symmetrically."""

    def test_both_sides_come_back_with_the_same_digest(self, wire: tuple[Side, Side]) -> None:
        done = both_run(wire, parameters(), parameters())
        assert done == {"ours": agreed_digest(), "theirs": agreed_digest()}

    def test_each_side_consumed_the_others_digest(self, wire: tuple[Side, Side]) -> None:
        """One producer and no consumer was the whole of P0-1."""
        ours, theirs = wire
        both_run(wire, parameters(), parameters())
        assert ours.inboxes.digests.empty(), "we never read what the opponent sent"
        assert theirs.inboxes.digests.empty(), "the opponent never read what we sent"

    def test_nothing_was_refused_at_either_door(self, wire: tuple[Side, Side]) -> None:
        """A refusal here would be two peers disagreeing about the protocol."""
        ours, theirs = wire
        both_run(wire, parameters(), parameters())
        assert ours.inboxes.rejected == []
        assert theirs.inboxes.rejected == []

    def test_the_digest_advertised_is_the_one_being_enforced(self, wire: tuple[Side, Side]) -> None:
        """Advertising a digest we are not playing by is cheating at audit."""
        ours, theirs = fresh(wire)
        concurrently({"ours": gate(ours, parameters()), "theirs": gate(theirs, parameters())})
        filed = theirs.inboxes.digests
        assert filed.empty() or filed.get_nowait()["config_sha256"] == agreed_digest()


class TestBothPeersCanNegotiateAtOnce:
    """Neither side may wait before it speaks, or two polite peers hang forever."""

    def test_neither_side_waits_for_the_other_to_go_first(self, wire: tuple[Side, Side]) -> None:
        """A window neither could survive if the gate serialised the two peers."""
        done = both_run(wire, parameters(), parameters(), timeout=BRIEF)
        assert [type(v) for v in done.values()] == [str, str], done

    def test_a_repeated_series_of_gates_never_stalls(self, wire: tuple[Side, Side]) -> None:
        """Six sub-games' worth of negotiation, back to back."""
        for _ in range(3):
            done = both_run(wire, parameters(), parameters(), timeout=BRIEF)
            assert set(done.values()) == {agreed_digest()}


class TestAMismatchAbortsBeforeAnySubGame:
    """Different physics is not a game. It is refused, by both sides, up front."""

    def test_both_sides_abort(self, wire: tuple[Side, Side]) -> None:
        done = both_run(wire, parameters(), altered())
        for role, outcome in done.items():
            assert isinstance(outcome, MatchAborted), f"{role} played on: {outcome!r}"

    def test_the_cause_is_an_illegal_action_on_both_sides(self, wire: tuple[Side, Side]) -> None:
        """Deterministic, and the same verdict each way round.

        Not a timeout: the opponent answered, and what they said was
        incompatible. Both teams have to agree a result before either reports
        one, and "they never replied" is a different conversation from "we are
        playing different games".
        """
        done = both_run(wire, parameters(), altered())
        assert [o.cause for o in done.values()] == [TechnicalLoss.ILLEGAL_ACTION] * 2

    def test_the_detail_names_both_digests(self, wire: tuple[Side, Side]) -> None:
        """An accusation both teams must reconcile arrives with the arithmetic."""
        done = both_run(wire, parameters(), altered())
        detail = done["ours"].detail
        assert agreed_digest() in detail and config_sha256(altered()) in detail

    def test_not_one_sub_game_is_played(self, wire: tuple[Side, Side], tmp_path: Path) -> None:
        """The mismatch has to be found before a move nobody can un-play."""
        ours, theirs = fresh(wire)
        runner = a_runner(ours, altered(), tmp_path)
        done = concurrently(
            {"ours": lambda: runner.agree(timeout=PATIENCE), "theirs": gate(theirs, parameters())}
        )
        assert isinstance(done["ours"], MatchAborted)
        assert runner.outcomes == []

    def test_no_turn_ever_crosses_the_wire(self, wire: tuple[Side, Side], tmp_path: Path) -> None:
        """The opponent's mailbox is the only witness that would survive a dispute."""
        ours, theirs = fresh(wire)
        runner = a_runner(ours, altered(), tmp_path)
        concurrently(
            {"ours": lambda: runner.agree(timeout=PATIENCE), "theirs": gate(theirs, parameters())}
        )
        assert theirs.inboxes.turns.empty()
        assert theirs.inboxes.accepted_turns == {}


class TestSilenceFailsClosed:
    """No digest is not a reason to wait, and never a reason to play."""

    def test_a_peer_that_never_negotiates_produces_a_timeout(self, wire: tuple[Side, Side]) -> None:
        ours, _ = fresh(wire)
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_it_fails_inside_its_own_window_rather_than_hanging(
        self, wire: tuple[Side, Side]
    ) -> None:
        ours, _ = fresh(wire)
        started = time.monotonic()
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert time.monotonic() - started < 15.0, "the gate hung instead of failing closed"

    def test_the_opponent_acknowledged_us_all_the_same(self, wire: tuple[Side, Side]) -> None:
        """``ok`` is not agreement, and that is precisely what P0-1 relied on.

        ``negotiate`` answers ``{"ok": True}`` to any well-formed message. The
        peer here files our digest, says yes, and never sends one back — the
        exact shape of a peer that has not agreed to anything.
        """
        ours, theirs = fresh(wire)
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert theirs.inboxes.digests.qsize() == 1


class TestOnlyAWellFormedCurrentDigestSatisfiesTheGate:
    """Malformed, stale and duplicated input all fail closed."""

    @pytest.mark.parametrize(
        "value",
        ["", "not-a-digest", "a" * 63, "a" * 65, "z" * 64, 0, True, None, ["a" * 64]],
    )
    def test_a_malformed_digest_is_refused_at_the_door(
        self, wire: tuple[Side, Side], value: object
    ) -> None:
        """It never reaches a mailbox, so no consumer has to handle it mid-gate."""
        ours, theirs = fresh(wire)
        assert theirs.send({"config_sha256": value})["ok"] is False
        assert ours.inboxes.digests.empty()
        assert ours.inboxes.rejected

    def test_a_refused_digest_cannot_satisfy_the_gate(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": "not-a-digest"})
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_a_digest_bound_to_another_series_does_not_answer_this_one(
        self, wire: tuple[Side, Side]
    ) -> None:
        """Right digest, wrong series. Replaying it must buy nothing."""
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": agreed_digest(), "game_uid": OTHER_UID})
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_a_digest_bound_to_this_series_does_answer_it(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": agreed_digest(), "game_uid": GAME_UID})
        assert (
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
            == agreed_digest()
        )

    def test_an_unbound_digest_is_still_accepted(self, wire: tuple[Side, Side]) -> None:
        """The reference protocol sends the digest alone; refusing it breaks interop.

        Binding is additive: a message that names a *different* series is
        stale, a message that names none is the reference peer being itself.
        """
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": agreed_digest()})
        assert (
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
            == agreed_digest()
        )

    def test_an_identical_retry_is_not_a_disagreement(self, wire: tuple[Side, Side]) -> None:
        """A retry re-sends bytes. Two copies of one answer are still one answer."""
        ours, theirs = fresh(wire)
        for _ in range(2):
            theirs.send({"config_sha256": agreed_digest(), "game_uid": GAME_UID})
        assert (
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
            == agreed_digest()
        )

    def test_a_duplicate_cannot_mask_a_disagreement_behind_it(
        self, wire: tuple[Side, Side]
    ) -> None:
        """Taking the first queued digest and stopping would pass this."""
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": agreed_digest(), "game_uid": GAME_UID})
        theirs.send({"config_sha256": agreed_digest(), "game_uid": GAME_UID})
        theirs.send({"config_sha256": config_sha256(altered()), "game_uid": GAME_UID})
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION

    def test_a_consumed_digest_does_not_open_the_next_series(self, wire: tuple[Side, Side]) -> None:
        """Otherwise one negotiation would open every series that followed it."""
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": agreed_digest(), "game_uid": GAME_UID})
        ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_an_uppercase_spelling_is_the_same_digest(self, wire: tuple[Side, Side]) -> None:
        """Canonicalised at the door, so the gate only ever compares canonical forms."""
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": agreed_digest().upper(), "game_uid": GAME_UID})
        assert (
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
            == agreed_digest()
        )

    def test_a_greeting_is_not_a_digest(self, wire: tuple[Side, Side]) -> None:
        """The two bodies share one tool; only one of them answers this question."""
        ours, theirs = fresh(wire)
        theirs.send(
            {
                "greeting": {
                    "role": THEIR_ROLE,
                    "group_id": "them",
                    "public_url": "https://peer-c3d4.ngrok-free.app",
                    "protocol_version": "1.0",
                }
            }
        )
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT


class TestWhatWeSendCarriesTheBinding:
    def test_the_outbound_message_names_the_series(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=BRIEF)
        assert theirs.inboxes.digests.get_nowait() == {
            "config_sha256": agreed_digest(),
            "game_uid": GAME_UID,
        }

    def test_the_runner_binds_the_digest_to_its_own_declaration(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        """The series in the declaration and the series we negotiate are one."""
        ours, theirs = fresh(wire)
        runner = a_runner(ours, parameters(), tmp_path)
        with pytest.raises(MatchAborted):
            runner.agree(timeout=BRIEF)
        assert theirs.inboxes.digests.get_nowait()["game_uid"] == runner.declaration.game_uid


class TestTheComparisonItself:
    """The predicate both repositories share, so neither can drift into ``==``."""

    def test_equal_digests_agree(self) -> None:
        assert digests_agree(agreed_digest(), agreed_digest())

    def test_different_digests_do_not(self) -> None:
        assert not digests_agree(agreed_digest(), config_sha256(altered()))

    def test_a_truncated_digest_does_not_agree(self) -> None:
        assert not digests_agree(agreed_digest(), agreed_digest()[:-1])

    def test_it_does_not_leak_the_position_of_the_first_difference(self) -> None:
        """A byte-at-a-time ``==`` tells a prober how much of a guess was right."""
        import thief_agent.shared.config as module

        assert "compare_digest" in Path(module.__file__ or "").read_text()
