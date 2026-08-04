"""Tests for the lie detector (#60), against the book's worked example."""

import pytest

from thief_agent.domain.credibility import (
    CONTRADICTION,
    FRESH_TRACE,
    Verdict,
    check,
    true_source,
)


class TestTheBooksWorkedExample:
    """PDF p. 47, reproduced.

    The thief announces "I moved north". A truthful claim would have left a
    fresh northern trace of (1-rho)*0.9 = 0.81. The cop measures 0.00 there
    while the whole scent mass sits at the opposite pole.
    """

    NORTH = {(0, 3): 1.0}
    SOUTH_EAST = {(6, 6): 0.9, (6, 5): 0.62, (5, 6): 0.62}

    def test_the_predicted_trace_is_the_books_number(self) -> None:
        assert FRESH_TRACE == 0.81

    def test_it_is_not_the_subtractive_prediction(self) -> None:
        """The reference's decay predicts 0.80, so an agent using it computes
        a different expectation and a different confidence from one board."""
        assert FRESH_TRACE != 0.80

    def test_the_northern_claim_is_contradicted(self) -> None:
        verdict = check(self.NORTH, self.SOUTH_EAST)
        assert verdict.predicted == 0.81
        assert verdict.measured == 0.0
        assert verdict.gap == pytest.approx(1.0)
        assert verdict.contradicted

    def test_the_verdict_reads_as_the_book_describes_it(self) -> None:
        assert "CONTRADICTED" in str(check(self.NORTH, self.SOUTH_EAST))
        assert "100%" in str(check(self.NORTH, self.SOUTH_EAST))

    def test_pursuit_re_aims_at_the_real_source(self) -> None:
        """Not the declared direction, and not the negation of it."""
        assert true_source(self.SOUTH_EAST) == (6, 6)

    def test_a_truthful_northern_claim_is_supported(self) -> None:
        assert not check(self.NORTH, {(0, 3): 0.81}).contradicted


class TestTheGapIsGradedNotBinary:
    def test_a_fully_supported_claim_scores_zero(self) -> None:
        assert check({(0, 0): 1.0}, {(0, 0): 0.81}).gap == pytest.approx(0.0)

    def test_a_partly_supported_claim_scores_in_between(self) -> None:
        assert 0.0 < check({(0, 0): 1.0}, {(0, 0): 0.4}).gap < 1.0

    def test_stronger_evidence_survives_being_exceeded(self) -> None:
        """A trace hotter than predicted is not a contradiction."""
        assert check({(0, 0): 1.0}, {(0, 0): 0.9}).gap == 0.0

    def test_the_ratio_matters_not_the_difference(self) -> None:
        """0.81 predicted against 0.00 is damning; 0.05 against 0.00 is not.
        A difference would rank them by absolute size and miss that."""
        damning = Verdict(predicted=0.81, measured=0.0, cells=((0, 0),))
        faint = Verdict(predicted=0.05, measured=0.0, cells=((0, 0),))
        assert damning.gap == faint.gap == 1.0
        assert damning.predicted > faint.predicted

    def test_a_claim_predicting_nothing_is_never_a_contradiction(self) -> None:
        """No prediction, no test. Dividing by it would be worse."""
        assert Verdict(predicted=0.0, measured=0.0, cells=()).gap == 0.0
        assert not Verdict(predicted=0.0, measured=0.0, cells=()).contradicted

    def test_the_threshold_sits_between_noise_and_the_books_case(self) -> None:
        assert 0.0 < CONTRADICTION < 1.0


class TestARegionalClaim:
    def test_the_strongest_cell_answers_for_the_region(self) -> None:
        """A hint naming an area is honest if the opponent is anywhere in it.
        Requiring every cell to be hot would convict a truthful speaker of
        imprecision."""
        claim = {(0, 0): 1.0, (0, 1): 1.0, (0, 2): 1.0}
        assert not check(claim, {(0, 2): 0.81}).contradicted

    def test_a_region_with_no_trace_anywhere_is_still_caught(self) -> None:
        claim = {(0, 0): 1.0, (0, 1): 1.0, (0, 2): 1.0}
        assert check(claim, {(6, 6): 0.9}).contradicted

    def test_the_cells_checked_are_recorded(self) -> None:
        verdict = check({(1, 1): 1.0, (0, 0): 1.0}, {})
        assert verdict.cells == ((0, 0), (1, 1))


class TestTheTrailCannotLie:
    def test_what_is_exposed_is_the_claim_not_the_field(self) -> None:
        """There is no such thing as a false trail: scent is emitted by
        movement and cannot be forged. The verdict is about the speaker."""
        verdict = check({(0, 3): 1.0}, {(6, 6): 0.9})
        assert verdict.contradicted
        assert verdict.measured == 0.0

    def test_an_empty_field_convicts_any_claim(self) -> None:
        """Early turns aside, silence everywhere means the claim has nothing
        supporting it."""
        assert check({(0, 0): 1.0}, {}).contradicted

    def test_no_source_when_nothing_has_been_smelled(self) -> None:
        assert true_source({}) is None

    def test_the_source_is_stable_under_ties(self) -> None:
        assert true_source({(4, 4): 0.5, (1, 1): 0.5}) == (1, 1)

    def test_the_check_is_symmetric(self) -> None:
        """Both agents run it: the thief cross-checks the cop's trail against
        the cop's hints by exactly this procedure."""
        assert check({(2, 2): 1.0}, {(2, 2): 0.81}).contradicted is False
        assert check({(2, 2): 1.0}, {(5, 5): 0.81}).contradicted is True
