"""Tests for scent emission (#209).

The fixture is figure 4 of the rulebook (PDF p. 44), transcribed by hand. It
is deliberately *not* derived from our own formula: the claim under test is
that our emission reproduces the book's printed field, and a fixture computed
from the implementation would only prove the implementation is deterministic.
"""

import math

import pytest

from thief_agent.domain.scent import (
    CENTRE_INTENSITY,
    CHEBYSHEV,
    DEFAULT_FALLOFF,
    GAUSSIAN,
    GRID_SIZE,
    MODELS,
    PRECISION,
    SIGMA,
    emission,
    numeric_example,
)
from thief_agent.shared.appendix_f import TABLE, Status

FIGURE_4 = [
    [0.04, 0.14, 0.20, 0.14, 0.04],
    [0.14, 0.42, 0.62, 0.42, 0.14],
    [0.20, 0.62, 0.90, 0.62, 0.20],
    [0.14, 0.42, 0.62, 0.42, 0.14],
    [0.04, 0.14, 0.20, 0.14, 0.04],
]
"""Rulebook figure 4, PDF p. 44, transcribed. Centre tau = 0.9."""


def reference_chebyshev(
    centre: tuple[int, int], board_size: int, intensity: float, grid_size: int
) -> dict[tuple[int, int], float]:
    """The reference repo's ``_radial``, transcribed verbatim."""
    half = grid_size // 2
    drop = intensity / (half + 1)
    out: dict[tuple[int, int], float] = {}
    for dr in range(-half, half + 1):
        for dc in range(-half, half + 1):
            cell = (centre[0] + dr, centre[1] + dc)
            if 0 <= cell[0] < board_size and 0 <= cell[1] < board_size:
                out[cell] = round(max(0.0, intensity - drop * max(abs(dr), abs(dc))), 3)
    return out


class TestAppendixFParameters:
    def test_all_three_are_fixed(self) -> None:
        rows = {row.key: row.status for row in TABLE if row.section == "pheromones"}
        assert rows["pheromone_center_intensity"] is Status.FIXED
        assert rows["pheromone_decay"] is Status.FIXED
        assert rows["pheromone_grid_size"] is Status.FIXED

    def test_the_constants_come_from_the_table(self) -> None:
        assert (CENTRE_INTENSITY, GRID_SIZE) == (0.9, 5)


class TestItReproducesFigure4:
    """#209's acceptance criterion, against the hand-transcribed figure."""

    def test_every_printed_value_matches(self) -> None:
        field = emission((3, 3), 9)
        for row, values in enumerate(FIGURE_4):
            for col, expected in enumerate(values):
                cell = (3 + row - 2, 3 + col - 2)
                assert round(field[cell], 2) == expected, f"offset {cell} in figure 4"

    def test_the_figure_is_not_chebyshev(self) -> None:
        """The two numbers that settle the shape on their own.

        (1,2) and (2,1) are 0.14 while (2,2) is 0.04. All three are ring 2
        under Chebyshev and would be equal. They are not, so intensity falls
        with dr**2 + dc**2 — Euclidean, not Chebyshev.
        """
        assert FIGURE_4[1][0] == FIGURE_4[0][1] == 0.14
        assert FIGURE_4[0][0] == 0.04
        assert FIGURE_4[1][0] != FIGURE_4[0][0]

    def test_and_our_field_agrees_on_exactly_that(self) -> None:
        field = emission((3, 3), 9)
        assert field[(2, 1)] == field[(1, 2)]
        assert field[(1, 1)] < field[(2, 1)]

    def test_the_diagonal_is_further_than_the_side(self) -> None:
        """The property that carries direction. A square terrace has none."""
        field = emission((3, 3), 9)
        assert field[(2, 3)] == 0.617
        assert field[(2, 2)] == 0.423
        assert field[(2, 2)] < field[(2, 3)]

    def test_sigma_is_the_value_the_figure_forces(self) -> None:
        """Fitted, not tuned. It is an agreement term, not a strategy knob."""
        assert 1.148 <= SIGMA <= 1.1544
        for row, values in enumerate(FIGURE_4):
            for col, expected in enumerate(values):
                squared = (row - 2) ** 2 + (col - 2) ** 2
                assert round(0.9 * math.exp(-squared / (2 * SIGMA**2)), 2) == expected


class TestTheReferenceModelIsStillAvailable:
    def test_it_is_not_the_default(self) -> None:
        assert DEFAULT_FALLOFF is GAUSSIAN
        assert MODELS["gaussian"] is GAUSSIAN
        assert MODELS["chebyshev"] is CHEBYSHEV

    def test_selecting_it_reproduces_the_reference_exactly(self) -> None:
        """So a series against an opponent running the reference code can be
        agreed at negotiation rather than lost to a failed lock."""
        for centre in ((3, 3), (0, 0), (6, 6), (0, 3)):
            assert emission(centre, 7, falloff=CHEBYSHEV) == reference_chebyshev(centre, 7, 0.9, 5)

    def test_the_two_models_genuinely_differ(self) -> None:
        """If they agreed, none of this would matter."""
        hill = emission((3, 3), 9)
        terrace = emission((3, 3), 9, falloff=CHEBYSHEV)
        assert hill != terrace
        assert len({round(v, 2) for v in terrace.values()}) == 3
        assert len({round(v, 2) for v in hill.values()}) == 6


class TestClipping:
    def test_a_centre_emission_is_the_full_grid(self) -> None:
        assert len(emission((3, 3), 7)) == GRID_SIZE * GRID_SIZE

    def test_a_corner_emission_is_a_quarter(self) -> None:
        field = emission((0, 0), 7)
        assert len(field) == 9
        assert all(row >= 0 and col >= 0 for row, col in field)

    def test_an_edge_emission_is_a_half(self) -> None:
        assert len(emission((0, 3), 7)) == 15

    def test_the_centre_keeps_full_intensity_in_a_corner(self) -> None:
        """Clipping removes cells; it does not attenuate what remains."""
        assert emission((0, 0), 7)[(0, 0)] == 0.9

    def test_clipping_applies_to_both_models(self) -> None:
        assert len(emission((0, 0), 7, falloff=CHEBYSHEV)) == 9


class TestReproducibility:
    def test_every_value_is_rounded(self) -> None:
        for value in emission((3, 3), 7, intensity=0.7).values():
            assert round(value, PRECISION) == value

    def test_the_field_is_identical_across_calls(self) -> None:
        assert emission((2, 4), 7) == emission((2, 4), 7)

    def test_nothing_is_negative(self) -> None:
        """A Gaussian never reaches zero, but the clamp guards a negotiated
        model that can — Chebyshev on a wider grid does."""
        assert min(emission((3, 3), 9).values()) > 0.0
        assert min(emission((3, 3), 9, falloff=CHEBYSHEV).values()) >= 0.0


class TestBarriersDoNotBlockIt:
    def test_emission_does_not_see_the_board_contents(self) -> None:
        """Scent passes through walls. Barriers block movement, not diffusion,
        and an occlusion rule we invented would break the hash lock."""
        assert (3, 4) in emission((3, 3), 7)


class TestTheNumericExample:
    def test_it_prints_the_field_the_lock_agrees(self) -> None:
        text = numeric_example()
        assert "gaussian 5x5" in text
        assert "0.90" in text and "0.62" in text and "0.04" in text

    def test_it_reports_the_model_actually_in_force(self) -> None:
        """A negotiated Chebyshev series must exchange Chebyshev numbers, not
        the ones we would have preferred."""
        text = numeric_example(falloff=CHEBYSHEV)
        assert text.startswith("chebyshev")
        assert "0.30" in text

    def test_the_example_matches_what_we_emit(self) -> None:
        """An example that drifted from the implementation is worse than none:
        we would hash-lock a promise we do not keep."""
        printed = [
            [float(value) for value in line.split()] for line in numeric_example().splitlines()[1:]
        ]
        assert printed == FIGURE_4


class TestTheParametersAreReadNotRestated:
    def test_a_non_numeric_book_value_is_refused(self) -> None:
        from thief_agent.domain.scent import _fixed_float

        with pytest.raises(TypeError, match="not a number"):
            _fixed_float("world", "map_area")

    def test_it_reads_the_table_rather_than_a_literal(self) -> None:
        from thief_agent.domain.scent import _fixed_float

        assert _fixed_float("pheromones", "pheromone_decay") == 0.10
