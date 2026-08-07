"""Two agents, two servers, two sockets — and a scent field that crosses them.

``test_localhost_match`` proved the ceremony survives a real wire. This proves
the pheromone layer does, which is a different claim: the field is the one
payload in the protocol that is *computed* on one side and *consumed* on the
other, so every place it can be lost is a place where both peers keep playing
and one of them silently stops seeing anything.

It has to be an end-to-end test rather than a unit one. A field that is emitted
but not sealed, sealed but not sent, sent but not parsed, or parsed but not
absorbed produces a working match with an empty belief map every time — and
each of those four is invisible from either side alone.

Both sides are built from *this* package with different roles, because a test
in the cop repository may not import the thief one. Nothing is shared between
the two instances except the socket.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState, Move
from thief_agent.domain.scent_audit import trail_snapshots
from thief_agent.infra.ceremony import Commitment
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.match_log import MatchLog
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.mcp_server import ServerSettings, build, serve
from thief_agent.infra.mcp_transport import FastMcpTransport
from thief_agent.runtime.peer import McpPeer
from thief_agent.runtime.subgame import SubGame
from thief_agent.strategy.base import Decision

WHEN = "2026-08-05T11:00:00+00:00"
AXES = AxisConvention()
STEPS = 3
GRID = 8
COP_START = (0, 0)
THIEF_START = (6, 5)
SCRIPT: dict[str, list[Move]] = {"police": ["S", "S", "S"], "thief": ["N", "N", "N"]}
"""Both sides march, so the trail is a moving hill rather than a fixed blob.

A stationary emitter would pass every assertion below while proving nothing
about whether decay ran, since a re-emitted centre is 0.9 either way.
"""


def start_board() -> BoardState:
    return BoardState(
        grid_size=GRID, cop=COP_START, thief=THIEF_START, barriers=frozenset(), step=0
    )


def cells_walked(start: tuple[int, int], moves: list[Move]) -> list[tuple[int, int]]:
    """Where a marching agent stands after each of its moves."""
    delta = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1), "STAY": (0, 0)}
    here, walked = start, []
    for move in moves:
        drow, dcol = delta[move]
        here = (here[0] + drow, here[1] + dcol)
        walked.append(here)
    return walked


class Marches:
    """A brain that walks a fixed line, so every expected field is arithmetic."""

    def __init__(self, moves: list[Move]) -> None:
        self.moves = moves
        self.played = 0

    def decide(self, state: BoardState, **context: object) -> Decision:
        move = self.moves[min(self.played, len(self.moves) - 1)]
        self.played += 1
        return Decision(action=MoveAction(move=move), hint="over there", intent="truth")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for(port: int) -> None:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    pytest.fail(f"nothing came up on {port}")  # pragma: no cover


@dataclass
class Side:
    role: str
    port: int
    inboxes: PeerInboxes
    game: SubGame

    @property
    def sent(self) -> list[dict[str, float] | None]:
        """The field we put on the wire at each step."""
        return [self.game.ceremony.at(step).revealed_ours.scent for step in range(1, STEPS + 1)]  # type: ignore[union-attr]

    @property
    def received(self) -> list[dict[str, float] | None]:
        """The field that came off the wire at each step."""
        return [self.game.ceremony.at(step).revealed_theirs.scent for step in range(1, STEPS + 1)]  # type: ignore[union-attr]


def a_side(role: str, port: int, opponent_port: int) -> Side:
    inboxes = PeerInboxes(game_uid="u-0001", sub_game=1)
    client = OpponentClient(
        transport=FastMcpTransport(),
        settings=ClientSettings(
            opponent_url=f"http://127.0.0.1:{opponent_port}/mcp",
            response_timeout_sec=20.0,
            max_retries=3,
            retry_backoff_sec=5.0,
        ),
    )
    game = SubGame(
        role=role,
        brain=Marches(SCRIPT[role]),  # type: ignore[arg-type]
        peer=McpPeer(
            role=role,
            client=client,
            inboxes=inboxes,
            game_uid="u-0001",
            sub_game=1,
            now=WHEN,
            timeout=25.0,
        ),
        log=MatchLog(
            game_id="uoh26-s82kma9e",
            sub_game=1,
            role=role,
            game_uid="u-0001",
            config_sha256="c" * 64,
        ),
        state=start_board(),
        axes=AXES,
        max_steps=STEPS,
        now=lambda: WHEN,
    )
    return Side(role=role, port=port, inboxes=inboxes, game=game)


@pytest.fixture(scope="module")
def played() -> Iterator[tuple[Side, Side]]:
    """One real sub-game between two real servers, once for this module."""
    cop_port, thief_port = free_port(), free_port()
    cop, thief = a_side("police", cop_port, thief_port), a_side("thief", thief_port, cop_port)

    for side in (cop, thief):
        host = build(side.inboxes, name=f"{side.role}-scent-under-test")
        threading.Thread(
            target=serve,
            args=(host, ServerSettings(port=side.port, host="127.0.0.1")),
            daemon=True,
        ).start()
    wait_for(cop_port)
    wait_for(thief_port)

    failures: dict[str, BaseException] = {}

    def run(side: Side) -> None:
        try:
            side.game.play()
        except BaseException as exc:  # noqa: BLE001 - reported below, not swallowed
            failures[side.role] = exc

    threads = [threading.Thread(target=run, args=(side,)) for side in (cop, thief)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120.0)

    if failures:
        pytest.fail("; ".join(f"{role}: {exc!r}" for role, exc in failures.items()))
    for thread in threads:
        assert not thread.is_alive(), "a side never finished; the match deadlocked"

    yield cop, thief


class TestTheFieldActuallyCrossesTheWire:
    def test_each_side_receives_exactly_one_identical_hint_per_step(
        self, played: tuple[Side, Side]
    ) -> None:
        cop, thief = played
        assert cop.game.received_hints == {step: "over there" for step in range(1, STEPS + 1)}
        assert thief.game.received_hints == {step: "over there" for step in range(1, STEPS + 1)}

    def test_both_sides_transmitted_a_non_empty_field_every_step(
        self, played: tuple[Side, Side]
    ) -> None:
        for side in played:
            assert all(field for field in side.sent), f"{side.role} sent nothing"

    def test_each_side_received_what_the_other_sent(self, played: tuple[Side, Side]) -> None:
        """Byte for byte, through JSON, a socket and two parsers."""
        cop, thief = played
        assert cop.received == thief.sent
        assert thief.received == cop.sent

    def test_the_field_survives_the_wire_unrounded(self, played: tuple[Side, Side]) -> None:
        """It is hashed, so a float perturbed in transit is a forgery verdict."""
        cop, _ = played
        for field in cop.received:
            assert field == json.loads(json.dumps(field))


class TestNothingIsGivenAwayInPhaseOne:
    def test_the_commitment_carries_no_field(self, played: tuple[Side, Side]) -> None:
        """A fresh emission peaks on the emitter's cell — that is the position."""
        cop, _ = played
        for step in range(1, STEPS + 1):
            commitment = cop.game.ceremony.at(step).ours
            assert commitment is not None
            assert "scent" not in commitment.to_dict()

    def test_the_turn_message_we_put_on_the_wire_has_an_empty_smell_grid(self) -> None:
        """Driven through the real client, not asserted about the real client.

        The reference dialect's ``TurnMessage`` has a slot for the field and
        travels with the commitment. Ours goes out empty, every time, and this
        records what was actually emitted rather than what was intended.
        """
        sent: list[tuple[str, dict[str, Any]]] = []

        class Recorder:
            def call(
                self, url: str, tool: str, payload: dict[str, Any], timeout: float
            ) -> dict[str, Any]:
                sent.append((tool, payload))
                return {"ok": True}

        peer = McpPeer(
            role="police",
            client=OpponentClient(
                Recorder(), ClientSettings(opponent_url="http://127.0.0.1:1/mcp")
            ),
            inboxes=PeerInboxes(),
            game_uid="u-0001",
            sub_game=1,
            now=WHEN,
        )
        peer.send_commit(Commitment(step=1, sender="police", commit="a" * 64, timestamp=WHEN))
        tool, payload = sent[0]
        assert tool == "receive_turn"
        assert payload["message"]["hint"] == ""
        assert payload["message"]["smell_grid"] == {}

    def test_no_nonce_travels_with_the_field(self, played: tuple[Side, Side]) -> None:
        cop, _ = played
        for step in range(1, STEPS + 1):
            opened = cop.game.ceremony.at(step).revealed_theirs
            assert opened is not None
            assert "nonce" not in json.dumps(opened.to_dict())


class TestTheReceiverActuallyUsesIt:
    def test_the_opponents_trail_is_absorbed(self, played: tuple[Side, Side]) -> None:
        cop, _ = played
        assert cop.game.scent.opponent.values
        peak = cop.game.scent.opponent.strongest()
        assert peak is not None
        assert peak[1] == THIEF_START[1]  # the thief marched north, never sideways

    def test_our_own_field_is_never_absorbed_as_theirs(self, played: tuple[Side, Side]) -> None:
        """The cop marches down column 0; the thief never leaves column 5."""
        cop, _ = played
        assert cop.game.scent.own.values
        assert all(cell[1] <= 2 for cell in cop.game.scent.own.values)
        assert all(cell[1] >= 3 for cell in cop.game.scent.opponent.values)

    def test_the_belief_heatmap_moved(self, played: tuple[Side, Side]) -> None:
        """The GUI paints this object, so a still heatmap is a still GUI."""
        for side in played:
            assert side.game.belief.concentration() > 0.0
            assert side.game.belief.total() == pytest.approx(1.0)

    def test_the_belief_points_at_the_opponent_rather_than_at_us(
        self, played: tuple[Side, Side]
    ) -> None:
        cop, thief = played
        cop_peak, thief_peak = cop.game.belief.most_likely(), thief.game.belief.most_likely()
        assert cop_peak is not None and thief_peak is not None
        assert cop_peak[1] >= 3  # the thief's column, not the cop's
        assert thief_peak[1] <= 2  # the cop's column, not the thief's

    def test_the_live_view_never_receives_the_true_cell(self) -> None:
        """FR-7.11 again, at the boundary the belief is handed across."""
        import inspect

        from thief_agent.ui.view import render

        assert set(inspect.signature(render).parameters) == {
            "state",
            "belief",
            "role",
            "ours",
            "our_glyph",
            "opponent_glyph",
        }


class TestDecayRanOncePerFullTurn:
    def test_the_transmitted_trail_matches_the_model_exactly(
        self, played: tuple[Side, Side]
    ) -> None:
        """Re-derived from the script, by the same model an auditor would use.

        Two decays a turn, or none, changes every value after the first — so
        this is the assertion that the boundary is the full turn rather than
        the half-move.
        """
        cop, thief = played
        assert cop.sent == trail_snapshots(cells_walked(COP_START, SCRIPT["police"]), GRID)
        assert thief.sent == trail_snapshots(cells_walked(THIEF_START, SCRIPT["thief"]), GRID)

    def test_a_cell_left_behind_fades_rather_than_vanishing(
        self, played: tuple[Side, Side]
    ) -> None:
        _, thief = played
        left_behind = f"{THIEF_START[0]},{THIEF_START[1]}"
        strengths = [field[left_behind] for field in thief.sent if field]
        assert strengths == sorted(strengths, reverse=True)
        assert strengths[-1] > 0.0


class TestBothSidesAuditEachOtherClean:
    def test_an_honest_match_produces_no_findings(self, played: tuple[Side, Side]) -> None:
        for side in played:
            result = side.game.audit()
            assert result.clean, f"{side.role}: {result}"
            assert result.checked == STEPS

    def test_nothing_was_rejected_at_either_door(self, played: tuple[Side, Side]) -> None:
        """A refusal here is two peers disagreeing about the wire contract."""
        for side in played:
            assert side.inboxes.rejected == []

    def test_the_log_carries_the_field_the_commitment_covers(
        self, played: tuple[Side, Side]
    ) -> None:
        """A third party must be able to re-verify the trail from the file."""
        cop, _ = played
        for step in range(1, STEPS + 1):
            entry = cop.game.log.entries[step]
            assert entry.reveal is not None
            assert entry.reveal["scent"] == cop.sent[step - 1]


def _moves() -> list[Move]:
    """Keeps the script honest against the type the board actually accepts."""
    return ["N", "S", "E", "W", "STAY"]


class TestTheScriptIsPlayable:
    def test_every_scripted_move_is_a_real_move(self) -> None:
        assert all(move in _moves() for side in SCRIPT.values() for move in side)
