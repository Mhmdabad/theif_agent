"""A series is six sub-games, and nothing in the stack may shorten it.

Appendix F table 18 row 1 — ``[מספר המשחקונים]`` = **6**, status **קבוע
(FIXED)** — is the one row of that table the binding table never carried, so
the validator structurally could not catch a deviation from it. A shipped
``num_games: 1``, a ``--sub-games`` flag defaulting to ``1`` and a runner that
took the count from its caller then agreed with each other perfectly while all
three disagreed with the book.

This file follows the number from the book to the evidence: the table row, the
validator, the shipped config, the command line, the runner, the artefacts. It
is one invariant crossing six modules, which is why it is tested in one place
rather than six.
"""

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from test_localhost_match import REPOS, parameters
from test_match import a_runner, an_outcome, stub_boundaries
from thief_agent import __main__ as cli
from thief_agent.__main__ import CONFIG, StartupError, main, resolve_series_length
from thief_agent.runtime import driver
from thief_agent.runtime.driver import open_match
from thief_agent.runtime.match import MatchRunner
from thief_agent.shared.appendix_f import TABLE, Param, Status, book_int
from thief_agent.shared.config import (
    SERIES_KEY,
    SERIES_SECTION,
    SHARED_CONFIG,
    ConfigError,
    series_length,
    validate,
)
from thief_agent.shared.terms import to_terms

REPO = Path(__file__).resolve().parent.parent
BOOK_SERIES = 6
NO_TUNNEL: dict[str, str] = {}
PUBLIC = {"PUBLIC_URL": "https://abc.ngrok.io"}


def shipped() -> dict[str, Any]:
    return json.loads((REPO / "config/game.json").read_text())  # type: ignore[no-any-return]


class TestTheBindingTableCarriesTheRow:
    """Table 18 row 1 was the only row of that table missing from the manifest."""

    def test_the_row_is_present_with_the_book_key_value_and_status(self) -> None:
        assert Param(SERIES_SECTION, SERIES_KEY, BOOK_SERIES, Status.FIXED) in TABLE

    def test_it_is_named_by_the_key_the_shared_config_uses(self) -> None:
        assert (SERIES_SECTION, SERIES_KEY) == ("network_and_league", "num_games")

    def test_it_is_readable_through_the_accessor_like_every_other_parameter(self) -> None:
        assert book_int(SERIES_SECTION, SERIES_KEY) == BOOK_SERIES

    def test_it_is_fixed_rather_than_a_minimum_or_negotiable(self) -> None:
        """A longer series is as much a deviation as a shorter one."""
        row = next(p for p in TABLE if (p.section, p.key) == (SERIES_SECTION, SERIES_KEY))
        assert row.status is Status.FIXED


class TestValidationRefusesAnyOtherSeriesLength:
    """The validator is the only thing standing between a typo and an audit."""

    @pytest.mark.parametrize(
        "bad",
        [1, 5, 7, 0, -6, 12, True, False, 6.0, 5.9, "6", "six", None, [6], {"num_games": 6}],
        ids=[
            "one",
            "five",
            "seven",
            "zero",
            "negative",
            "twelve",
            "true",
            "false",
            "float-six",
            "float",
            "string-six",
            "word",
            "null",
            "list",
            "nested-dict",
        ],
    )
    def test_a_deviation_is_refused_whatever_it_is_dressed_as(self, bad: object) -> None:
        """``6.0 == 6`` and ``True == 1`` in Python; equality alone is not enough."""
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION][SERIES_KEY] = bad
        with pytest.raises(ConfigError, match="disqualifies the team"):
            validate(config)

    def test_the_complaint_names_the_parameter_and_the_book_value(self) -> None:
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION][SERIES_KEY] = 1
        with pytest.raises(ConfigError) as excinfo:
            validate(config)
        assert "network_and_league.num_games" in str(excinfo.value)
        assert "6" in str(excinfo.value)

    def test_a_missing_value_is_reported_rather_than_defaulted(self) -> None:
        config = copy.deepcopy(shipped())
        del config[SERIES_SECTION][SERIES_KEY]
        with pytest.raises(ConfigError, match="network_and_league.num_games is missing"):
            validate(config)

    def test_a_missing_section_is_reported(self) -> None:
        config = copy.deepcopy(shipped())
        del config[SERIES_SECTION]
        with pytest.raises(ConfigError, match="network_and_league.num_games is missing"):
            validate(config)

    @pytest.mark.parametrize("instead", [6, "six", [{"num_games": 6}], None])
    def test_a_section_that_is_not_a_section_is_reported(self, instead: object) -> None:
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION] = instead
        with pytest.raises(ConfigError, match="network_and_league.num_games is missing"):
            validate(config)

    def test_the_value_must_be_where_the_schema_puts_it(self) -> None:
        """A six hidden one level down satisfies nothing."""
        config = copy.deepcopy(shipped())
        del config[SERIES_SECTION][SERIES_KEY]
        config[SERIES_SECTION]["league"] = {SERIES_KEY: BOOK_SERIES}
        config[SERIES_KEY] = BOOK_SERIES
        with pytest.raises(ConfigError, match="network_and_league.num_games is missing"):
            validate(config)

    def test_the_book_value_itself_passes(self) -> None:
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION][SERIES_KEY] = BOOK_SERIES
        validate(config)


class TestTheShippedConfigIsASixSubGameSeries:
    def test_it_says_six(self) -> None:
        assert shipped()[SERIES_SECTION][SERIES_KEY] == BOOK_SERIES

    def test_it_validates(self) -> None:
        validate(shipped())

    def test_the_series_length_read_back_out_of_it_is_six(self) -> None:
        assert series_length(shipped()) == BOOK_SERIES

    def test_the_negotiated_terms_carry_six(self) -> None:
        """What we sign with the opponent has to say the same number."""
        assert to_terms(shipped())[SERIES_KEY] == BOOK_SERIES

    def test_the_terms_fallback_is_the_book_value_not_one(self) -> None:
        config = copy.deepcopy(shipped())
        del config[SERIES_SECTION]
        assert to_terms(config)[SERIES_KEY] == BOOK_SERIES


class TestTheSeriesLengthComesFromTheValidatedConfig:
    def test_a_valid_config_yields_the_book_length(self) -> None:
        assert series_length(shipped()) == BOOK_SERIES

    def test_an_invalid_config_yields_nothing_at_all(self) -> None:
        """It validates first, so a deviation cannot be read back as a length."""
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION][SERIES_KEY] = 1
        with pytest.raises(ConfigError, match="disqualifies the team"):
            series_length(config)

    def test_a_deviation_anywhere_in_the_config_still_refuses(self) -> None:
        config = copy.deepcopy(shipped())
        config["scoring"]["capture_cop"] = 99
        with pytest.raises(ConfigError, match="disqualifies the team"):
            series_length(config)

    def test_asking_for_the_book_length_is_allowed(self) -> None:
        assert series_length(shipped(), requested=BOOK_SERIES) == BOOK_SERIES

    @pytest.mark.parametrize("requested", [1, 3, 5, 7, 0])
    def test_asking_for_anything_else_is_refused(self, requested: int) -> None:
        with pytest.raises(ConfigError, match="disqualifies the team"):
            series_length(shipped(), requested=requested)

    def test_the_refusal_names_the_table_row(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            series_length(shipped(), requested=1)
        assert "Appendix F" in str(excinfo.value)
        assert "table 18" in str(excinfo.value)

    def test_the_length_is_an_integer_not_a_boolean(self) -> None:
        length = series_length(shipped())
        assert isinstance(length, int) and not isinstance(length, bool)


class TestTheCommandLineTakesItFromTheConfigRatherThanFromOne:
    def test_the_default_is_the_book_length(self) -> None:
        assert resolve_series_length(None, REPO / "config/game.json") == BOOK_SERIES

    def test_the_flag_carries_no_series_length_of_its_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``default=1`` was the defect: the command answered without reading the file."""
        monkeypatch.chdir(REPO)
        asked: list[int | None] = []

        def remember(requested: int | None, path: Path) -> int:
            asked.append(requested)
            return BOOK_SERIES

        monkeypatch.setattr("thief_agent.__main__.resolve_series_length", remember)
        main(["check"], environ=NO_TUNNEL)
        assert asked == [None]

    def test_check_reports_the_series_it_would_play(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(REPO)
        assert main(["check"], environ=NO_TUNNEL) == 0
        assert "6 sub-games" in capsys.readouterr().out

    def test_a_deviating_flag_stops_play_before_anything_starts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(REPO)
        monkeypatch.setattr(
            "thief_agent.__main__.play", lambda *_: pytest.fail("a deviation must not reach play")
        )
        monkeypatch.setattr(
            "thief_agent.__main__.serve",
            lambda *_: pytest.fail("a deviation must not bind a socket"),
        )
        assert main(["play", "--game-id", "uoh26-x", "--sub-games", "3"], environ=PUBLIC) == 1

    def test_the_refusal_says_why_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(REPO)
        main(["play", "--game-id", "uoh26-x", "--sub-games", "1"], environ=PUBLIC)
        error = capsys.readouterr().err
        assert "disqualifies the team" in error
        assert "cannot start" in error

    def test_asking_for_six_is_not_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(REPO)
        reached: list[object] = []

        def played(*args: object) -> int:
            reached.append(args)
            return 0

        monkeypatch.setattr("thief_agent.__main__.play", played)
        assert main(["play", "--game-id", "uoh26-x", "--sub-games", "6"], environ=PUBLIC) == 0
        assert reached, "a request for the book length should have played"

    def test_a_deviating_shared_config_is_refused_before_the_socket(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The file both peers sign is checked on our terminal, not at their audit."""
        deviant = tmp_path / "game.json"
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION][SERIES_KEY] = 1
        deviant.write_text(json.dumps(config))
        with pytest.raises(ConfigError, match="disqualifies the team"):
            resolve_series_length(None, deviant)

    def test_a_shared_config_that_is_absent_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(StartupError, match="shared configuration"):
            resolve_series_length(None, tmp_path / "absent.json")

    def test_a_shared_config_that_is_not_json_says_so(self, tmp_path: Path) -> None:
        broken = tmp_path / "game.json"
        broken.write_text("{not json")
        with pytest.raises(StartupError, match="valid JSON"):
            resolve_series_length(None, broken)

    def test_serve_refuses_a_deviating_shared_config_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Serving under the wrong series length is the same deviation, later."""
        deviant = tmp_path / "game.json"
        config = copy.deepcopy(shipped())
        config[SERIES_SECTION][SERIES_KEY] = 1
        deviant.write_text(json.dumps(config))
        monkeypatch.chdir(REPO)
        monkeypatch.setattr("thief_agent.__main__.SHARED_CONFIG", deviant)
        monkeypatch.setattr(
            "thief_agent.__main__.serve", lambda *_: pytest.fail("must not bind a socket")
        )
        assert main([], environ=NO_TUNNEL) == 1

    def test_the_private_config_cannot_shorten_the_series(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The private file is local and unsigned; a series length there is nothing."""
        private = tmp_path / "game.toml"
        private.write_text("num_games = 1\nsub_games = 1\n" + (REPO / CONFIG).read_text())
        monkeypatch.chdir(REPO)
        assert main(["check", "--config", str(private)], environ=NO_TUNNEL) == 0
        assert "6 sub-games" in capsys.readouterr().out

    def test_the_command_and_the_driver_read_one_shared_config(self) -> None:
        """Two paths to the constitution is two constitutions."""
        assert SHARED_CONFIG.as_posix() == "config/game.json"
        for module in (cli, driver):
            assert getattr(module, "SHARED_CONFIG") is SHARED_CONFIG  # noqa: B009


class TestTheRunnerPlaysExactlySixNumberedSubGames:
    def test_it_takes_its_length_from_the_agreed_parameters(self, tmp_path: Path) -> None:
        assert a_runner(tmp_path).sub_games == BOOK_SERIES

    def test_the_length_cannot_be_supplied_by_a_caller(self) -> None:
        """The defect was a count travelling in from the command line."""
        assert "sub_games" not in inspect.signature(MatchRunner).parameters
        assert "sub_games" not in inspect.signature(open_match).parameters

    def test_a_series_is_six_sub_games_numbered_one_to_six(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        played: list[int] = []
        monkeypatch.setattr(
            MatchRunner,
            "play_sub_game",
            lambda self, number, timeout=30.0: played.append(number),
        )
        crossed = stub_boundaries(monkeypatch)
        a_runner(tmp_path).play_series()
        assert played == [1, 2, 3, 4, 5, 6]
        assert crossed == [2, 3, 4, 5, 6], "six sub-games are separated by five boundaries"

    def test_a_runner_on_deviating_parameters_plays_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            MatchRunner,
            "play_sub_game",
            lambda self, number, timeout=30.0: pytest.fail("a deviation must not be played"),
        )
        runner = a_runner(tmp_path)
        runner.parameters = copy.deepcopy(parameters())
        runner.parameters[SERIES_SECTION][SERIES_KEY] = 1
        with pytest.raises(ConfigError, match="disqualifies the team"):
            runner.play_series()


class TestTheEvidenceCountsSixSubGames:
    """A series of six that reports two is a series nobody can audit."""

    @staticmethod
    def a_played_series(tmp_path: Path) -> MatchRunner:
        runner = a_runner(tmp_path)
        runner.outcomes.extend(an_outcome(number) for number in range(1, BOOK_SERIES + 1))
        return runner

    def test_the_result_reports_every_sub_game(self, tmp_path: Path) -> None:
        result = self.a_played_series(tmp_path).result(
            "a" * 40, 0, agreed=False, repositories=REPOS
        )
        assert [entry.sub_game for entry in result.sub_games] == [1, 2, 3, 4, 5, 6]

    def test_the_totals_say_six_were_played(self, tmp_path: Path) -> None:
        result = self.a_played_series(tmp_path).result(
            "a" * 40, 0, agreed=False, repositories=REPOS
        )
        assert result.to_dict()["num_sub_games"] == BOOK_SERIES

    def test_the_artefacts_agree_that_there_were_six(self, tmp_path: Path) -> None:
        runner = self.a_played_series(tmp_path)
        result = runner.result("a" * 40, 0, agreed=False, repositories=REPOS)
        artefacts = runner.artefacts(result)
        assert len(artefacts.configs) == BOOK_SERIES
        assert len(artefacts.logs) == BOOK_SERIES
        assert artefacts.check().coherent

    def test_the_written_set_is_one_config_and_one_log_per_sub_game(self, tmp_path: Path) -> None:
        runner = self.a_played_series(tmp_path)
        written = runner.write(runner.result("a" * 40, 0, agreed=False, repositories=REPOS))
        assert len([p for p in written if p.name.startswith("config_")]) == BOOK_SERIES
        assert len([p for p in written if p.name.startswith("log_")]) == BOOK_SERIES
        assert len(written) == BOOK_SERIES * 2 + 2

    def test_the_sub_games_are_numbered_in_the_filenames(self, tmp_path: Path) -> None:
        runner = self.a_played_series(tmp_path)
        written = runner.write(runner.result("a" * 40, 0, agreed=False, repositories=REPOS))
        assert {p.name for p in written if p.name.startswith("log_")} == {
            f"log_uoh26-s82kma9e_g{number:02d}.json" for number in range(1, BOOK_SERIES + 1)
        }
