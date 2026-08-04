"""Tests for the scent trail and its decay (#52).

Where the rulebook prints a number, that number is the fixture. #51 shipped a
wrong emission because its tests compared us against the reference
implementation rather than against the book, so the book's own worked values
are transcribed here by hand.
"""

import pytest

from thief_agent.domain.scent import PRECISION, emission
from thief_agent.domain.trail import RETENTION, VANISHED, Trail
from thief_agent.shared.appendix_f import TABLE, Status


class TestTheBookValues:
    def test_the_rate_is_fixed_in_appendix_f(self) -> None:
        row = next(r for r in TABLE if r.key == "pheromone_decay")
        assert (row.book_value, row.status) == (0.10, Status.FIXED)

    def test_retention_is_the_books_ninety_percent(self) -> None:
        """PDF p. 43 states it in words as well as in the formula: the trail
        keeps 90% of its value each turn."""
        assert pytest.approx(0.90) == RETENTION


class TestDecayIsMultiplicative:
    def test_one_turn_from_the_centre_gives_the_books_worked_value(self) -> None:
        """The number the lie-detection example on PDF p. 47 depends on.

        The cop expects a fresh northern trace of (1-rho)*0.9 = 0.81 and
        measures 0.00, and that gap is what exposes the lie. Subtractive decay
        gives 0.80, so an agent using it computes a different expectation and
        a different confidence from the same board.
        """
        trail = Trail({(3, 3): 0.9})
        trail.decay()
        assert round(trail.intensity_at((3, 3)), 3) == 0.81

    def test_it_is_not_the_references_subtraction(self) -> None:
        trail = Trail({(3, 3): 0.9})
        trail.decay()
        assert round(trail.intensity_at((3, 3)), 3) != 0.80

    @pytest.mark.parametrize(
        ("turns", "expected"),
        [(1, 0.81), (2, 0.729), (3, 0.656), (6, 0.478), (9, 0.349)],
    )
    def test_the_curve_matches_hand_computation(self, turns: int, expected: float) -> None:
        trail = Trail({(0, 0): 0.9})
        for _ in range(turns):
            trail.decay()
        assert round(trail.intensity_at((0, 0)), 3) == expected

    def test_a_deposit_stays_above_half_peak_for_six_to_seven_turns(self) -> None:
        """#52 states this as the practical consequence of rho = 0.10, and it
        is only true of the multiplicative rule — subtraction crosses half at
        four and a half."""
        trail = Trail({(0, 0): 0.9})
        for _ in range(6):
            trail.decay()
        assert trail.intensity_at((0, 0)) > 0.45
        trail.decay()
        assert trail.intensity_at((0, 0)) < 0.45

    def test_a_stronger_trace_outlives_a_weaker_one(self) -> None:
        """Why proportional decay matters beyond the arithmetic. Subtraction
        gives every cell the same lifetime, so intensity stops meaning
        recency — and recency is what makes the field readable."""
        trail = Trail({(0, 0): 0.9, (0, 1): 0.2})
        for _ in range(20):
            trail.decay()
        assert trail.intensity_at((0, 0)) > trail.intensity_at((0, 1)) > 0.0

    def test_nothing_goes_negative(self) -> None:
        """A silent cell is absent information, never negative information."""
        trail = Trail({(0, 0): 0.9})
        for _ in range(200):
            trail.decay()
        assert all(value >= 0.0 for value in trail.values.values())


class TestOncePerFullTurn:
    def test_two_calls_are_two_turns_of_forgetting(self) -> None:
        """Decaying per half-move halves the trail's memory and puts us out of
        step with an opponent who read the rule correctly."""
        once, twice = Trail({(0, 0): 0.9}), Trail({(0, 0): 0.9})
        once.decay()
        twice.decay()
        twice.decay()
        assert round(once.intensity_at((0, 0)), 3) == 0.81
        assert round(twice.intensity_at((0, 0)), 3) == 0.729

    def test_a_negotiated_rate_is_honoured(self) -> None:
        trail = Trail({(0, 0): 0.9})
        trail.decay(rate=0.20)
        assert round(trail.intensity_at((0, 0)), 3) == 0.72


class TestDeposit:
    def test_an_emission_lands_whole(self) -> None:
        trail = Trail()
        trail.deposit(emission((3, 3), 7))
        assert trail.intensity_at((3, 3)) == 0.9
        assert round(trail.intensity_at((2, 3)), 2) == 0.62

    def test_the_stronger_value_wins(self) -> None:
        trail = Trail({(1, 1): 0.5})
        trail.deposit({(1, 1): 0.9})
        assert trail.intensity_at((1, 1)) == 0.9

    def test_a_weaker_deposit_does_not_erase_a_stronger_one(self) -> None:
        trail = Trail({(1, 1): 0.9})
        trail.deposit({(1, 1): 0.2})
        assert trail.intensity_at((1, 1)) == 0.9

    def test_deposits_do_not_accumulate(self) -> None:
        """Max-merge, not addition. Intensity is a clock, not a quantity, and
        summing would let a pacing agent manufacture a peak brighter than any
        real emission and drag the opponent's argmax onto it."""
        trail = Trail()
        for _ in range(5):
            trail.deposit({(1, 1): 0.9})
        assert trail.intensity_at((1, 1)) == 0.9

    def test_an_older_trail_is_overwritten_by_a_fresh_pass(self) -> None:
        trail = Trail()
        trail.deposit(emission((3, 3), 7))
        for _ in range(5):
            trail.decay()
        faded = trail.intensity_at((3, 3))
        trail.deposit(emission((3, 3), 7))
        assert trail.intensity_at((3, 3)) == 0.9 > faded


class TestPruning:
    def test_a_faded_cell_is_dropped_rather_than_kept_forever(self) -> None:
        """Multiplicative decay never reaches zero, so without a floor the
        field only ever grows."""
        trail = Trail({(0, 0): 0.9})
        for _ in range(200):
            trail.decay()
        assert trail.values == {}

    def test_it_is_dropped_at_the_wires_own_resolution(self) -> None:
        """Pruning at the precision the field is transmitted in keeps the
        threshold observable rather than arbitrary: anything dropped would
        have gone out as 0.000 anyway."""
        assert VANISHED == 0.0005
        assert round(0.00049, PRECISION) == 0.0
        crosses = Trail({(0, 0): 0.00055})
        crosses.decay()
        assert crosses.values == {}, "0.00055 * 0.9 = 0.000495, rounds to 0.000"
        survives = Trail({(0, 0): 0.00056})
        survives.decay()
        assert survives.values != {}, "0.00056 * 0.9 = 0.000504, still transmittable"

    def test_a_cell_just_above_the_floor_survives(self) -> None:
        trail = Trail({(0, 0): 0.9})
        while trail.values:
            last = trail.intensity_at((0, 0))
            trail.decay()
        assert round(last, PRECISION) > 0.0


class TestReading:
    def test_silence_reads_as_zero(self) -> None:
        assert Trail().intensity_at((3, 3)) == 0.0

    def test_the_strongest_cell_is_the_naive_guess(self) -> None:
        trail = Trail()
        trail.deposit(emission((5, 2), 7))
        assert trail.strongest() == (5, 2)

    def test_an_empty_trail_names_no_cell(self) -> None:
        assert Trail().strongest() is None

    def test_ties_break_by_position_not_dict_order(self) -> None:
        """Two peers reading the same field must name the same cell."""
        trail = Trail({(4, 4): 0.5, (1, 1): 0.5, (2, 2): 0.5})
        assert trail.strongest() == (1, 1)


class TestTheWireForm:
    def test_it_is_string_keyed_and_rounded(self) -> None:
        trail = Trail()
        trail.deposit(emission((1, 1), 7))
        wire = trail.snapshot()
        assert wire["1,1"] == 0.9
        assert wire["0,1"] == 0.617

    def test_rounding_happens_only_here(self) -> None:
        """Rounding every decay step would pin small values in place forever:
        0.001 decayed is 0.0009, which rounds straight back to 0.001."""
        trail = Trail({(0, 0): 0.001})
        trail.decay()
        assert trail.intensity_at((0, 0)) == pytest.approx(0.0009)
        assert trail.snapshot() == {"0,0": 0.001}

    def test_cells_that_transmit_as_zero_are_omitted(self) -> None:
        assert Trail({(0, 0): 0.0004}).snapshot() == {}

    def test_the_form_is_stable_across_calls(self) -> None:
        trail = Trail()
        trail.deposit(emission((3, 3), 7))
        assert trail.snapshot() == trail.snapshot()
        assert list(trail.snapshot()) == sorted(trail.snapshot())
