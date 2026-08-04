"""The display shows local truth. It is not given the means to show anything else."""

import inspect
from typing import Any

import pytest

from thief_agent.domain.belief import Belief
from thief_agent.domain.board import BoardState
from thief_agent.ui.view import (
    BARRIER,
    EMPTY,
    SHADES,
    SUSPECTED,
    View,
    heatmap,
    render,
    shade,
)

OURS = "T"

BOARD = BoardState(grid_size=5, cop=(0, 0), thief=(4, 4), barriers=frozenset({(2, 2)}), step=7)


def belief_at(*cells: tuple[int, int]) -> Belief:
    """A belief concentrated on the given cells."""
    belief = Belief.uniform(BOARD)
    belief.update({cell: 100.0 for cell in cells})
    return belief


def view(**overrides: object) -> View:
    fields: dict[str, Any] = {
        "state": BOARD,
        "belief": belief_at((3, 1)),
        "role": "thief",
        "ours": (4, 4),
        "our_glyph": OURS,
        "opponent_glyph": "C",
    }
    return render(**{**fields, **overrides})


class TestItCannotShowWhatItIsNotGiven:
    def test_there_is_no_parameter_for_the_opponents_true_cell(self) -> None:
        """The only version of this rule that survives a later 'debug marker'.

        A bird's-eye view cannot be prevented by discipline inside a drawing
        routine, only by never handing it the value.
        """
        assert set(inspect.signature(render).parameters) == {
            "state",
            "belief",
            "role",
            "ours",
            "our_glyph",
            "opponent_glyph",
        }

    def test_the_opponents_real_cell_is_drawn_as_empty_when_belief_is_elsewhere(self) -> None:
        """(0,0) is where the cop actually is. The window must not know."""
        drawn = view(belief=belief_at((3, 1)))
        assert drawn.at((0, 0)).glyph == EMPTY
        assert drawn.suspected == (3, 1)

    def test_the_board_it_draws_is_identical_for_a_different_true_position(self) -> None:
        """The strongest form: move the opponent, change nothing on screen.

        If the display depended on the truth at all, this would differ.
        """
        elsewhere = BoardState(
            grid_size=5, cop=(1, 3), thief=(4, 4), barriers=frozenset({(2, 2)}), step=7
        )
        assert view().glyphs() == view(state=elsewhere).glyphs()

    def test_exactly_one_opponent_marker_is_drawn_and_it_is_the_suspicion(self) -> None:
        """A cheating board and an honest one differ by one variable.

        Which is why this is a test rather than a review checklist item.
        """
        rows = view(belief=belief_at((3, 1))).glyphs()
        assert sum(row.count("C") for row in rows) == 1
        assert "C" in rows[3]  # where we believe, not where they are


class TestWhatItDoesShow:
    def test_our_own_cell(self) -> None:
        assert view().at((4, 4)).glyph == OURS

    def test_barriers(self) -> None:
        assert view().at((2, 2)).glyph == BARRIER

    def test_the_belief_peak_marked_as_a_suspicion(self) -> None:
        drawn = view(belief=belief_at((3, 1)))
        assert drawn.at((3, 1)).glyph == "C" + SUSPECTED

    def test_every_cell_carries_belief_mass_for_the_heatmap(self) -> None:
        drawn = view()
        assert len(drawn.cells) == BOARD.grid_size**2
        assert all(0.0 <= cell.heat <= 1.0 for cell in drawn.cells)
        assert drawn.at((3, 1)).heat > drawn.at((0, 4)).heat

    def test_our_own_cell_wins_over_a_suspicion_on_the_same_square(self) -> None:
        """We know where we are; we only believe where they are."""
        assert view(belief=belief_at((4, 4))).at((4, 4)).glyph == OURS

    def test_a_barrier_does_not_hide_our_own_agent(self) -> None:
        sealed = BoardState(
            grid_size=5, cop=(0, 0), thief=(2, 2), barriers=frozenset({(2, 2)}), step=7
        )
        assert view(state=sealed, ours=(2, 2)).at((2, 2)).glyph == OURS

    def test_it_reports_the_step_so_the_window_can_label_itself(self) -> None:
        assert view().step == 7


class TestTheRowForm:
    def test_one_string_per_row(self) -> None:
        assert len(view().glyphs()) == BOARD.grid_size

    def test_it_reads_as_the_board(self) -> None:
        drawn = view(belief=belief_at((3, 1)))
        assert drawn.glyphs()[4].endswith(OURS)
        assert BARRIER in drawn.glyphs()[2]
        assert "C" in drawn.glyphs()[3]


class TestGuards:
    def test_a_role_the_wire_does_not_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="role must be one of"):
            view(role="cop")

    def test_the_view_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            view().step = 9  # type: ignore[misc]

    def test_a_cell_serialises_for_a_front_end(self) -> None:
        assert set(view().at((4, 4)).to_dict()) == {"row", "col", "glyph", "heat"}


class TestTheHeatmapIsBoundToTheLiveBelief:
    def test_updating_the_belief_changes_the_picture(self) -> None:
        """Bound to the object the strategy uses, not to a copy of it.

        A heatmap fed from a snapshot would show what the agent believed at
        some earlier moment, and the screenshot would be a true picture of a
        stale opinion — the least useful kind of wrong.
        """
        live = Belief.uniform(BOARD)
        before = heatmap(view(belief=live))
        live.update({(3, 1): 100.0})
        assert heatmap(view(belief=live)) != before

    def test_the_peak_is_the_deepest_band(self) -> None:
        drawn = view(belief=belief_at((3, 1)))
        bands = heatmap(drawn)
        assert bands[3][1] == SHADES - 1
        assert drawn.suspected == (3, 1)

    def test_the_glyph_and_the_colour_agree_about_which_cell_is_suspected(self) -> None:
        """Same Cell values behind both, so they cannot disagree."""
        drawn = view(belief=belief_at((2, 4)))
        bands = heatmap(drawn)
        hottest = max(
            ((r, c) for r in range(BOARD.grid_size) for c in range(BOARD.grid_size)),
            key=lambda cell: bands[cell[0]][cell[1]],
        )
        assert hottest == drawn.suspected


class TestTheScaleIsRelativeToTheObservedPeak:
    def test_a_spread_belief_still_shows_a_shape(self) -> None:
        """An absolute scale would render every honest mid-game board black.

        A belief over twenty-five cells has no value above 0.04, so the
        heatmap would look broken exactly when it is working.
        """
        gentle = Belief.uniform(BOARD)
        gentle.update({(1, 1): 2.0, (1, 2): 1.5})
        bands = heatmap(view(belief=gentle))
        assert bands[1][1] == SHADES - 1
        assert max(max(row) for row in bands) > min(min(row) for row in bands)

    def test_a_uniform_belief_is_flat_except_where_it_cannot_be(self) -> None:
        """Barriers carry no mass, so they are cold on an otherwise flat board.

        That is the belief being honest rather than the scale misbehaving: a
        sealed cell is somewhere the opponent cannot be, not somewhere we
        merely doubt.
        """
        bands = heatmap(view(belief=Belief.uniform(BOARD)))
        reachable = {
            bands[row][col]
            for row in range(BOARD.grid_size)
            for col in range(BOARD.grid_size)
            if (row, col) != (2, 2)
        }
        assert reachable == {SHADES - 1}
        assert bands[2][2] == 0

    @pytest.mark.parametrize(
        ("heat", "peak", "expected"),
        [(0.0, 1.0, 0), (1.0, 1.0, SHADES - 1), (0.5, 1.0, 2), (0.0, 0.0, 0)],
    )
    def test_the_band_arithmetic(self, heat: float, peak: float, expected: int) -> None:
        assert shade(heat, peak) == expected

    def test_a_peak_of_zero_is_cold_rather_than_a_division_error(self) -> None:
        """Reachable before the first observation arrives."""
        assert shade(0.0, 0.0) == 0

    def test_bands_stay_inside_the_scale(self) -> None:
        assert shade(2.0, 1.0) == SHADES - 1
        assert shade(-1.0, 1.0) == 0


class TestTheHeatmapShape:
    def test_it_is_one_row_per_board_row(self) -> None:
        bands = heatmap(view())
        assert len(bands) == BOARD.grid_size
        assert all(len(row) == BOARD.grid_size for row in bands)

    def test_every_band_is_in_range(self) -> None:
        assert all(0 <= band < SHADES for row in heatmap(view()) for band in row)
