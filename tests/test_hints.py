"""Tests for the natural-language hint parser (#64)."""

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.hints import (
    LANDMARKS,
    MAX_WORDS,
    CoordinateProtocolError,
    parse,
    truncate,
    words,
)

BOARD = BoardState(cop=(0, 0), thief=(3, 3), grid_size=7)
HERE = (3, 3)


class TestCoordinatesAreRefused:
    """The rulebook bans a numeric-coordinate protocol outright."""

    @pytest.mark.parametrize(
        "hint",
        [
            "I am at 3,4",
            "check row 2",
            "try (5, 5)",
            "column 6 is where I went",
            "cell 4 obviously",
            "meet me at 0; 0",
        ],
    )
    def test_a_coordinate_bearing_hint_raises(self, hint: str) -> None:
        with pytest.raises(CoordinateProtocolError):
            parse(hint, BOARD, HERE)

    def test_it_raises_rather_than_parsing_generously(self) -> None:
        """Accepting one would mean playing a different game from the one both
        teams agreed to — and rewarding the cheat, since their 'hint' would be
        worth more than an honest one."""
        with pytest.raises(CoordinateProtocolError):
            parse("I went north to 1,1", BOARD, HERE)

    def test_ordinary_numbers_are_not_coordinates(self) -> None:
        """'two blocks north' is a hint, not a protocol violation."""
        assert parse("about 2 streets north of the park", BOARD, HERE)

    def test_the_error_names_the_offending_text(self) -> None:
        with pytest.raises(CoordinateProtocolError, match="forbidden"):
            parse("3,3", BOARD, HERE)


class TestDirections:
    def test_north_claims_cells_above_the_speaker(self) -> None:
        claim = parse("I moved north", BOARD, HERE)
        assert all(row < HERE[0] for row, _ in claim)

    def test_south_claims_cells_below(self) -> None:
        claim = parse("headed south", BOARD, HERE)
        assert all(row > HERE[0] for row, _ in claim)

    def test_it_is_relative_to_the_speaker_not_the_board(self) -> None:
        """'North' means north *of them*."""
        high = parse("north", BOARD, (5, 3))
        low = parse("north", BOARD, (1, 3))
        assert min(r for r, _ in high) > min(r for r, _ in low)

    def test_colloquial_synonyms_are_understood(self) -> None:
        """The thief will not always say 'north'."""
        assert parse("going up", BOARD, HERE) == parse("going north", BOARD, HERE)
        assert parse("cut left", BOARD, HERE) == parse("cut west", BOARD, HERE)

    def test_a_claim_is_a_region_not_a_pin(self) -> None:
        """An honest but vague hint must not look like a lie because the thief
        was one square off."""
        assert len(parse("north", BOARD, HERE)) > 1

    def test_the_centre_of_the_claim_carries_most_weight(self) -> None:
        claim = parse("north", BOARD, HERE)
        assert max(claim.values()) > min(claim.values())

    def test_it_clips_to_the_board(self) -> None:
        claim = parse("north", BOARD, (0, 0))
        assert claim and all(BOARD.in_bounds(cell) for cell in claim)


class TestLandmarks:
    def test_a_named_place_becomes_a_region(self) -> None:
        """Named places rather than coordinates — the point of the channel."""
        assert parse("slipped past the bridge", BOARD, HERE)

    def test_different_landmarks_claim_different_places(self) -> None:
        assert parse("at the harbour", BOARD, HERE) != parse("uptown", BOARD, HERE)

    def test_they_scale_with_the_board(self) -> None:
        """grid_size is a negotiable minimum, so landmarks are fractions."""
        big = BoardState(cop=(0, 0), thief=(3, 3), grid_size=11)
        claim = parse("downtown", big, (5, 5))
        assert max(row for row, _ in claim) > 7

    def test_the_set_is_a_default_not_a_protocol(self) -> None:
        """Both sides only need to agree which words mean roughly where."""
        assert "bridge" in LANDMARKS and "park" in LANDMARKS


class TestUnreadableHints:
    def test_nothing_recognised_is_silence_not_an_error(self) -> None:
        """Refusing to act on a hint we did not understand is correct;
        refusing to play because of one is not."""
        assert parse("you will never find me", BOARD, HERE) == {}

    def test_an_empty_hint_is_silence(self) -> None:
        assert parse("", BOARD, HERE) == {}

    def test_punctuation_and_case_do_not_matter(self) -> None:
        assert parse("NORTH!", BOARD, HERE) == parse("north", BOARD, HERE)

    def test_a_long_hint_from_the_opponent_is_still_read(self) -> None:
        """Discarding it would let them silence us by rambling."""
        rambling = "well " * 40 + "north"
        assert parse(rambling, BOARD, HERE)


class TestOurOwnWordCap:
    def test_the_cap_is_the_appendix_f_value(self) -> None:
        assert MAX_WORDS == 15

    def test_a_short_hint_is_untouched(self) -> None:
        assert truncate("I went north") == "I went north"

    def test_a_long_hint_is_cut_to_the_cap(self) -> None:
        assert len(truncate(" ".join(["word"] * 40)).split()) == MAX_WORDS

    def test_it_applies_to_what_we_send_not_what_we_receive(self) -> None:
        """Emitting over the cap is our violation; receiving one is theirs."""
        long_hint = " ".join(["north"] * 40)
        assert len(truncate(long_hint).split()) == MAX_WORDS
        assert parse(long_hint, BOARD, HERE)


class TestTokenising:
    def test_it_strips_punctuation(self) -> None:
        assert words("Well, I'm north-east!") == ["well", "i", "m", "north", "east"]

    def test_it_lowercases(self) -> None:
        assert words("NORTH") == ["north"]
