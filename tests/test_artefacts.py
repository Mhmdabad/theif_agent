"""One uid across four files, names derived from one id, and holes refused."""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.artefacts import ArtefactError, ArtefactSet
from thief_agent.infra.config_file import LockedConfig, lock
from thief_agent.infra.declaration import Endpoints, MatchDeclaration, Team, build
from thief_agent.infra.match_log import MatchLog
from thief_agent.infra.report import Report, Repositories, SubGameResult
from thief_agent.infra.step_zero import Hardware, Provenance

GAME_ID = "uoh26-s82kma9e"
UID = "u-0001"
TEAMS = ("uoh26-thieves", "uoh26-others")

REPOS = Repositories(
    cop_repo="https://github.com/Mhmdabad/police_agent",
    thief_repo="https://github.com/Mhmdabad/theif_agent",
    opponent_cop_repo="https://github.com/other/police",
    opponent_thief_repo="https://github.com/other/thief",
)


def parameters() -> dict[str, Any]:
    body = json.loads((Path(__file__).resolve().parent.parent / "config/game.json").read_text())
    assert isinstance(body, dict)
    return body


def a_declaration(game_id: str = GAME_ID, uid: str = UID) -> MatchDeclaration:
    return build(
        game_id=game_id,
        game_uid=uid,
        role="thief",
        us=Team(
            name="uoh26-thieves",
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
            group_name="uoh26-thieves",
            github_commit="a" * 40,
            dirty=False,
        ),
        llm_model="claude-haiku-4-5",
        token_ceiling=200_000,
        started_at="2026-08-05T12:00:00Z",
        key=None,
    )


def a_config(sub_game: int, game_id: str = GAME_ID, uid: str = UID) -> LockedConfig:
    return lock(
        game_id=game_id,
        game_uid=uid,
        sub_game=sub_game,
        parameters=parameters(),
        agreed_between=TEAMS,
    )


def a_log(sub_game: int, game_id: str = GAME_ID, uid: str = UID) -> MatchLog:
    log = MatchLog(
        game_id=game_id,
        sub_game=sub_game,
        role="thief",
        game_uid=uid,
        config_sha256="c" * 64,
    )
    log.commit(1, f"{sub_game:064x}")
    log.reveal(1, {"move": "N"})
    log.disclose(1, f"{sub_game:032x}")
    return log


def a_result(sub_games: tuple[int, ...] = (1, 2), game_id: str = GAME_ID, uid: str = UID) -> Report:
    return Report(
        game_id=game_id,
        game_uid=uid,
        role="thief",
        team="uoh26-thieves",
        opponent_team="uoh26-others",
        repositories=REPOS,
        sub_games=tuple(
            SubGameResult(
                sub_game=number, cop_score=10, thief_score=0, commit_hash=f"{number:040x}"
            )
            for number in sub_games
        ),
        total_tokens=1234,
        agreed=True,
    )


def a_set(**overrides: object) -> ArtefactSet:
    fields: dict[str, object] = {
        "declaration": a_declaration(),
        "configs": (a_config(1), a_config(2)),
        "logs": (a_log(1), a_log(2)),
        "result": a_result(),
    }
    fields.update(overrides)
    return ArtefactSet(**fields)  # type: ignore[arg-type]


class TestACoherentSet:
    def test_it_agrees_on_one_match(self) -> None:
        assert a_set().check().coherent
        assert "agree on one match" in str(a_set().check())

    def test_the_declaration_is_authoritative_for_the_uid(self) -> None:
        """Somebody has to be, or 'they disagree' has no direction."""
        assert a_set().game_uid == UID

    def test_every_name_derives_from_the_game_id(self) -> None:
        assert a_set().filenames() == (
            "declaration_uoh26-s82kma9e.json",
            "config_uoh26-s82kma9e_g01.json",
            "config_uoh26-s82kma9e_g02.json",
            "log_uoh26-s82kma9e_g01.json",
            "log_uoh26-s82kma9e_g02.json",
            "result_uoh26-s82kma9e.json",
        )

    def test_the_names_are_all_distinct(self) -> None:
        """Sixty logs in one repository, and none may overwrite another."""
        names = a_set().filenames()
        assert len(set(names)) == len(names)


class TestTheUidMustMatchEverywhere:
    def test_a_config_with_a_different_uid(self) -> None:
        wrong = a_set(configs=(a_config(1), a_config(2, uid="u-9999")))
        assert "config g02 has a different game_uid" in str(wrong.check())

    def test_a_log_with_a_different_uid(self) -> None:
        wrong = a_set(logs=(a_log(1, uid="u-9999"), a_log(2)))
        assert "log g01 has a different game_uid" in str(wrong.check())

    def test_a_result_with_a_different_uid(self) -> None:
        assert "the result has a different game_uid" in str(
            a_set(result=a_result(uid="u-9")).check()
        )

    def test_a_declaration_with_no_uid_at_all(self) -> None:
        with pytest.raises(Exception, match="shares a game_uid"):
            a_declaration(uid="")

    def test_this_is_the_silent_failure(self) -> None:
        """A wrong uid produces files that each look valid on their own."""
        wrong = a_set(logs=(a_log(1, uid="u-9999"), a_log(2)))
        assert not wrong.check().coherent
        assert wrong.logs[0].verifiable().complete, "the log itself is fine; the link is wrong"


class TestTheGameIdMustMatchToo:
    def test_a_config_from_another_match(self) -> None:
        other = a_config(1, game_id="uoh26-other")
        assert "not 'uoh26-s82kma9e'" in str(a_set(configs=(other, a_config(2))).check())

    def test_a_log_from_another_match(self) -> None:
        other = a_log(1, game_id="uoh26-other")
        assert "log g01 is for game" in str(a_set(logs=(other, a_log(2))).check())

    def test_a_result_from_another_match(self) -> None:
        assert "the result is for game" in str(
            a_set(result=a_result(game_id="uoh26-other")).check()
        )


class TestHolesInTheEvidence:
    def test_a_config_with_no_log(self) -> None:
        """A sub-game agreed and never played."""
        thin = a_set(logs=(a_log(1),), result=a_result(sub_games=(1,)))
        assert "sub-game 2 has a config but no log" in str(thin.check())

    def test_a_log_with_no_config(self) -> None:
        """A sub-game played under parameters nobody recorded."""
        thin = a_set(configs=(a_config(1),))
        assert "sub-game 2 has a log but no config" in str(thin.check())

    def test_a_result_reporting_a_sub_game_that_was_never_played(self) -> None:
        assert "reports sub-game 3, which has no log" in str(
            a_set(result=a_result((1, 2, 3))).check()
        )

    def test_a_played_sub_game_missing_from_the_result(self) -> None:
        assert "sub-game 2 was played but is not in the result" in str(
            a_set(result=a_result((1,))).check()
        )

    def test_two_configs_for_one_sub_game(self) -> None:
        assert "two configs claim the same sub-game" in str(
            a_set(configs=(a_config(1), a_config(1))).check()
        )

    def test_two_logs_for_one_sub_game(self) -> None:
        assert "two logs claim the same sub-game" in str(a_set(logs=(a_log(1), a_log(1))).check())


class TestEverythingIsReportedAtOnce:
    def test_several_problems_come_back_together(self) -> None:
        """An examiner should not fix one thing to discover the next."""
        broken = a_set(
            configs=(a_config(1, uid="u-9"), a_config(2, uid="u-9")),
            result=a_result(uid="u-8"),
        )
        assert len(broken.check().problems) >= 3

    def test_the_summary_lists_them(self) -> None:
        broken = a_set(result=a_result(uid="u-8"))
        assert str(broken.check()).startswith("the artefacts disagree:")


class TestWriting:
    def test_a_coherent_set_writes_all_four_kinds(self, tmp_path: Path) -> None:
        written = a_set().write(tmp_path)
        assert len(written) == 6
        assert {path.name for path in written} == set(a_set().filenames())

    def test_every_written_file_is_readable_json(self, tmp_path: Path) -> None:
        for path in a_set().write(tmp_path):
            assert json.loads(path.read_text())

    def test_every_written_file_carries_the_uid(self, tmp_path: Path) -> None:
        for path in a_set().write(tmp_path):
            assert json.loads(path.read_text())["game_uid"] == UID

    def test_an_incoherent_set_is_refused(self, tmp_path: Path) -> None:
        """Caught at the only moment it is cheap: before anything exists."""
        with pytest.raises(ArtefactError, match="incoherent artefact set"):
            a_set(result=a_result(uid="u-9999")).write(tmp_path)

    def test_nothing_is_written_when_it_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ArtefactError):
            a_set(result=a_result(uid="u-9999")).write(tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_the_refusal_names_what_disagreed(self, tmp_path: Path) -> None:
        with pytest.raises(ArtefactError, match="different game_uid"):
            a_set(result=a_result(uid="u-9999")).write(tmp_path)
