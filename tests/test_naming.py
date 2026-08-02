"""Tests for match artefact filenames."""

import pytest

from thief_agent.shared.naming import (
    NamingError,
    config_filename,
    declaration_filename,
    log_filename,
    result_filename,
)


class TestShape:
    def test_declaration_has_no_sub_game(self) -> None:
        assert declaration_filename("m1") == "declaration_m1.json"

    def test_result_has_no_sub_game(self) -> None:
        assert result_filename("m1") == "result_m1.json"

    def test_config_carries_a_padded_sub_game(self) -> None:
        assert config_filename("m1", 1) == "config_m1_g01.json"

    def test_log_carries_a_padded_sub_game(self) -> None:
        assert log_filename("m1", 7) == "log_m1_g07.json"

    def test_two_digit_sub_games_are_not_padded_further(self) -> None:
        assert log_filename("m1", 12) == "log_m1_g12.json"

    def test_padding_keeps_a_full_series_in_order(self) -> None:
        """Zero padding so g02 sorts before g10 in a directory listing."""
        names = sorted(log_filename("m1", n) for n in range(1, 11))
        assert names[1] == "log_m1_g02.json"
        assert names[-1] == "log_m1_g10.json"


class TestDistinctness:
    def test_sub_games_of_one_match_never_collide(self) -> None:
        names = {config_filename("m1", n) for n in range(1, 7)}
        assert len(names) == 6

    def test_different_matches_never_collide(self) -> None:
        assert config_filename("m1", 1) != config_filename("m2", 1)

    def test_the_four_artefacts_are_distinct(self) -> None:
        names = {
            declaration_filename("m1"),
            config_filename("m1", 1),
            log_filename("m1", 1),
            result_filename("m1"),
        }
        assert len(names) == 4


class TestGameIdValidation:
    @pytest.mark.parametrize("game_id", ["", "-lead", "_lead", "a" * 65])
    def test_malformed_ids_are_refused(self, game_id: str) -> None:
        with pytest.raises(NamingError, match="game_id"):
            declaration_filename(game_id)

    @pytest.mark.parametrize("game_id", ["../etc/passwd", "a/b", "a b", "a.b", "a\\b"])
    def test_path_separators_and_traversal_are_refused(self, game_id: str) -> None:
        """The id becomes a filename component, so it must not escape it."""
        with pytest.raises(NamingError, match="game_id"):
            log_filename(game_id, 1)

    @pytest.mark.parametrize("game_id", ["m1", "s82kma9e", "2026-05-01_vs-teamB"])
    def test_realistic_ids_are_accepted(self, game_id: str) -> None:
        assert declaration_filename(game_id).endswith(".json")


class TestSubGameValidation:
    @pytest.mark.parametrize("sub_game", [0, -1, 100])
    def test_out_of_range_is_refused(self, sub_game: int) -> None:
        with pytest.raises(NamingError, match="sub_game"):
            config_filename("m1", sub_game)

    def test_a_full_six_sub_game_series_is_in_range(self) -> None:
        for n in range(1, 7):
            config_filename("m1", n)
