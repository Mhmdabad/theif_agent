"""Tests for hint generation (#65)."""

import random

from thief_agent.domain.bluff import (
    COMPASS,
    TEMPLATES,
    bearing,
    compose,
    decoy,
    nearest_landmark,
)
from thief_agent.domain.board import BoardState
from thief_agent.domain.hints import DIRECTIONS, LANDMARKS, MAX_WORDS, NUMERIC, parse

BOARD = BoardState(cop=(0, 0), thief=(5, 1), grid_size=7)


def every_hint() -> list[str]:
    return [
        compose(cell, BOARD, (3, 3), random.Random(seed))
        for seed in range(len(TEMPLATES))
        for cell in ((0, 0), (5, 1), (6, 6), (3, 3), (0, 6))
    ]


class TestTheWordCap:
    def test_it_is_the_appendix_f_value(self) -> None:
        assert MAX_WORDS == 15

    def test_every_template_fits_once_filled(self) -> None:
        assert all(len(hint.split()) <= MAX_WORDS for hint in every_hint())

    def test_a_hint_is_never_empty(self) -> None:
        assert all(hint.strip() for hint in every_hint())


class TestNoCoordinates:
    def test_nothing_we_emit_could_be_a_coordinate_protocol(self) -> None:
        """Our own parser refuses these; emitting one would be our violation."""
        assert not any(NUMERIC.search(hint) for hint in every_hint())

    def test_no_digits_at_all(self) -> None:
        assert not any(char.isdigit() for hint in every_hint() for char in hint)

    def test_our_own_parser_reads_what_we_write(self) -> None:
        """A hint the opponent cannot parse is silence we paid a turn for."""
        for hint in every_hint():
            assert parse(hint, BOARD, (3, 3)), hint


class TestItDescribesARegion:
    def test_a_hint_names_a_direction_or_a_landmark(self) -> None:
        for hint in every_hint():
            spoken = set(hint.lower().replace(",", " ").split())
            assert spoken & (set(DIRECTIONS) | set(LANDMARKS)), hint

    def test_only_compass_words_the_parser_reads_back(self) -> None:
        """'north-east' would be honest and unparseable, which helps nobody."""
        assert all(word in DIRECTIONS for word, _ in COMPASS)

    def test_the_larger_displacement_wins(self) -> None:
        assert bearing((3, 3), (0, 4)) == "north"
        assert bearing((3, 3), (4, 6)) == "east"

    def test_a_zero_displacement_still_yields_a_word(self) -> None:
        assert bearing((3, 3), (3, 3)) in DIRECTIONS


class TestDeterminism:
    def test_the_same_seed_gives_the_same_sentence(self) -> None:
        """A hint that differed between a match and its replay is one the
        audit cannot check."""
        assert compose((5, 1), BOARD, (3, 3), random.Random(4)) == compose(
            (5, 1), BOARD, (3, 3), random.Random(4)
        )

    def test_the_nearest_landmark_is_stable_under_ties(self) -> None:
        assert nearest_landmark((3, 3), BOARD) == nearest_landmark((3, 3), BOARD)

    def test_it_works_without_an_rng(self) -> None:
        assert compose((5, 1), BOARD, (3, 3))


class TestLying:
    def test_a_lie_reads_the_same_as_a_truth(self) -> None:
        """Phrasing that changed when we lie is a tell worth more to the
        opponent than the lie costs them."""
        truth = compose((5, 1), BOARD, (3, 3), random.Random(1))
        lie = compose(decoy((5, 1), BOARD), BOARD, (3, 3), random.Random(1))
        assert truth != lie
        assert truth.split()[0] == lie.split()[0]

    def test_the_decoy_is_far_from_the_truth(self) -> None:
        """A lie one square off is a lie the trail confirms — we would spend
        credibility to tell them something true."""
        for cell in ((0, 0), (5, 1), (2, 3)):
            far = decoy(cell, BOARD)
            assert abs(far[0] - cell[0]) + abs(far[1] - cell[1]) >= BOARD.grid_size - 1

    def test_the_decoy_is_on_the_board(self) -> None:
        for cell in ((0, 0), (6, 6), (3, 3)):
            assert BOARD.in_bounds(decoy(cell, BOARD))

    def test_a_centre_cell_still_produces_a_distant_decoy(self) -> None:
        """The regression. Mirroring lands (2, 3) two squares away, close
        enough that our own emission reaches it — a lie the trail confirms."""
        for cell in ((3, 3), (2, 3), (3, 4)):
            far = decoy(cell, BOARD)
            assert BOARD.in_bounds(far)
            assert abs(far[0] - cell[0]) + abs(far[1] - cell[1]) >= BOARD.grid_size - 1

    def test_it_is_stable_under_ties(self) -> None:
        assert decoy((3, 3), BOARD) == decoy((3, 3), BOARD)


class TestLandmarks:
    def test_it_names_the_closest_one(self) -> None:
        assert nearest_landmark((0, 3), BOARD) == "uptown"

    def test_landmarks_scale_with_the_board(self) -> None:
        big = BoardState(cop=(0, 0), thief=(3, 3), grid_size=11)
        assert nearest_landmark((10, 10), big) == nearest_landmark((6, 6), BOARD)

    def test_every_named_place_is_one_the_parser_knows(self) -> None:
        for hint in every_hint():
            named = [word for word in hint.lower().split() if word in LANDMARKS]
            assert named, hint
