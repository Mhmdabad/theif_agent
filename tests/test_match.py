"""The match runner's own steps, without a socket.

`test_localhost_match` proves it composes over a real wire. This covers the
steps that a passing match never exercises — the config digest refused, the
audit that comes back dirty — and it is where the runner's own decisions live.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from test_localhost_match import REPOS, build_declaration, parameters  # noqa: E402
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.scoring import Outcome, scores_for
from thief_agent.infra.ceremony import AuditResult, Verdict
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.match_log import MatchLog
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.report import Report, SubGameResult
from thief_agent.runtime.driver import _cell, _now, _team
from thief_agent.runtime.match import MatchRunner, SubGameOutcome
from thief_agent.runtime.orchestrator import MatchAborted, Orchestrator
from thief_agent.runtime.subgame import Played
from thief_agent.strategy.thief_brain import ThiefBrain

WHEN = "2026-08-05T12:00:00+00:00"
AXES = AxisConvention()


class Answering:
    """A transport that replies however the test wants."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append((tool, payload))
        return self.reply


def a_runner(tmp_path: Path, reply: dict[str, Any] | None = None) -> MatchRunner:
    transport = Answering(reply if reply is not None else {"ok": True})
    return MatchRunner(
        orchestrator=Orchestrator(
            inboxes=PeerInboxes(),
            client=OpponentClient(
                transport=transport,
                settings=ClientSettings(opponent_url="http://127.0.0.1:1/mcp"),
            ),
            role="thief",
        ),
        declaration=build_declaration("thief", "uoh26-s82kma9e", "u-0001"),
        parameters=parameters(),
        brain=ThiefBrain(),
        axes=AXES,
        start=BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0),
        sub_games=1,
        max_steps=2,
        directory=tmp_path,
        now=lambda: WHEN,
    )


def an_outcome(number: int, clean: bool = True, captured: bool = False) -> SubGameOutcome:
    log = MatchLog(
        game_id="uoh26-s82kma9e",
        sub_game=number,
        role="thief",
        game_uid="u-0001",
        config_sha256="c" * 64,
    )
    audit = (
        AuditResult(verdict=Verdict.CLEAN, checked=2)
        if clean
        else AuditResult(
            verdict=Verdict.FORGED,
            checked=2,
            failures=("step 2: committed abc… but the revealed move produces def…",),
        )
    )
    board = BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=2)
    return SubGameOutcome(
        number=number,
        played=Played(2, board, captured, "capture" if captured else "step limit reached", audit),
        audit=audit,
        log=log,
    )


class TestAgreeingTheConfigComesFirst:
    def test_a_matching_digest_lets_the_match_start(self, tmp_path: Path) -> None:
        assert len(a_runner(tmp_path).agree()) == 64

    def test_the_digest_is_of_the_parameters_we_are_actually_playing(self, tmp_path: Path) -> None:
        """Advertising one we are not enforcing is indistinguishable from cheating."""
        from thief_agent.shared.config import config_sha256

        runner = a_runner(tmp_path)
        assert runner.agree() == config_sha256(runner.parameters)

    def test_a_refusal_aborts_before_a_single_move(self, tmp_path: Path) -> None:
        """Two peers with different parameters are playing different games."""
        runner = a_runner(tmp_path, reply={"ok": False, "detail": "digest mismatch"})
        with pytest.raises(MatchAborted):
            runner.agree()

    def test_nothing_was_played_when_it_refuses(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path, reply={"ok": False, "detail": "no"})
        with pytest.raises(MatchAborted):
            runner.agree()
        assert runner.outcomes == []


class TestTheConfigItLocks:
    def test_one_per_sub_game(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        assert runner.config_for(2).sub_game == 2

    def test_it_names_both_teams(self, tmp_path: Path) -> None:
        locked = a_runner(tmp_path).config_for(1)
        assert set(locked.agreed_between) == {"uoh26-cops", "uoh26-others"}

    def test_it_carries_the_shared_uid(self, tmp_path: Path) -> None:
        assert a_runner(tmp_path).config_for(1).game_uid == "u-0001"


class TestWhatTheMatchConcludesAboutTheOpponent:
    def test_a_clean_series_is_clean(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1), an_outcome(2)])
        assert runner.opponent_played_fairly
        assert runner.failures() == []

    def test_one_forged_sub_game_taints_the_match(self, tmp_path: Path) -> None:
        """FR-7.16: there is nothing to agree about a series that does not open."""
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1), an_outcome(2, clean=False)])
        assert not runner.opponent_played_fairly

    def test_the_findings_name_their_sub_game(self, tmp_path: Path) -> None:
        """An accusation without a location is one nobody can check."""
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1), an_outcome(2, clean=False)])
        assert runner.failures() == [
            "sub-game 2: step 2: committed abc… but the revealed move produces def…"
        ]

    def test_an_empty_match_is_vacuously_fair(self, tmp_path: Path) -> None:
        assert a_runner(tmp_path).opponent_played_fairly


class TestWritingTheEvidence:
    def test_it_writes_one_config_and_one_log_per_sub_game(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1), an_outcome(2)])
        written = runner.write(result_for_two())
        assert len([p for p in written if p.name.startswith("config_")]) == 2
        assert len([p for p in written if p.name.startswith("log_")]) == 2

    def test_an_incoherent_set_is_refused(self, tmp_path: Path) -> None:
        """A result naming a sub-game with no log is a claim with no evidence."""
        from thief_agent.infra.artefacts import ArtefactError

        runner = a_runner(tmp_path)
        runner.outcomes.append(an_outcome(1))
        with pytest.raises(ArtefactError):
            runner.write(result_for_two())

    def test_every_file_carries_the_uid(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1), an_outcome(2)])
        for path in runner.write(result_for_two()):
            assert json.loads(path.read_text())["game_uid"] == "u-0001"


def result_for_two() -> Report:
    return Report(
        game_id="uoh26-s82kma9e",
        game_uid="u-0001",
        role="thief",
        team="uoh26-cops",
        opponent_team="uoh26-others",
        repositories=REPOS,
        sub_games=tuple(
            SubGameResult(sub_game=n, cop_score=0, thief_score=0, commit_hash=f"{n:040x}")
            for n in (1, 2)
        ),
        total_tokens=0,
        agreed=True,
    )


class TestTheResultIsScoredFromWhatWasPlayed:
    """The scoreboard, which until now was a placeholder in a fixture."""

    def test_a_capture_scores_the_cop(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.append(an_outcome(1, captured=True))
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        cop, thief = scores_for(Outcome.CAPTURE)
        assert result.sub_games[0].cop_score == cop
        assert result.sub_games[0].thief_score == thief

    def test_survival_scores_the_thief(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.append(an_outcome(1))
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        assert (result.sub_games[0].cop_score, result.sub_games[0].thief_score) == scores_for(
            Outcome.SURVIVAL
        )

    def test_the_scores_come_from_appendix_f_not_from_here(self, tmp_path: Path) -> None:
        """They are *fixed* parameters; inventing them is a disqualification."""
        runner = a_runner(tmp_path)
        runner.outcomes.append(an_outcome(1, captured=True))
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        assert (result.cop_total, result.thief_total) == scores_for(Outcome.CAPTURE)

    def test_the_totals_add_up_across_sub_games(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1, captured=True), an_outcome(2)])
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        capture, survival = scores_for(Outcome.CAPTURE), scores_for(Outcome.SURVIVAL)
        assert result.cop_total == capture[0] + survival[0]
        assert result.thief_total == capture[1] + survival[1]

    def test_the_steps_played_are_recorded(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.append(an_outcome(1))
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        assert result.sub_games[0].steps == 2

    def test_agreement_has_no_default(self, tmp_path: Path) -> None:
        """FR-7.16: only a person can say the other side accepted the result."""
        import inspect

        signature = inspect.signature(MatchRunner.result)
        assert signature.parameters["agreed"].default is inspect.Parameter.empty

    def test_a_result_is_not_agreed_just_because_we_played(self, tmp_path: Path) -> None:
        runner = a_runner(tmp_path)
        runner.outcomes.append(an_outcome(1))
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        assert result.to_dict()["result_agreed_with_opponent"] is False

    def test_the_commit_hash_reaches_every_sub_game(self, tmp_path: Path) -> None:
        """FR-7.28: which code played this game."""
        runner = a_runner(tmp_path)
        runner.outcomes.extend([an_outcome(1), an_outcome(2)])
        result = runner.result("b" * 40, 0, agreed=False, repositories=REPOS)
        assert {entry.commit_hash for entry in result.sub_games} == {"b" * 40}


class TestReadingTheConfigForAMatch:
    """The driver is uncovered by design; the parts that can be silently wrong are not."""

    def test_a_start_cell_arrives_from_json_as_a_list(self) -> None:
        """JSON has no tuples, and a board built from a list is a board of the wrong type."""
        assert _cell([3, 4], (0, 0)) == (3, 4)

    def test_a_tuple_survives_unchanged(self) -> None:
        assert _cell((1, 2), (0, 0)) == (1, 2)

    @pytest.mark.parametrize("bad", [None, [1], [1, 2, 3], "3,4", 7])
    def test_anything_unusable_falls_back_rather_than_crashing(self, bad: object) -> None:
        """A missing start is a config gap, not a reason to die mid-handshake."""
        assert _cell(bad, (9, 9)) == (9, 9)

    def test_a_team_is_read_from_the_private_config(self) -> None:
        team = _team(
            {
                "us": {
                    "name": "uoh26-cops",
                    "members": ["A", "B"],
                    "cop_repo": "https://x/cop",
                    "thief_repo": "https://x/thief",
                }
            },
            "us",
            "fallback",
        )
        assert team.name == "uoh26-cops"
        assert team.members == ("A", "B")

    def test_a_team_with_no_repository_links_is_refused(self) -> None:
        """FR-7.28 wants four links; a declaration without them cannot be built."""
        from thief_agent.infra.declaration import DeclarationError

        with pytest.raises(DeclarationError, match="four repository links"):
            _team({"us": {"name": "x", "members": ["A"]}}, "us", "fallback")

    def test_the_timestamp_is_utc_and_to_the_second(self) -> None:
        """Both sides record times; a local-time one is unreconcilable."""
        from datetime import datetime

        stamp = _now()
        parsed = datetime.fromisoformat(stamp)
        assert parsed.tzinfo is not None
        assert parsed.microsecond == 0
