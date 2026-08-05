"""Two agents, two servers, two sockets, one real sub-game.

The thing this project has never done. A cop and a thief, each with its own
FastMCP server on its own port, its own inboxes, its own ceremony and its own
log, talking only over HTTP — and at the end, two logs that the Replay App
stamps ``Verified OK`` independently.

Both sides are built from *this* package with different roles, because a test in
the cop repository may not import the thief one. That is not a shortcut:
:class:`~thief_agent.runtime.subgame.SubGame` takes its role as a parameter and
shares nothing between the two instances here except the wire.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.rules import legal_moves
from thief_agent.infra.artefacts import ArtefactSet
from thief_agent.infra.config_file import lock
from thief_agent.infra.declaration import Endpoints, MatchDeclaration, Team
from thief_agent.infra.declaration import build as declare
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.match_log import MatchLog
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.mcp_server import ServerSettings, build, serve
from thief_agent.infra.mcp_transport import FastMcpTransport
from thief_agent.infra.report import Report, Repositories, SubGameResult
from thief_agent.infra.step_zero import Hardware, Provenance
from thief_agent.runtime.peer import McpPeer
from thief_agent.runtime.subgame import SubGame
from thief_agent.strategy.base import Decision
from thief_agent.ui.replay import load
from thief_agent.ui.verdict import Stamp, walk


def parameters() -> dict[str, Any]:
    body = json.loads((Path(__file__).resolve().parent.parent / "config/game.json").read_text())
    assert isinstance(body, dict)
    return body


REPOS = Repositories(
    cop_repo="https://github.com/Mhmdabad/police_agent",
    thief_repo="https://github.com/Mhmdabad/theif_agent",
    opponent_cop_repo="https://github.com/other/police",
    opponent_thief_repo="https://github.com/other/thief",
)


def build_declaration(role: str, game_id: str, uid: str) -> MatchDeclaration:
    return declare(
        game_id=game_id,
        game_uid=uid,
        role=role,
        us=Team(
            name="uoh26-cops",
            members=("Mohammed Abad",),
            cop_repo=REPOS.cop_repo,
            thief_repo=REPOS.thief_repo,
        ),
        them=Team(
            name="uoh26-others",
            members=("Someone",),
            cop_repo=REPOS.opponent_cop_repo,
            thief_repo=REPOS.opponent_thief_repo,
        ),
        endpoints=Endpoints(ours="https://a.ngrok.io/mcp", theirs="https://b.ngrok.io/mcp"),
        hardware=Hardware(
            os_name="Linux",
            logical_cores=8,
            cpu_max_mhz=3600.0,
            ram_mb=16384,
            gpu=None,
            vram_mb=None,
            llm_model="claude-haiku-4-5",
        ),
        provenance=Provenance(
            code_version="1.0.0",
            group_name="uoh26-cops",
            sub_game=1,
            github_commit="a" * 40,
            dirty=False,
        ),
        llm_model="claude-haiku-4-5",
        token_ceiling=200_000,
        started_at="2026-08-05T11:00:00Z",
        key=None,
    )


def result_for(side: "Side", game_id: str, uid: str) -> Report:
    return Report(
        game_id=game_id,
        game_uid=uid,
        role=side.role,
        team="uoh26-cops",
        opponent_team="uoh26-others",
        repositories=REPOS,
        sub_games=(SubGameResult(sub_game=1, cop_score=0, thief_score=0, commit_hash="a" * 40),),
        total_tokens=0,
        agreed=True,
    )


WHEN = "2026-08-05T11:00:00+00:00"
AXES = AxisConvention()
STEPS = 3


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


class PlaysItsOwnPiece:
    """A brain that picks any legal move for whichever agent it is playing.

    The cop repository ships only a ``ThiefBrain``, which chooses moves for the
    *cop*. Driving the thief side with it produces moves that are legal for one
    piece and illegal for the other — which is what the first run of this test
    reported. The point here is the wire and the ceremony, not the strategy, so
    the thief side gets the simplest brain that plays by the rules.
    """

    def __init__(self, agent: str) -> None:
        self.agent = agent

    def decide(self, state: BoardState, **context: object) -> Decision:
        options = legal_moves(state, self.agent, AXES)  # type: ignore[arg-type]
        return Decision(action=MoveAction(move=options[0]), hint="", intent="truth")


@dataclass
class Side:
    """One agent: its server, its inboxes, its log and its sub-game."""

    role: str
    port: int
    inboxes: PeerInboxes
    log: MatchLog
    game: SubGame


def a_side(role: str, port: int, opponent_port: int) -> Side:
    inboxes = PeerInboxes()
    log = MatchLog(
        game_id="uoh26-s82kma9e",
        sub_game=1,
        role=role,
        game_uid="u-0001",
        config_sha256="c" * 64,
    )
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
        brain=PlaysItsOwnPiece("cop" if role == "police" else "thief"),  # type: ignore[arg-type]
        peer=McpPeer(role=role, client=client, inboxes=inboxes, now=WHEN, timeout=25.0),
        log=log,
        state=BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0),
        axes=AXES,
        max_steps=STEPS,
        now=lambda: WHEN,
    )
    return Side(role=role, port=port, inboxes=inboxes, log=log, game=game)


@pytest.fixture(scope="module")
def played(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Side, Side, Path]]:
    """Run one real sub-game between two real servers, once for this module."""
    cop_port, thief_port = free_port(), free_port()
    cop = a_side("thief", cop_port, thief_port)
    thief = a_side("police", thief_port, cop_port)

    for side in (cop, thief):
        host = build(side.inboxes, name=f"{side.role}-under-test")
        threading.Thread(
            target=serve,
            args=(host, ServerSettings(port=side.port, host="127.0.0.1")),
            daemon=True,
        ).start()
    wait_for(cop_port)
    wait_for(thief_port)

    # Both sides must run at once: each blocks waiting for the other's messages.
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

    yield cop, thief, tmp_path_factory.mktemp("artefacts")


class TestTheMatchActuallyHappened:
    def test_both_sides_played_every_step(self, played: tuple[Side, Side, Path]) -> None:
        cop, thief, _ = played
        assert sorted(cop.log.entries) == [1, 2, 3]
        assert sorted(thief.log.entries) == [1, 2, 3]

    def test_nothing_was_rejected(self, played: tuple[Side, Side, Path]) -> None:
        """A refusal here is two peers disagreeing about the protocol."""
        cop, thief, _ = played
        assert cop.inboxes.rejected == []
        assert thief.inboxes.rejected == []

    def test_each_side_holds_the_others_commitments(self, played: tuple[Side, Side, Path]) -> None:
        cop, thief, _ = played
        for step in (1, 2, 3):
            assert cop.game.ceremony.at(step).theirs is not None
            assert thief.game.ceremony.at(step).theirs is not None

    def test_the_digests_match_across_the_wire(self, played: tuple[Side, Side, Path]) -> None:
        """What the cop committed is what the thief received, byte for byte."""
        cop, thief, _ = played
        for step in (1, 2, 3):
            ours = cop.game.ceremony.at(step).ours
            theirs = thief.game.ceremony.at(step).theirs
            assert ours is not None and theirs is not None
            assert ours.commit == theirs.commit


class TestBothLogsVerify:
    def test_the_cops_log_stamps_verified_ok(self, played: tuple[Side, Side, Path]) -> None:
        cop, _, where = played
        result = walk(load(cop.log.write(where / "cop")))
        assert result.stamp is Stamp.VERIFIED_OK, str(result)

    def test_the_thiefs_log_stamps_verified_ok(self, played: tuple[Side, Side, Path]) -> None:
        _, thief, where = played
        result = walk(load(thief.log.write(where / "police")))
        assert result.stamp is Stamp.VERIFIED_OK, str(result)

    def test_both_are_fully_re_verifiable(self, played: tuple[Side, Side, Path]) -> None:
        cop, thief, _ = played
        assert cop.log.verifiable().complete
        assert thief.log.verifiable().complete

    def test_no_nonce_left_early(self, played: tuple[Side, Side, Path]) -> None:
        cop, thief, _ = played
        assert cop.log.unopened() == []
        assert thief.log.unopened() == []


class TestTheAcknowledgementLimitIsVisible:
    def test_this_opponent_returns_a_bare_ack(self, played: tuple[Side, Side, Path]) -> None:
        """Our own ``receive_turn`` answers ``{"ok": true}`` with no digest.

        So even against ourselves the acknowledgement carries no proof of
        *which* commitment they hold. Recorded rather than assumed away — this
        is the limit the peer module documents, observed against a real server.
        """
        cop, _, _ = played
        peer = cop.game.peer
        assert isinstance(peer, McpPeer)
        assert peer.reference_acks == [1, 2, 3]


class TestEachSideAuditsTheOther:
    """The question the nonces exist to answer, over a real wire."""

    def test_the_cop_finds_the_thief_honest(self, played: tuple[Side, Side, Path]) -> None:
        cop, _, _ = played
        result = cop.game.audit()
        assert result.clean, str(result)
        assert result.checked == STEPS

    def test_the_thief_finds_the_cop_honest(self, played: tuple[Side, Side, Path]) -> None:
        _, thief, _ = played
        result = thief.game.audit()
        assert result.clean, str(result)
        assert result.checked == STEPS

    def test_both_kept_the_board_each_step_was_sealed_against(
        self, played: tuple[Side, Side, Path]
    ) -> None:
        """Two peers who disagreed about the board could not audit each other."""
        cop, thief, _ = played
        for step in range(1, STEPS + 1):
            assert cop.game.sealed_states[step] == thief.game.sealed_states[step]

    def test_each_received_the_others_nonces(self, played: tuple[Side, Side, Path]) -> None:
        cop, thief, _ = played
        assert cop.game.their_final is not None
        assert thief.game.their_final is not None
        assert sorted(cop.game.their_final.nonces) == [1, 2, 3]


class TestTheMatchProducesItsOwnEvidence:
    """A played match must write the four files, or it produced nothing to submit."""

    @staticmethod
    def artefacts_for(side: Side) -> ArtefactSet:
        uid, game_id = side.log.game_uid, side.log.game_id
        return ArtefactSet(
            declaration=build_declaration(side.role, game_id, uid),
            configs=(
                lock(
                    game_id=game_id,
                    game_uid=uid,
                    sub_game=1,
                    parameters=parameters(),
                    agreed_between=("uoh26-cops", "uoh26-others"),
                ),
            ),
            logs=(side.log,),
            result=result_for(side, game_id, uid),
        )

    def test_the_set_is_coherent(self, played: tuple[Side, Side, Path]) -> None:
        cop, _, _ = played
        coherence = self.artefacts_for(cop).check()
        assert coherence.coherent, str(coherence)

    def test_all_four_kinds_are_written(self, played: tuple[Side, Side, Path]) -> None:
        cop, _, where = played
        written = self.artefacts_for(cop).write(where / "cop-artefacts")
        assert {path.name for path in written} == {
            "declaration_uoh26-s82kma9e.json",
            "config_uoh26-s82kma9e_g01.json",
            "log_uoh26-s82kma9e_g01.json",
            "result_uoh26-s82kma9e.json",
        }

    def test_the_written_log_still_stamps_verified_ok(
        self, played: tuple[Side, Side, Path]
    ) -> None:
        """The evidence survives being written as part of a set."""
        cop, _, where = played
        written = self.artefacts_for(cop).write(where / "cop-set")
        log = next(path for path in written if path.name.startswith("log_"))
        assert walk(load(log)).stamp is Stamp.VERIFIED_OK

    def test_the_result_records_the_commit_the_game_was_played_at(
        self, played: tuple[Side, Side, Path]
    ) -> None:
        cop, _, where = played
        written = self.artefacts_for(cop).write(where / "cop-commit")
        result = next(path for path in written if path.name.startswith("result_"))
        body = json.loads(result.read_text())
        assert body["sub_games"][0]["commit_hash"]
        assert len(body["repositories"]) == 4

    def test_both_sides_produce_sets_that_agree_on_the_match(
        self, played: tuple[Side, Side, Path]
    ) -> None:
        """One game_uid, one game_id, two independent sets of evidence."""
        cop, thief, _ = played
        ours, theirs = self.artefacts_for(cop), self.artefacts_for(thief)
        assert ours.game_uid == theirs.game_uid
        assert ours.game_id == theirs.game_id
        assert ours.check().coherent and theirs.check().coherent
