"""Tests for the Bayes update over scent and hints (#58)."""

import pytest

from thief_agent.domain.belief import Belief
from thief_agent.domain.board import BoardState
from thief_agent.domain.inference import (
    FLOOR,
    MAX_RELIABILITY,
    hint_likelihood,
    scent_likelihood,
    update,
)

BOARD = BoardState(cop=(0, 0), thief=(6, 6), grid_size=7)
CELLS = [(r, c) for r in range(7) for c in range(7)]


def fresh() -> Belief:
    return Belief.uniform(BOARD)


class TestScentEvidence:
    def test_a_strong_cell_becomes_more_likely(self) -> None:
        belief = fresh()
        update(belief, {(5, 5): 0.9, (5, 4): 0.6})
        assert belief.most_likely() == (5, 5)
        assert belief.at((5, 5)) > belief.at((5, 4)) > belief.at((0, 0))

    def test_silence_is_floored_not_zeroed(self) -> None:
        """A quiet turn must not permanently disprove a cell — the opponent
        chooses where it emits, and the thief's whole strategy is to be
        somewhere the cop is not looking."""
        assert scent_likelihood({}, CELLS)[(3, 3)] == FLOOR
        belief = fresh()
        for _ in range(10):
            update(belief, {(5, 5): 0.9})
        assert belief.at((0, 0)) > 0.0

    def test_repeated_consistent_scent_sharpens(self) -> None:
        belief = fresh()
        peaks = []
        for _ in range(3):
            update(belief, {(5, 5): 0.9, (5, 4): 0.6})
            peaks.append(belief.at((5, 5)))
        assert peaks == sorted(peaks)
        assert belief.concentration() > 0.0

    def test_the_trail_can_move_the_belief_back(self) -> None:
        belief = fresh()
        for _ in range(5):
            update(belief, {(5, 5): 0.9})
        assert belief.most_likely() == (5, 5)
        for _ in range(20):
            update(belief, {(0, 0): 0.9})
        assert belief.most_likely() == (0, 0)


class TestReliabilityFlattensRatherThanScales:
    def test_a_worthless_hint_changes_nothing(self) -> None:
        flat = hint_likelihood({(0, 0): 1.0}, CELLS, reliability=0.0)
        assert len(set(flat.values())) == 1

    def test_scaling_would_have_been_a_silent_no_op(self) -> None:
        """The mistake this avoids. The belief renormalises, so multiplying a
        claim by a constant changes nothing — an implementation that
        'discounted' an unreliable hint that way would apply it at full
        strength while appearing to weigh it."""
        strong = fresh()
        update(strong, {}, claim={(0, 0): 1.0}, reliability=0.9)
        scaled = fresh()
        scaled.update({cell: 0.1 * (1.0 if cell == (0, 0) else 0.0) for cell in CELLS})
        assert strong.at((0, 0)) < scaled.at((0, 0))

    def test_an_unreliable_hint_cannot_overturn_the_trail(self) -> None:
        belief = fresh()
        update(belief, {(5, 5): 0.9, (5, 4): 0.6}, claim={(0, 0): 1.0}, reliability=0.0)
        assert belief.most_likely() == (5, 5)

    def test_a_trusted_hint_moves_it(self) -> None:
        belief = fresh()
        update(belief, {(5, 5): 0.9}, claim={(0, 0): 1.0}, reliability=0.9)
        assert belief.most_likely() == (0, 0)

    def test_influence_rises_with_reliability(self) -> None:
        weights = []
        for reliability in (0.0, 0.25, 0.5, 0.75, 0.9):
            belief = fresh()
            update(belief, {(5, 5): 0.9}, claim={(0, 0): 1.0}, reliability=reliability)
            weights.append(belief.at((0, 0)))
        assert weights == sorted(weights)

    def test_reliability_is_clamped_into_range(self) -> None:
        assert len(set(hint_likelihood({(0, 0): 1.0}, CELLS, -5.0).values())) == 1
        assert hint_likelihood({(0, 0): 1.0}, CELLS, 5.0) == hint_likelihood(
            {(0, 0): 1.0}, CELLS, MAX_RELIABILITY
        )


class TestAnAdversarysClaimIsNeverFinal:
    def test_reliability_is_capped_below_certainty(self) -> None:
        """The rules permit the opponent to lie, so certainty in their word is
        never justified by anything."""
        assert MAX_RELIABILITY < 1.0

    def test_a_hint_never_annihilates_a_cell_the_trail_supports(self) -> None:
        """At exactly 1.0 the flattening term vanishes and one hint erases
        every cell it does not name, with no later evidence able to revive
        them."""
        belief = fresh()
        update(belief, {(5, 5): 0.9}, claim={(0, 0): 1.0}, reliability=1.0)
        assert belief.at((5, 5)) > 0.0

    def test_so_the_trail_can_still_answer_a_lie(self) -> None:
        belief = fresh()
        update(belief, {(5, 5): 0.9}, claim={(0, 0): 1.0}, reliability=1.0)
        assert belief.most_likely() == (0, 0)
        for _ in range(30):
            update(belief, {(5, 5): 0.9})
        assert belief.most_likely() == (5, 5)


class TestTheTwoSourcesTogether:
    def test_agreement_sharpens_faster_than_either_alone(self) -> None:
        scent_only, both = fresh(), fresh()
        update(scent_only, {(5, 5): 0.9})
        update(both, {(5, 5): 0.9}, claim={(5, 5): 1.0}, reliability=0.8)
        assert both.at((5, 5)) > scent_only.at((5, 5))

    def test_conflict_is_resolved_numerically_not_by_precedence(self) -> None:
        """Neither source wins by rule. The stronger evidence moves the
        posterior and the weaker one slows it down."""
        belief = fresh()
        for _ in range(6):
            update(belief, {(5, 5): 0.9}, claim={(0, 0): 1.0}, reliability=0.5)
        assert 0.0 < belief.at((0, 0)) < 1.0
        assert 0.0 < belief.at((5, 5)) < 1.0

    def test_a_silent_turn_applies_scent_alone(self) -> None:
        belief = fresh()
        update(belief, {(5, 5): 0.9}, claim=None)
        assert belief.most_likely() == (5, 5)

    def test_an_empty_claim_is_treated_as_silence(self) -> None:
        spoken, silent = fresh(), fresh()
        update(spoken, {(5, 5): 0.9}, claim={}, reliability=0.9)
        update(silent, {(5, 5): 0.9}, claim=None)
        assert spoken.mass == pytest.approx(silent.mass)

    def test_belief_stays_a_distribution_throughout(self) -> None:
        belief = fresh()
        for turn in range(20):
            update(
                belief,
                {(turn % 7, turn % 7): 0.9},
                claim={(6 - turn % 7, 0): 1.0},
                reliability=0.6,
            )
            assert belief.total() == pytest.approx(1.0)

    def test_barriers_stay_at_zero_through_updates(self) -> None:
        walled = BoardState(cop=(0, 0), thief=(6, 6), grid_size=7, barriers=frozenset({(3, 3)}))
        belief = Belief.uniform(walled)
        update(belief, {(3, 3): 0.9}, claim={(3, 3): 1.0}, reliability=0.9)
        assert belief.at((3, 3)) == 0.0
        assert belief.total() == pytest.approx(1.0)

    def test_an_empty_belief_survives_an_update(self) -> None:
        assert hint_likelihood({(0, 0): 1.0}, [], 0.5) == {}
