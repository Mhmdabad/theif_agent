"""Tests for the belief map b(s) (#57)."""

import pytest

from thief_agent.domain.belief import Belief
from thief_agent.domain.board import BoardState


def board(**kw: object) -> BoardState:
    barriers = kw.get("barriers", frozenset())
    size = kw.get("grid_size", 7)
    assert isinstance(barriers, frozenset | set) and isinstance(size, int)
    return BoardState(
        cop=(0, 0), thief=(size - 1, size - 1), grid_size=size, barriers=frozenset(barriers)
    )


class TestItIsADistribution:
    def test_a_uniform_prior_sums_to_one(self) -> None:
        assert Belief.uniform(board()).total() == pytest.approx(1.0)

    def test_every_free_cell_has_equal_mass(self) -> None:
        """The honest prior. Weighting the centre or a start position would be
        evidence we did not gather."""
        belief = Belief.uniform(board())
        assert len(set(belief.mass.values())) == 1
        assert belief.at((3, 3)) == pytest.approx(1 / 49)

    def test_it_still_sums_to_one_after_an_update(self) -> None:
        belief = Belief.uniform(board())
        belief.update({(3, 3): 0.9, (3, 4): 0.1})
        assert belief.total() == pytest.approx(1.0)

    def test_nothing_is_ever_negative(self) -> None:
        belief = Belief.uniform(board())
        belief.update({(3, 3): 5.0})
        assert all(value >= 0.0 for value in belief.mass.values())


class TestBarriers:
    def test_a_sealed_cell_carries_no_belief(self) -> None:
        """Nobody can stand there. Not unlikely — impossible."""
        belief = Belief.uniform(board(barriers={(2, 2)}))
        assert belief.at((2, 2)) == 0.0

    def test_the_mass_is_redistributed_not_lost(self) -> None:
        """Zeroing without renormalising leaves a distribution summing to less
        than one, and every downstream comparison then measures a different
        total."""
        belief = Belief.uniform(board())
        belief.apply_barriers(board(barriers={(2, 2), (3, 3)}))
        assert belief.total() == pytest.approx(1.0)
        assert belief.at((2, 2)) == belief.at((3, 3)) == 0.0
        assert belief.at((0, 0)) == pytest.approx(1 / 47)

    def test_it_survives_barriers_arriving_over_time(self) -> None:
        """Barriers accumulate through a match, so this runs repeatedly and
        would leak mass a little at a time."""
        belief = Belief.uniform(board())
        walls: set[tuple[int, int]] = set()
        for cell in ((0, 1), (1, 1), (2, 1), (3, 1), (4, 1)):
            walls.add(cell)
            belief.apply_barriers(board(barriers=walls))
            assert belief.total() == pytest.approx(1.0)
        assert belief.at((2, 1)) == 0.0

    def test_a_fully_sealed_board_yields_no_belief_rather_than_nan(self) -> None:
        walls = {(r, c) for r in range(3) for c in range(3)}
        belief = Belief.uniform(board(grid_size=3, barriers=walls))
        assert belief.total() == 0.0
        assert belief.most_likely() is None


class TestTheBayesStep:
    def test_evidence_concentrates_the_posterior(self) -> None:
        belief = Belief.uniform(board())
        belief.update({(5, 5): 9.0, (5, 4): 6.0})
        assert belief.most_likely() == (5, 5)
        assert belief.at((5, 5)) > belief.at((5, 4)) > belief.at((0, 0))

    def test_contradictory_evidence_moves_it_back(self) -> None:
        """Silence is not disproof, so a cell the first update never mentioned
        still has mass to be revived by the second."""
        belief = Belief.uniform(board())
        belief.update({(5, 5): 9.0})
        assert belief.most_likely() == (5, 5)
        belief.update({(0, 0): 90.0, (5, 5): 0.01})
        assert belief.most_likely() == (0, 0)

    def test_an_unmentioned_cell_is_not_disproved(self) -> None:
        """The rulebook's own distinction. A 5x5 emission leaves 24 of 49
        cells unmentioned every turn; reading that as disproof would collapse
        the distribution onto the field in a single update."""
        belief = Belief.uniform(board())
        belief.update({(5, 5): 9.0})
        assert belief.at((0, 0)) > 0.0
        assert belief.at((5, 5)) > belief.at((0, 0))

    def test_an_explicit_zero_still_annihilates(self) -> None:
        """Barriers and disproved cells need it."""
        belief = Belief.uniform(board())
        belief.update({(5, 5): 0.0})
        assert belief.at((5, 5)) == 0.0
        assert belief.total() == pytest.approx(1.0)

    def test_a_likelihood_that_is_zero_everywhere_leaves_the_prior_alone(self) -> None:
        """Destroying the distribution would be worse than learning nothing."""
        belief = Belief.uniform(board())
        before = dict(belief.mass)
        belief.update({})
        assert belief.mass == pytest.approx(before)
        assert belief.total() == pytest.approx(1.0)

    def test_repeated_consistent_evidence_sharpens(self) -> None:
        belief = Belief.uniform(board())
        peaks = []
        for _ in range(3):
            belief.update({(5, 5): 9.0, (5, 4): 3.0})
            peaks.append(belief.at((5, 5)))
        assert peaks == sorted(peaks)

    def test_a_likelihood_that_rules_out_everything_is_ignored(self) -> None:
        """Evidence that disproves every remaining cell is evidence we have
        misread, not proof the opponent left the board. Keeping the prior is
        recoverable; zeroing it is not."""
        belief = Belief.uniform(board())
        before = dict(belief.mass)
        belief.update({cell: 0.0 for cell in belief.mass})
        assert belief.mass == before
        assert belief.total() == pytest.approx(1.0)

    def test_normalising_an_empty_distribution_is_not_an_error(self) -> None:
        belief = Belief(grid_size=7, mass={(0, 0): 0.0})
        belief.normalise()
        assert belief.mass == {}
        assert belief.most_likely() is None


class TestWhatThePolicyConsumes:
    def test_the_target_is_the_argmax(self) -> None:
        belief = Belief.uniform(board())
        belief.update({(1, 4): 9.0})
        assert belief.most_likely() == (1, 4)

    def test_ties_break_by_position_not_dict_order(self) -> None:
        """A uniform prior must yield a stable target, and two peers replaying
        must agree on it."""
        assert Belief.uniform(board()).most_likely() == (0, 0)

    def test_a_uniform_belief_reads_as_no_concentration(self) -> None:
        """The figure the barrier budget spends against: a wall placed on a
        diffuse belief is a permanent cost paid for a guess."""
        assert Belief.uniform(board()).concentration() == pytest.approx(0.0)

    def test_certainty_reads_as_full_concentration(self) -> None:
        belief = Belief.uniform(board())
        belief.update({(3, 3): 1.0, **{cell: 0.0 for cell in belief.mass if cell != (3, 3)}})
        assert belief.at((3, 3)) == pytest.approx(1.0)
        assert belief.concentration() == pytest.approx(1.0)

    def test_a_single_candidate_is_certainty(self) -> None:
        """Degenerate but reachable: one free cell left means we know."""
        assert Belief(grid_size=7, mass={(3, 3): 1.0}).concentration() == 1.0

    def test_partial_evidence_reads_in_between(self) -> None:
        belief = Belief.uniform(board())
        belief.update({(3, 3): 9.0, (3, 4): 6.0, (4, 3): 6.0})
        assert 0.0 < belief.concentration() < 1.0

    def test_an_empty_belief_has_no_concentration(self) -> None:
        assert Belief(grid_size=7).concentration() == 0.0


class TestTheHeatmapIsTheRealThing:
    def test_it_is_the_same_numbers_the_policy_sees(self) -> None:
        """#57 asks for the object the GUI renders and the policy targets to
        be the same one. A display-only copy would let the picture diverge
        from the reasoning, which is what the screenshot requirement exists
        to demonstrate."""
        belief = Belief.uniform(board())
        belief.update({(2, 5): 9.0})
        grid = belief.heatmap()
        assert grid[2][5] == belief.at((2, 5))
        assert sum(sum(row) for row in grid) == pytest.approx(belief.total())

    def test_it_is_square_and_row_major(self) -> None:
        grid = Belief.uniform(board()).heatmap()
        assert len(grid) == 7 and all(len(row) == 7 for row in grid)

    def test_barriers_render_as_zero(self) -> None:
        belief = Belief.uniform(board(barriers={(4, 2)}))
        assert belief.heatmap()[4][2] == 0.0
