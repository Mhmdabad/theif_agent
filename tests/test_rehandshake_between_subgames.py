"""P1-14: the six sub-games are separated by a re-handshake, and it is wired in.

``Orchestrator.rehandshake`` was fully implemented — it tolerates a first failed
announce, refuses anything but an address rotation, and re-records the address
book — and it had **zero call sites**. The series loop ran ``play_sub_game`` six
times with nothing between the iterations, so a free-tier tunnel that rotated
partway through a series killed the whole series, including the sub-games already
won on the board: a technical loss scores zero for **both** sides, so a dead
tunnel destroys results that were already earned.

This file follows the boundary from the loop to the wire. The interleaving is
read off the transport rather than off a spy, because what matters is not that a
method was called but that a ``negotiate`` crossed the wire between one sub-game's
last message and the next one's first — and that the next one's first message
went to the address that re-handshake agreed.

The trace a whole series leaves is therefore the central assertion here::

    negotiate, receive_turn, negotiate, receive_turn, … , receive_turn
    └ open ─┘  └ game 1 ─┘  └ 1→2 ─┘   └ game 2 ─┘        └ game 6 ─┘

One opening handshake, five boundaries, nothing after the sixth sub-game.
"""

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from test_localhost_match import (
    PlaysItsOwnPiece,
    build_declaration,
    free_port,
    parameters,
    wait_for,
)
from test_match import an_outcome
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.ceremony import Commitment
from thief_agent.infra.handshake import Peering
from thief_agent.infra.inboxes import (
    ACK,
    DIGEST_KEY,
    SCENT_DIGEST_KEY,
    SCENT_KEY,
    SERIES_KEY,
    PeerInboxes,
)
from thief_agent.infra.match_log import MatchLog
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.mcp_server import ServerSettings, build, serve
from thief_agent.infra.mcp_transport import FastMcpTransport
from thief_agent.runtime.match import MatchRunner, SubGameOutcome
from thief_agent.runtime.orchestrator import (
    GREETING_TIMEOUT_SEC,
    PROTOCOL_VERSION,
    MatchAborted,
    Orchestrator,
)
from thief_agent.runtime.peer import McpPeer
from thief_agent.shared.appendix_f import book_int
from thief_agent.shared.config import config_sha256
from thief_agent.strategy.thief_brain import ThiefBrain
from thief_agent.ui.replay import load
from thief_agent.ui.verdict import Stamp, walk

ROLE = "thief"
OPPONENT = "police"
GROUP = "s82kma9e"
GAME_ID = "uoh26-s82kma9e"
GAME_UID = "u-0001"
WHEN = "2026-08-05T12:00:00+00:00"
AXES = AxisConvention()
COMMIT = "a" * 64

BOOK_SERIES = book_int("network_and_league", "num_games")
BOOK_RETRIES = book_int("rate_limiter_gatekeeper", "max_retries")
BOOK_RESPONSE_TIMEOUT = book_int("network_and_league", "response_timeout_sec")
BOUNDARIES = [2, 3, 4, 5, 6]
"""Every sub-game a re-handshake precedes: 1→2 through 5→6, and nothing else."""

OUR_URL = "https://thief-a1b2.ngrok-free.app"
THEIR_URL = "https://cop-c3d4.ngrok-free.app"
ROTATED = "https://cop-e5f6.ngrok-free.app"
PRIVATE = "http://10.0.0.7:8802"
LOOPBACK = "http://127.0.0.1:8802"

AT_THEIRS = f"{THEIR_URL}/mcp"
AT_ROTATED = f"{ROTATED}/mcp"


def greets(url: str, **changed: str) -> dict[str, Any]:
    """The negotiate message the opponent pushes at us to say where it is."""
    return {
        "greeting": {
            "role": OPPONENT,
            "group_id": "them",
            "public_url": url,
            "protocol_version": PROTOCOL_VERSION,
            **changed,
        }
    }


@dataclass
class ScriptedPeer:
    """A transport that answers us, and pushes what the opponent would push back.

    The opponent's re-greeting is **not** the reply to ours: it is a separate
    call into our own server, which is why :attr:`announce` is filed into our
    inboxes rather than returned. Filing it on every attempt — including the ones
    that fail — is the closest a socket-free test gets to the real interleaving,
    where their announcement is on its own schedule and arrives whether or not
    ours ever landed.

    Every attempt is recorded as ``(url, tool)``, so a whole series leaves a
    trace of what crossed the wire and, for each message, where it went.
    """

    inboxes: PeerInboxes
    announce: dict[str, Any] | None = field(default_factory=lambda: greets(THEIR_URL))
    failing: frozenset[int] = frozenset()
    """Which ``negotiate`` attempts, counted from one, fail as a dead tunnel."""

    calls: list[tuple[str, str]] = field(default_factory=list, init=False)
    negotiations: int = field(default=0, init=False)

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append((url, tool))
        if tool != "negotiate":
            return dict(ACK)
        self.negotiations += 1
        if self.announce is not None:
            self.inboxes.negotiate(dict(self.announce))
        if self.negotiations in self.failing:
            raise ConnectionError("the address this call named is a tunnel that no longer exists")
        return dict(ACK)

    @property
    def tools(self) -> list[str]:
        return [tool for _, tool in self.calls]

    def where(self, tool: str) -> list[str]:
        """Every address a given tool was called at, in order."""
        return [url for url, called in self.calls if called == tool]


def a_runner(tmp_path: Path, transport: ScriptedPeer, peering: Peering | None) -> MatchRunner:
    """A runner over ``transport``, built the way the driver builds one."""
    return MatchRunner(
        orchestrator=Orchestrator(
            inboxes=transport.inboxes,
            client=OpponentClient(
                transport=transport,
                settings=ClientSettings(opponent_url=THEIR_URL, retry_backoff_sec=0.0),
            ),
            role=ROLE,
        ),
        declaration=build_declaration(ROLE, GAME_ID, GAME_UID),
        parameters=parameters(),
        brain=ThiefBrain(),
        axes=AXES,
        start=BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0),
        max_steps=2,
        directory=tmp_path,
        now=lambda: WHEN,
        peering=peering,
    )


def opened(tmp_path: Path, transport: ScriptedPeer) -> MatchRunner:
    """A runner whose series has had its opening handshake, as the driver does.

    The driver trades addresses through ``open_series`` and hands the result to
    the runner, so the runner starts a series already knowing who it is playing
    and where. Anything else would be a re-handshake with nothing to compare
    against.
    """
    orchestrator = Orchestrator(
        inboxes=transport.inboxes,
        client=OpponentClient(
            transport=transport,
            settings=ClientSettings(opponent_url=THEIR_URL, retry_backoff_sec=0.0),
        ),
        role=ROLE,
    )
    peering = orchestrator.open_series(orchestrator.greeting(OUR_URL, GROUP), tmp_path, GAME_ID)
    runner = a_runner(tmp_path, transport, peering)
    runner.orchestrator = orchestrator
    return runner


def plays(after: Callable[[int], None] = lambda _: None) -> Callable[..., SubGameOutcome]:
    """A stand-in sub-game that makes the one call a real sub-game opens with.

    The ceremony is not what is under test here; *where its first message goes*
    is. So the stub sends a commitment through a real :class:`McpPeer` built from
    the runner's own client — the same object the real sub-game builds — and the
    transport records the address it went to.

    Args:
        after: run once the sub-game is over, for a test that needs the
            opponent's tunnel to rotate between two particular sub-games.
    """

    def play(self: MatchRunner, number: int, timeout: float = 30.0) -> SubGameOutcome:
        McpPeer(
            role=self.role,
            client=self.orchestrator.client,
            inboxes=self.orchestrator.inboxes,
            game_uid=self.declaration.game_uid,
            sub_game=number,
            now=WHEN,
            timeout=timeout,
        ).send_commit(Commitment(step=1, sender=self.role, commit=COMMIT, timestamp=WHEN))
        outcome = an_outcome(number)
        self.outcomes.append(outcome)
        after(number)
        return outcome

    return play


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[int], None]], None]:
    """Install a stand-in sub-game, so a whole series runs without a ceremony."""

    def install(after: Callable[[int], None] = lambda _: None) -> None:
        monkeypatch.setattr(MatchRunner, "play_sub_game", plays(after))

    return install


Install = Callable[..., None]


class TestTheSeriesReHandshakesAtEveryBoundaryAndNowhereElse:
    """The defect was a loop with nothing between its iterations."""

    def test_a_whole_series_interleaves_one_re_handshake_between_each_pair(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """Read off the wire: an announcement between every pair of sub-games."""
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert transport.tools == ["negotiate"] + ["receive_turn", "negotiate"] * 5 + [
            "receive_turn"
        ]

    def test_the_opening_handshake_happens_once_and_before_the_first_sub_game(
        self, tmp_path: Path, stub: Install
    ) -> None:
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        assert transport.tools == ["negotiate"]
        runner.play_series(timeout=1.0)
        assert transport.tools[0] == "negotiate"

    def test_nothing_re_handshakes_after_the_last_sub_game(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """A boundary after the series is over is a message nobody is waiting for."""
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert transport.tools[-1] == "receive_turn"
        assert transport.tools.count("negotiate") == 1 + len(BOUNDARIES)

    def test_the_boundary_is_agreed_for_the_sub_game_it_precedes(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """The peering advances to six, one sub-game at a time."""
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        agreed: list[int] = []
        original = MatchRunner.rehandshake

        def watched(
            self: MatchRunner, number: int, timeout: float = GREETING_TIMEOUT_SEC
        ) -> Peering:
            later = original(self, number, timeout)
            agreed.append(later.sub_game)
            return later

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(MatchRunner, "rehandshake", watched)
            runner.play_series(timeout=1.0)
        assert agreed == BOUNDARIES
        assert runner.peering is not None and runner.peering.sub_game == BOOK_SERIES

    def test_every_sub_game_of_the_book_series_was_played(
        self, tmp_path: Path, stub: Install
    ) -> None:
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        assert [o.number for o in runner.play_series(timeout=1.0)] == list(range(1, 7))

    def test_a_series_that_never_traded_addresses_refuses_to_open(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """Silently skipping the boundary is the defect, not the remedy."""
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = a_runner(tmp_path, transport, peering=None)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_series(timeout=1.0)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert runner.outcomes == []


class TestARotatedAddressReachesTheTransportTheNextSubGameUses:
    """The whole point: the series survives the tunnel it started on."""

    def rotating_after(self, number: int, transport: ScriptedPeer) -> Callable[[int], None]:
        def rotate(played: int) -> None:
            if played == number:
                transport.announce = greets(ROTATED)

        return rotate

    def test_the_next_sub_games_first_commit_goes_to_the_new_address(
        self, tmp_path: Path, stub: Install
    ) -> None:
        transport = ScriptedPeer(PeerInboxes())
        stub(self.rotating_after(2, transport))
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert transport.where("receive_turn") == [AT_THEIRS] * 2 + [AT_ROTATED] * 4

    def test_the_client_is_re_pointed_before_that_commit_rather_than_after(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """A repoint that lands after the commit has already lost the sub-game."""
        transport = ScriptedPeer(PeerInboxes())
        stub(self.rotating_after(2, transport))
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        moved = transport.calls.index((AT_ROTATED, "receive_turn"))
        assert transport.calls[moved - 1] == (AT_THEIRS, "negotiate")
        assert runner.orchestrator.client.opponent_url == AT_ROTATED

    def test_the_relocation_is_recorded_once_where_a_dispute_can_read_it(
        self, tmp_path: Path, stub: Install
    ) -> None:
        transport = ScriptedPeer(PeerInboxes())
        stub(self.rotating_after(2, transport))
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert runner.orchestrator.client.relocations[-1] == (AT_THEIRS, AT_ROTATED)
        assert any(
            beat.startswith(f"agreed-move:{OPPONENT}:") for beat in runner.orchestrator.heartbeats
        )

    def test_the_declaration_says_which_sub_game_the_new_address_took_effect_at(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """Otherwise a rotated series looks exactly like one that never moved."""
        transport = ScriptedPeer(PeerInboxes())
        stub(self.rotating_after(2, transport))
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        written = json.loads((tmp_path / f"declaration_{GAME_ID}.json").read_text())
        assert written["mcp_addresses"][OPPONENT]["public_url"] == AT_ROTATED
        assert written["mcp_addresses"][OPPONENT]["since_sub_game"] == BOOK_SERIES

    def test_one_client_session_is_kept_per_active_endpoint(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """Six sub-games, two endpoints, and no client rebuilt in between.

        Free tunnels cap new connections, and a series that opened a session per
        sub-game died partway through. The re-handshake re-points the client that
        already exists rather than replacing it.
        """
        transport = ScriptedPeer(PeerInboxes())
        stub(self.rotating_after(2, transport))
        runner = opened(tmp_path, transport)
        client = runner.orchestrator.client
        runner.play_series(timeout=1.0)
        assert runner.orchestrator.client is client
        assert client.relocations == [(AT_THEIRS, AT_ROTATED)]  # one move, five boundaries


class TestAnUnchangedAddressIsAcceptedIdempotently:
    """Both peers re-greet every sub-game, whether or not anything moved."""

    def test_six_sub_games_on_one_address_re_point_nothing(
        self, tmp_path: Path, stub: Install
    ) -> None:
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert transport.where("receive_turn") == [AT_THEIRS] * BOOK_SERIES
        assert runner.orchestrator.client.relocations == []

    def test_the_boundaries_still_happened(self, tmp_path: Path, stub: Install) -> None:
        """A re-handshake that only fires on a known change cannot discover one."""
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert transport.tools.count("negotiate") == 1 + len(BOUNDARIES)

    def test_no_relocation_is_reported_for_an_address_that_did_not_move(
        self, tmp_path: Path, stub: Install
    ) -> None:
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        assert not [b for b in runner.orchestrator.heartbeats if b.startswith("agreed-move:")]


class TestOnlyTheAddressMayMoveAcrossABoundary:
    """A greeting that changes anything else is a different peer, not a rotation."""

    @pytest.mark.parametrize(
        "changed",
        [{"role": ROLE}, {"group_id": "someone-else"}, {"protocol_version": "9.9"}],
        ids=["role", "group", "protocol"],
    )
    def test_an_identity_change_is_refused_rather_than_followed(
        self, tmp_path: Path, stub: Install, changed: dict[str, str]
    ) -> None:
        transport = ScriptedPeer(PeerInboxes())

        def swap(played: int) -> None:
            if played == 2:
                transport.announce = greets(ROTATED, **changed)

        stub(swap)
        runner = opened(tmp_path, transport)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_series(timeout=1.0)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert [o.number for o in runner.outcomes] == [1, 2]

    @pytest.mark.parametrize(
        "changed",
        [{"role": ROLE}, {"group_id": "someone-else"}, {"protocol_version": "9.9"}],
        ids=["role", "group", "protocol"],
    )
    def test_a_refused_boundary_leaves_the_client_where_it_was(
        self, tmp_path: Path, stub: Install, changed: dict[str, str]
    ) -> None:
        """Following it half-way would finish the match against someone else."""
        transport = ScriptedPeer(PeerInboxes())

        def swap(played: int) -> None:
            if played == 2:
                transport.announce = greets(ROTATED, **changed)

        stub(swap)
        runner = opened(tmp_path, transport)
        with pytest.raises(MatchAborted):
            runner.play_series(timeout=1.0)
        assert runner.orchestrator.client.opponent_url == AT_THEIRS
        assert runner.peering is not None and runner.peering.sub_game == 2

    def test_a_config_digest_is_not_a_greeting_and_does_not_rotate_anything(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """It is filed as a digest, so the boundary is still waiting for an address."""
        transport = ScriptedPeer(PeerInboxes())

        def swap(played: int) -> None:
            if played == 1:
                transport.announce = {
                    DIGEST_KEY: config_sha256(parameters()),
                    SERIES_KEY: GAME_UID,
                }

        stub(swap)
        runner = opened(tmp_path, transport)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_series(timeout=0.05)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT
        assert runner.orchestrator.client.opponent_url == AT_THEIRS

    def test_a_scent_lock_offer_is_not_a_greeting_either(
        self, tmp_path: Path, stub: Install
    ) -> None:
        transport = ScriptedPeer(PeerInboxes())

        def swap(played: int) -> None:
            if played == 1:
                transport.announce = {
                    SCENT_KEY: {"scent_model": {"emission": {}}},
                    SCENT_DIGEST_KEY: "b" * 64,
                    SERIES_KEY: GAME_UID,
                }

        stub(swap)
        runner = opened(tmp_path, transport)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_series(timeout=0.05)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT
        assert runner.orchestrator.client.opponent_url == AT_THEIRS


class TestABoundaryFailsClosedOnTheAppendixFDeadline:
    """Every way a boundary can go wrong ends in a named cause, never a hang."""

    def refusing(
        self, tmp_path: Path, stub: Install, announce: dict[str, Any] | None, at: int = 1
    ) -> MatchAborted:
        transport = ScriptedPeer(PeerInboxes())

        def swap(played: int) -> None:
            if played == at:
                transport.announce = announce

        stub(swap)
        runner = opened(tmp_path, transport)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_series(timeout=0.05)
        assert runner.orchestrator.client.opponent_url == AT_THEIRS
        return excinfo.value

    def test_the_greeting_deadline_is_the_appendix_f_response_timeout(self) -> None:
        """A boundary with no deadline is the one deadlock that costs nothing to reach."""
        assert float(BOOK_RESPONSE_TIMEOUT) == GREETING_TIMEOUT_SEC

    def test_an_opponent_that_never_re_greets_is_a_timeout(
        self, tmp_path: Path, stub: Install
    ) -> None:
        assert self.refusing(tmp_path, stub, None).cause is TechnicalLoss.TIMEOUT

    def test_the_wait_is_bounded_rather_than_open_ended(
        self, tmp_path: Path, stub: Install
    ) -> None:
        started = time.monotonic()
        self.refusing(tmp_path, stub, None)
        assert time.monotonic() - started < 5.0

    @pytest.mark.parametrize(
        "greeting",
        [
            {"greeting": {"role": OPPONENT, "group_id": "them", "public_url": ROTATED}},
            {"greeting": {"role": OPPONENT, "group_id": "them"}},
            {"greeting": "https://cop-e5f6.ngrok-free.app"},
            {"greeting": {"role": OPPONENT, "group_id": "", "public_url": ROTATED}},
            {"greeting": {}},
        ],
        ids=["no-version", "no-address", "not-an-object", "no-group", "empty"],
    )
    def test_a_malformed_greeting_is_refused(
        self, tmp_path: Path, stub: Install, greeting: dict[str, Any]
    ) -> None:
        """The opponent is untrusted from the first byte, and this is a first byte."""
        assert self.refusing(tmp_path, stub, greeting).cause is TechnicalLoss.ILLEGAL_ACTION

    @pytest.mark.parametrize("url", [PRIVATE, LOOPBACK], ids=["private", "loopback"])
    def test_an_address_that_routes_nowhere_is_refused(
        self, tmp_path: Path, stub: Install, url: str
    ) -> None:
        """We advertise a tunnel, so we cannot reach a peer that does not.

        Adopting it would send every later call to a machine that is not theirs,
        the deadline would expire, and the sub-game would end in a technical loss
        scoring zero for both sides — including the side that made the mistake.
        """
        refused = self.refusing(tmp_path, stub, greets(url))
        assert refused.cause is TechnicalLoss.ILLEGAL_ACTION
        assert "routes nowhere" in refused.detail

    def test_a_stale_greeting_for_a_sub_game_already_played_is_refused(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """Mid-game it is indistinguishable from redirecting our traffic."""
        stub()
        transport = ScriptedPeer(PeerInboxes())
        runner = opened(tmp_path, transport)
        runner.play_sub_game(1, timeout=1.0)
        with pytest.raises(MatchAborted, match="only change between sub-games"):
            runner.rehandshake(1, timeout=1.0)
        assert runner.orchestrator.client.opponent_url == AT_THEIRS

    @pytest.mark.parametrize(
        "conflict_first", [True, False], ids=["conflict-first", "conflict-last"]
    )
    def test_two_conflicting_greetings_in_one_window_are_refused_either_way(
        self, tmp_path: Path, stub: Install, conflict_first: bool
    ) -> None:
        """A newer greeting supersedes an older address, never an older identity.

        Duplicates are ordinary — a retry re-sends the same bytes — so they are
        accepted. What must not happen is a contradiction being superseded away
        by whichever message happened to arrive last, which is the one
        arrangement where a different peer walks into the middle of a series.
        """
        transport = ScriptedPeer(PeerInboxes())
        pair = [greets(ROTATED, group_id="someone-else"), greets(ROTATED)]

        def both(played: int) -> None:
            if played != 1:
                return
            transport.announce = None
            for message in pair if conflict_first else list(reversed(pair)):
                transport.inboxes.negotiate(message)

        stub(both)
        runner = opened(tmp_path, transport)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_series(timeout=1.0)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert runner.orchestrator.client.opponent_url == AT_THEIRS

    def test_an_identical_duplicate_greeting_is_not_a_conflict(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """A retry re-sends bytes; refusing it would lose a series to a re-send."""
        transport = ScriptedPeer(PeerInboxes())

        def twice(played: int) -> None:
            if played == 1:
                transport.inboxes.negotiate(greets(THEIR_URL))

        stub(twice)
        runner = opened(tmp_path, transport)
        assert len(runner.play_series(timeout=1.0)) == BOOK_SERIES


class TestATransientAnnounceFailureCannotHangOrSkipABoundary:
    """If *their* tunnel died, the address we hold died with it."""

    def failing_boundary(self, tmp_path: Path, stub: Install) -> tuple[MatchRunner, ScriptedPeer]:
        """The opening announce lands; the first boundary's spends its whole budget."""
        budget = BOOK_RETRIES + 1
        transport = ScriptedPeer(PeerInboxes(), failing=frozenset(range(2, 2 + budget)))

        def rotate(played: int) -> None:
            if played == 1:
                transport.announce = greets(ROTATED)

        stub(rotate)
        runner = opened(tmp_path, transport)
        runner.play_series(timeout=1.0)
        return runner, transport

    def test_the_budget_spent_is_the_one_appendix_f_documents(
        self, tmp_path: Path, stub: Install
    ) -> None:
        _, transport = self.failing_boundary(tmp_path, stub)
        # opening announce, then the whole budget, then the re-announce that landed.
        spent = 1 + (BOOK_RETRIES + 1) + 1 + len(BOUNDARIES[1:])
        assert transport.tools.count("negotiate") == spent

    def test_the_boundary_is_crossed_rather_than_skipped(
        self, tmp_path: Path, stub: Install
    ) -> None:
        runner, _ = self.failing_boundary(tmp_path, stub)
        assert runner.peering is not None and runner.peering.sub_game == BOOK_SERIES
        assert [o.number for o in runner.outcomes] == list(range(1, BOOK_SERIES + 1))

    def test_the_failure_is_recorded_rather_than_swallowed_silently(
        self, tmp_path: Path, stub: Install
    ) -> None:
        runner, _ = self.failing_boundary(tmp_path, stub)
        assert "announce-failed" in runner.orchestrator.heartbeats

    def test_the_second_announcement_goes_to_the_address_we_just_adopted(
        self, tmp_path: Path, stub: Install
    ) -> None:
        """Announcing again at the dead address would strand them for good."""
        _, transport = self.failing_boundary(tmp_path, stub)
        assert transport.where("negotiate")[: 2 + BOOK_RETRIES] == [AT_THEIRS] * (2 + BOOK_RETRIES)
        assert transport.where("negotiate")[2 + BOOK_RETRIES] == AT_ROTATED

    def test_the_series_still_finishes_on_the_rotated_address(
        self, tmp_path: Path, stub: Install
    ) -> None:
        runner, transport = self.failing_boundary(tmp_path, stub)
        assert transport.where("receive_turn") == [AT_THEIRS] + [AT_ROTATED] * 5
        assert runner.orchestrator.client.opponent_url == AT_ROTATED


# --- the same thing over two real servers -----------------------------------

STEPS = 2


@dataclass
class Live:
    """One agent in the live series: its server, its mailboxes and its runner."""

    role: str
    port: int
    inboxes: PeerInboxes
    runner: MatchRunner
    transport: FastMcpTransport


def a_live_side(role: str, port: int, opponent_port: int, where: Path) -> Live:
    inboxes = PeerInboxes()
    transport = FastMcpTransport()
    client = OpponentClient(
        transport=transport,
        settings=ClientSettings(
            opponent_url=f"http://127.0.0.1:{opponent_port}/mcp",
            response_timeout_sec=20.0,
            retry_backoff_sec=1.0,
        ),
    )
    runner = MatchRunner(
        orchestrator=Orchestrator(inboxes=inboxes, client=client, role=role),
        declaration=build_declaration(role, GAME_ID, GAME_UID),
        parameters=parameters(),
        brain=PlaysItsOwnPiece("cop" if role == "police" else "thief"),  # type: ignore[arg-type]
        axes=AXES,
        start=BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0),
        max_steps=STEPS,
        directory=where / role,
        now=lambda: WHEN,
    )
    return Live(role=role, port=port, inboxes=inboxes, runner=runner, transport=transport)


@pytest.fixture(scope="module")
def series(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Live, Live]]:
    """A whole six-sub-game series between two real peers, boundaries and all.

    Both sides run at once, and both re-handshake at every boundary — each
    announcing before it listens, which is the ordering that keeps two polite
    peers from waiting for each other forever. A deadlock here is the failure
    this fixture exists to catch, so the join has a deadline and the test fails
    rather than hangs.
    """
    where = tmp_path_factory.mktemp("series")
    our_port, their_port = free_port(), free_port()
    us = a_live_side(ROLE, our_port, their_port, where)
    them = a_live_side(OPPONENT, their_port, our_port, where)

    for side in (us, them):
        host = build(side.inboxes, name=f"{side.role}-series")
        threading.Thread(
            target=serve,
            args=(host, ServerSettings(port=side.port, host="127.0.0.1")),
            daemon=True,
        ).start()
    wait_for(our_port)
    wait_for(their_port)

    failures: dict[str, BaseException] = {}

    def run(side: Live) -> None:
        try:
            ours = side.runner.orchestrator.greeting(f"http://127.0.0.1:{side.port}/mcp", GROUP)
            side.runner.peering = side.runner.orchestrator.open_series(
                ours, side.runner.directory, GAME_ID, timeout=25.0
            )
            side.runner.agree(timeout=25.0)
            side.runner.play_series(timeout=25.0)
        except BaseException as exc:  # noqa: BLE001 - reported below, not swallowed
            failures[side.role] = exc

    threads = [threading.Thread(target=run, args=(side,)) for side in (us, them)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300.0)
    for thread in threads:
        assert not thread.is_alive(), "a side never finished; the series deadlocked"
    if failures:
        pytest.fail("; ".join(f"{role}: {exc!r}" for role, exc in failures.items()))

    yield us, them
    for side in (us, them):
        side.transport.close()


class TestTwoRealPeersPlayASixSubGameSeriesAcrossFiveBoundaries:
    def test_both_sides_played_all_six(self, series: tuple[Live, Live]) -> None:
        for side in series:
            assert [o.number for o in side.runner.outcomes] == list(range(1, BOOK_SERIES + 1))

    def test_neither_side_deadlocked_re_handshaking_against_the_other(
        self, series: tuple[Live, Live]
    ) -> None:
        """Both announce before either listens; the fixture proves it terminates."""
        for side in series:
            assert side.runner.peering is not None
            assert side.runner.peering.sub_game == BOOK_SERIES

    def test_nothing_was_rejected_at_either_door(self, series: tuple[Live, Live]) -> None:
        for side in series:
            assert side.inboxes.rejected == []

    def test_no_boundary_had_to_be_retried_into(self, series: tuple[Live, Live]) -> None:
        """The retryable refusal is the net, and across six sub-games nothing fell.

        Each side binds its mailboxes *before* it announces the boundary, and
        the opponent only opens a sub-game after that announcement reaches it,
        so every packet of sub-game ``n`` arrives at a door already on ``n``.
        A deferral here would mean the ordering had a gap in it — recoverable,
        because the sender spends its budget rather than giving up, but no
        longer the guarantee this asserts.
        """
        for side in series:
            assert side.inboxes.deferred == []

    def test_every_sub_game_audited_clean(self, series: tuple[Live, Live]) -> None:
        for side in series:
            assert side.runner.opponent_played_fairly, side.runner.failures()

    def test_the_scent_lock_survives_every_boundary(self, series: tuple[Live, Live]) -> None:
        """A boundary that reset the series identity would void the lock."""
        us, them = series
        assert us.runner.scent_lock is not None
        assert us.runner.scent_lock == them.runner.scent_lock

    def test_the_config_digest_is_still_the_one_both_sides_agreed(
        self, series: tuple[Live, Live]
    ) -> None:
        us, them = series
        digest = config_sha256(parameters())
        for side in (us, them):
            assert {log.config_sha256 for log in self.logs(side)} == {digest}

    @staticmethod
    def logs(side: Live) -> list[MatchLog]:
        return [outcome.log for outcome in side.runner.outcomes]

    def test_every_log_is_numbered_for_its_own_sub_game(self, series: tuple[Live, Live]) -> None:
        for side in series:
            assert [log.sub_game for log in self.logs(side)] == list(range(1, BOOK_SERIES + 1))
            assert {log.game_uid for log in self.logs(side)} == {GAME_UID}

    def test_every_log_stamps_verified_ok(self, series: tuple[Live, Live], tmp_path: Path) -> None:
        for side in series:
            for log in self.logs(side):
                written = log.write(tmp_path / f"{side.role}-{log.sub_game}")
                assert walk(load(written)).stamp is Stamp.VERIFIED_OK, str(log.sub_game)

    def test_the_turn_ledger_was_reset_per_sub_game_and_nothing_was_dropped(
        self, series: tuple[Live, Live]
    ) -> None:
        """Step 1 recurs in every sub-game; a ledger kept across them refuses it."""
        for side in series:
            assert side.inboxes.duplicates == []
            assert sorted(self.logs(side)[0].entries) == list(range(1, STEPS + 1))

    def test_the_artefacts_of_the_whole_series_are_coherent(
        self, series: tuple[Live, Live], tmp_path: Path
    ) -> None:
        from test_localhost_match import REPOS

        for side in series:
            runner = side.runner
            result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
            artefacts = runner.artefacts(result)
            assert len(artefacts.configs) == BOOK_SERIES
            assert len(artefacts.logs) == BOOK_SERIES
            assert artefacts.check().coherent, str(artefacts.check())

    def test_the_declaration_records_the_addresses_the_last_boundary_agreed(
        self, series: tuple[Live, Live]
    ) -> None:
        for side in series:
            written = json.loads(
                (side.runner.directory / f"declaration_{GAME_ID}.json").read_text()
            )
            for role in (ROLE, OPPONENT):
                assert written["mcp_addresses"][role]["since_sub_game"] == BOOK_SERIES

    def test_the_two_sides_stayed_in_separate_processes_sharing_only_the_wire(
        self, series: tuple[Live, Live]
    ) -> None:
        """Sharing live state disqualifies the solution even if the game works."""
        us, them = series
        assert us.inboxes is not them.inboxes
        assert us.runner.orchestrator.client is not them.runner.orchestrator.client


def test_a_free_port_is_actually_free() -> None:
    """Guards the fixture above: a port in use would look like a deadlock."""
    port = free_port()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
