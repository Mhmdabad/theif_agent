"""Tests for the negotiated coordinate convention."""

import json
from pathlib import Path

import pytest

from thief_agent.domain.axes import ORIGIN_CORNERS, AxisConvention, OriginCorner
from thief_agent.domain.board import DELTAS, MOVES


class TestDefaults:
    def test_default_matches_the_book(self) -> None:
        axes = AxisConvention()
        assert axes.origin_corner == "top-left"
        assert axes.start_index == 0

    def test_default_deltas_agree_with_the_board_module(self) -> None:
        """Guards the two sources of the default from drifting apart."""
        assert AxisConvention().deltas == DELTAS

    def test_shipped_config_uses_the_default(self) -> None:
        cfg = json.loads((Path(__file__).parents[1] / "config/game.json").read_text())
        axes = AxisConvention.from_config(cfg["board_and_agents"])
        assert axes == AxisConvention()


class TestValidation:
    def test_rejects_unknown_corner(self) -> None:
        with pytest.raises(ValueError, match="origin_corner"):
            AxisConvention(origin_corner="middle")  # type: ignore[arg-type]

    def test_rejects_negative_start_index(self) -> None:
        with pytest.raises(ValueError, match="start_index"):
            AxisConvention(start_index=-1)

    def test_is_frozen_and_hashable(self) -> None:
        assert len({AxisConvention(), AxisConvention()}) == 1


class TestDeltas:
    @pytest.mark.parametrize("corner", ORIGIN_CORNERS)
    def test_every_corner_defines_every_move(self, corner: OriginCorner) -> None:
        assert set(AxisConvention(origin_corner=corner).deltas) == set(MOVES)

    @pytest.mark.parametrize("corner", ORIGIN_CORNERS)
    def test_no_delta_is_ever_diagonal(self, corner: OriginCorner) -> None:
        for move, (drow, dcol) in AxisConvention(origin_corner=corner).deltas.items():
            assert drow == 0 or dcol == 0, f"{corner}/{move} is diagonal"

    @pytest.mark.parametrize("corner", ORIGIN_CORNERS)
    def test_opposite_moves_cancel(self, corner: OriginCorner) -> None:
        deltas = AxisConvention(origin_corner=corner).deltas
        assert deltas["N"] == (-deltas["S"][0], -deltas["S"][1])
        assert deltas["E"] == (-deltas["W"][0], -deltas["W"][1])

    def test_top_origin_means_north_decreases_row(self) -> None:
        assert AxisConvention(origin_corner="top-left").deltas["N"] == (-1, 0)
        assert AxisConvention(origin_corner="top-right").deltas["N"] == (-1, 0)

    def test_bottom_origin_flips_the_vertical_axis(self) -> None:
        assert AxisConvention(origin_corner="bottom-left").deltas["N"] == (1, 0)
        assert AxisConvention(origin_corner="bottom-right").deltas["N"] == (1, 0)

    def test_right_origin_flips_the_horizontal_axis(self) -> None:
        assert AxisConvention(origin_corner="top-left").deltas["E"] == (0, 1)
        assert AxisConvention(origin_corner="top-right").deltas["E"] == (0, -1)

    def test_stay_never_moves(self) -> None:
        for corner in ORIGIN_CORNERS:
            assert AxisConvention(origin_corner=corner).deltas["STAY"] == (0, 0)


class TestIndexBase:
    def test_zero_indexed_is_identity(self) -> None:
        axes = AxisConvention()
        assert axes.to_external((3, 3)) == (3, 3)
        assert axes.from_external((3, 3)) == (3, 3)

    def test_one_indexed_config_shifts_every_cell(self) -> None:
        """Acceptance criterion: a 1-indexed config shifts cells consistently."""
        axes = AxisConvention(start_index=1)
        for row in range(7):
            for col in range(7):
                assert axes.to_external((row, col)) == (row + 1, col + 1)

    def test_round_trip_is_lossless(self) -> None:
        for start in (0, 1, 5):
            axes = AxisConvention(start_index=start)
            for pos in ((0, 0), (3, 3), (6, 6)):
                assert axes.from_external(axes.to_external(pos)) == pos

    def test_mismatched_bases_disagree_on_the_same_label(self) -> None:
        """Why both peers must agree: [3,3] means different cells otherwise."""
        zero, one = AxisConvention(), AxisConvention(start_index=1)
        assert zero.from_external((3, 3)) != one.from_external((3, 3))


class TestFromConfig:
    def test_reads_both_values(self) -> None:
        axes = AxisConvention.from_config(
            {"axis_origin_corner": "bottom-right", "axis_start_index": 1}
        )
        assert axes.origin_corner == "bottom-right"
        assert axes.start_index == 1

    def test_absent_keys_fall_back_to_the_book_default(self) -> None:
        assert AxisConvention.from_config({}) == AxisConvention()
