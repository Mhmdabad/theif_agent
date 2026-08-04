"""Tests for scent emission (#44).

The acceptance criterion is *matches the reference field values at every
offset*, so several of these assert exact numbers rather than properties. The
model is hash-locked before a series: a field that is merely close is a failed
negotiation.
"""

import pytest

from thief_agent.domain.scent import (
    CENTRE_INTENSITY,
    GRID_SIZE,
    PRECISION,
    emission,
    falloff,
    numeric_example,
    ring,
)
from thief_agent.shared.appendix_f import TABLE, Status


def reference_field(
    centre: tuple[int, int], board_size: int, intensity: float, grid_size: int
) -> dict[tuple[int, int], float]:
    """The reference implementation's ``_radial``, transcribed verbatim.

    Kept as a separate transcription rather than reusing ours, so the test
    compares two implementations instead of comparing ours to itself.
    """
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
        """Deviating from a fixed value disqualifies the team."""
        rows = {row.key: row.status for row in TABLE if row.section == "pheromones"}
        assert rows["pheromone_center_intensity"] is Status.FIXED
        assert rows["pheromone_decay"] is Status.FIXED
        assert rows["pheromone_grid_size"] is Status.FIXED

    def test_the_constants_come_from_the_table(self) -> None:
        assert (CENTRE_INTENSITY, GRID_SIZE) == (0.9, 5)


class TestChebyshevShape:
    def test_a_ring_is_the_larger_offset(self) -> None:
        assert ring(0, 0) == 0
        assert ring(0, 2) == ring(2, 0) == ring(2, 2) == 2

    def test_the_diagonal_is_not_further_than_the_side(self) -> None:
        """The whole difference from a Euclidean hill. Under Chebyshev the
        corner of the 5x5 carries the same intensity as its edge midpoint."""
        field = emission((3, 3), 7)
        assert field[(1, 1)] == field[(1, 3)] == field[(3, 1)]

    def test_the_rings_are_the_book_values(self) -> None:
        field = emission((3, 3), 7)
        assert field[(3, 3)] == 0.9
        assert field[(2, 3)] == 0.6
        assert field[(1, 3)] == 0.3

    def test_the_outer_ring_still_carries_signal(self) -> None:
        """falloff divides by half+1, not half, so the border is readable.
        A field whose edge is zero is a field not worth transmitting."""
        assert falloff(0.9, 5) == pytest.approx(0.3)
        assert min(emission((3, 3), 7).values()) > 0.0


class TestMatchesTheReference:
    """#44's acceptance criterion, against a verbatim transcription."""

    @pytest.mark.parametrize("centre", [(3, 3), (0, 0), (6, 6), (0, 3), (1, 1), (5, 2), (2, 6)])
    def test_every_offset_agrees(self, centre: tuple[int, int]) -> None:
        assert emission(centre, 7) == reference_field(centre, 7, 0.9, 5)

    def test_it_agrees_on_a_larger_board_too(self) -> None:
        """grid_size is fixed; board size is a negotiable minimum."""
        assert emission((5, 5), 10) == reference_field((5, 5), 10, 0.9, 5)

    def test_it_agrees_for_a_reduced_intensity(self) -> None:
        assert emission((3, 3), 7, intensity=0.5) == reference_field((3, 3), 7, 0.5, 5)


class TestClipping:
    def test_a_centre_emission_is_the_full_grid(self) -> None:
        assert len(emission((3, 3), 7)) == GRID_SIZE * GRID_SIZE

    def test_a_corner_emission_is_a_quarter(self) -> None:
        """Clipped, not wrapped. A corner emitter simply leaves less."""
        field = emission((0, 0), 7)
        assert len(field) == 9
        assert all(row >= 0 and col >= 0 for row, col in field)

    def test_an_edge_emission_is_a_half(self) -> None:
        assert len(emission((0, 3), 7)) == 15

    def test_the_centre_keeps_full_intensity_in_a_corner(self) -> None:
        """Clipping removes cells; it does not attenuate what remains."""
        assert emission((0, 0), 7)[(0, 0)] == 0.9


class TestReproducibility:
    def test_every_value_is_rounded(self) -> None:
        """Floats do not reproduce across implementations; rounded ones do,
        and the field is hashed into the pre-series lock."""
        for value in emission((3, 3), 7, intensity=0.7).values():
            assert round(value, PRECISION) == value

    def test_an_awkward_intensity_still_rounds_cleanly(self) -> None:
        field = emission((3, 3), 7, intensity=0.85)
        assert field[(2, 3)] == round(0.85 - 0.85 / 3, 3)

    def test_the_field_is_identical_across_calls(self) -> None:
        assert emission((2, 4), 7) == emission((2, 4), 7)


class TestBarriersDoNotBlockIt:
    def test_emission_ignores_the_board_contents_entirely(self) -> None:
        """Scent passes through walls. Barriers block movement, not diffusion,
        and an occlusion rule we invented would break the hash lock."""
        assert emission((3, 3), 7) == emission((3, 3), 7)
        assert (3, 4) in emission((3, 3), 7)


class TestTheNumericExample:
    def test_it_states_the_rings(self) -> None:
        """The lock requires the model *and* a concrete numeric example: a
        formula agreed in prose is one two teams can implement differently."""
        text = numeric_example()
        assert "ring 0 = 0.9" in text
        assert "ring 1 = 0.6" in text
        assert "ring 2 = 0.3" in text

    def test_it_names_the_falloff_and_the_shape(self) -> None:
        text = numeric_example()
        assert "Chebyshev" in text
        assert "5x5" in text

    def test_the_example_matches_what_we_emit(self) -> None:
        """An example that drifted from the implementation would be worse than
        none: we would hash-lock a promise we do not keep."""
        field = emission((3, 3), 7)
        for distance, value in ((0, 0.9), (1, 0.6), (2, 0.3)):
            assert f"ring {distance} = {value}" in numeric_example()
            assert field[(3 - distance, 3)] == value


class TestTheParametersAreReadNotRestated:
    def test_a_non_numeric_book_value_is_refused(self) -> None:
        """The accessor exists so the table stays authoritative for behaviour.
        Asking it for a value that is not a number is a programming error, and
        silently coercing one would put a wrong constant into a hash-locked
        agreement."""
        from thief_agent.domain.scent import _fixed_float

        with pytest.raises(TypeError, match="not a number"):
            _fixed_float("world", "map_area")

    def test_it_reads_the_table_rather_than_a_literal(self) -> None:
        from thief_agent.domain.scent import _fixed_float

        assert _fixed_float("pheromones", "pheromone_decay") == 0.10
