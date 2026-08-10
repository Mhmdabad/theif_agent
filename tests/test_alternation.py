"""Tests for the alternation schedule and the group tally.

The schedule is the cohort's — natural role on odd sub-games, the opposite on
even — and the tally mirrors the reference's ``aggregate`` down to the tie rule
adding the Appendix F tie score on top of equal totals. Rule 35 makes both of
these wire format rather than taste: two peers computing different standings
publish different claims and an honest match ends unagreed.
"""

import pytest

from thief_agent.domain.alternation import SeriesStanding, opposite, role_for, tally
from thief_agent.domain.scoring import BOOK_TIE_SCORE


class TestTheSchedule:
    def test_natural_role_on_odd_opposite_on_even(self) -> None:
        assert [role_for("thief", n) for n in range(1, 7)] == [
            "thief", "police", "thief", "police", "thief", "police",
        ]

    def test_the_two_peers_schedules_interlock(self) -> None:
        """When A is the cop, B is the thief — every sub-game, both parities."""
        for number in range(1, 9):
            assert role_for("thief", number) == opposite(role_for("police", number))

    def test_a_role_the_board_does_not_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="role must be one of"):
            role_for("cop", 1)

    def test_sub_games_are_numbered_from_one(self) -> None:
        with pytest.raises(ValueError, match="numbered from 1"):
            role_for("thief", 0)


class TestTheGroupTally:
    def test_points_follow_the_role_played_not_the_repository(self) -> None:
        """Five captures: we take the cop's 20 whenever the schedule makes us cop.

        Five rather than six, because six identical sub-games split the roles
        symmetrically and the series is a genuine tie — which the next test
        pins on purpose.
        """
        capture = (20, 5)
        standing = tally([capture] * 5, "thief", BOOK_TIE_SCORE)
        assert standing.us == 3 * 5 + 2 * 20
        assert standing.them == 3 * 20 + 2 * 5

    def test_six_identical_sub_games_are_a_tie_by_symmetry(self) -> None:
        """Alternation is the fairness: same outcome six times means level totals."""
        standing = tally([(20, 5)] * 6, "thief", BOOK_TIE_SCORE)
        assert standing.series_tie

    def test_a_level_series_awards_the_tie_score_on_top(self) -> None:
        """The reference's ``aggregate`` adds it to both totals; so do we."""
        standing = tally([(20, 5)] * 2, "thief", BOOK_TIE_SCORE)
        assert standing.series_tie
        assert standing.winner is None
        assert standing.us == standing.them == 25 + BOOK_TIE_SCORE

    def test_an_uneven_series_names_a_winner_without_the_tie_score(self) -> None:
        """Thief in g1 (5), police in g2 (5) — their 20 and 10 win the series."""
        standing = tally([(20, 5), (5, 10)], "thief", BOOK_TIE_SCORE)
        assert not standing.series_tie
        assert standing.winner == "them"
        assert (standing.us, standing.them) == (5 + 5, 20 + 10)

    def test_a_technical_loss_sub_game_is_a_counted_tie(self) -> None:
        """0-0 has no winner; the reference counts it under ``ties``."""
        standing = tally([(0, 0), (20, 5)], "police", BOOK_TIE_SCORE)
        assert standing.ties == 1
        assert standing.won_us == 0
        assert standing.won_them == 1

    def test_an_empty_series_is_a_tie_of_nothing(self) -> None:
        standing = tally([], "thief", BOOK_TIE_SCORE)
        assert standing == SeriesStanding(
            BOOK_TIE_SCORE, BOOK_TIE_SCORE, 0, 0, 0, series_tie=True
        )

    def test_the_two_sides_compute_the_same_standing_mirrored(self) -> None:
        """What rule 35 actually needs: our 'us' is their 'them', byte for byte."""
        scores = [(20, 5), (5, 10), (0, 0), (20, 5)]
        ours = tally(scores, "thief", BOOK_TIE_SCORE)
        theirs = tally(scores, "police", BOOK_TIE_SCORE)
        assert (ours.us, ours.them) == (theirs.them, theirs.us)
        assert (ours.won_us, ours.won_them) == (theirs.won_them, theirs.won_us)
        assert ours.ties == theirs.ties
        assert ours.series_tie == theirs.series_tie
