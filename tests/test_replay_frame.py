"""A recorded step becomes a board, and a malformed one becomes nothing.

The Replay App is a submission requirement and its screenshot is evidence, so
the frame it draws is worth asserting on without a display. Two properties
carry the weight: the frame says what the log said, and the opponent's cell is
absent from it because it was absent from the file.
"""

from typing import Any

import pytest

from thief_agent.ui.replay_frame import BOOK_GRID, frame, grid_of
from thief_agent.ui.replay_model import RecordedStep, Replay
from thief_agent.ui.view import BARRIER, EMPTY


def a_reveal(**changes: object) -> dict[str, Any]:
    body: dict[str, Any] = {
        "role": "police",
        "move": "barrier",
        "intent": "truth",
        "hint": "took the west road",
        "barrier_placed": [0, 1],
        "scent": {"0,0": 0.9, "0,1": 0.617, "2,2": 0.044},
        "state": {"grid_size": 7, "self": [0, 0], "barriers": [[0, 1]], "step": 1},
    }
    body.update(changes)
    return body


def a_step(step: int = 1, **changes: object) -> RecordedStep:
    return RecordedStep(step=step, commit="a" * 64, reveal=a_reveal(**changes), nonce="b" * 32)


def a_replay(*steps: RecordedStep) -> Replay:
    return Replay(game_id="G", sub_game=3, role="police", steps=steps or (a_step(),))


class TestTheFrameSaysWhatTheLogSaid:
    def test_the_board_is_the_side_the_log_recorded(self) -> None:
        view = frame(a_step())
        assert view is not None
        assert view.grid_size == 7
        assert len(view.cells) == 49

    def test_the_authors_own_cell_carries_its_roles_letter(self) -> None:
        view = frame(a_step())
        assert view is not None
        assert view.at((0, 0)).glyph == "C"

    def test_a_thiefs_log_carries_the_thiefs_letter(self) -> None:
        view = frame(a_step(role="thief"))
        assert view is not None
        assert view.at((0, 0)).glyph == "T"

    def test_recorded_barriers_are_drawn_as_barriers(self) -> None:
        view = frame(a_step())
        assert view is not None
        assert view.at((0, 1)).glyph == BARRIER

    def test_every_other_square_is_empty(self) -> None:
        view = frame(a_step())
        assert view is not None
        assert view.at((3, 3)).glyph == EMPTY

    def test_heat_is_the_emitted_scent_and_zero_where_none_was_left(self) -> None:
        view = frame(a_step())
        assert view is not None
        assert view.at((0, 0)).heat == pytest.approx(0.9)
        assert view.at((2, 2)).heat == pytest.approx(0.044)
        assert view.at((6, 6)).heat == 0.0

    def test_the_step_number_comes_from_the_sealed_state(self) -> None:
        view = frame(a_step(state={"grid_size": 7, "self": [1, 1], "step": 12}))
        assert view is not None
        assert view.step == 12


class TestNoOpponentCellCanReachTheFrame:
    def test_a_reveal_naming_the_opponent_still_draws_only_the_author(self) -> None:
        """Mandatory rules 8 and 9: local truth, enforced by absence.

        A peer that volunteered its rival's cell — or a hand-edited log that
        added one — must not put a second marker on the board. Nothing reads
        the key, so nothing can draw it.
        """
        view = frame(a_step(opponent=[5, 5], their_cell=[5, 5]))
        assert view is not None
        drawn = [cell for cell in view.cells if cell.glyph not in (EMPTY, BARRIER)]
        assert [(cell.row, cell.col) for cell in drawn] == [(0, 0)]

    def test_no_square_is_ever_marked_as_suspected(self) -> None:
        """A replay shades by where the author *was*, not where anyone guessed."""
        view = frame(a_step())
        assert view is not None
        assert view.suspected is None


class TestAMalformedRevealDrawsNothingRatherThanCrashing:
    @pytest.mark.parametrize(
        "state",
        [
            {"grid_size": 0, "self": [0, 0]},
            {"grid_size": "seven", "self": [0, 0]},
            {"grid_size": True, "self": [0, 0]},
            {"self": [0, 0]},
            "not a mapping",
        ],
        ids=["zero", "text", "bool", "absent", "not-a-mapping"],
    )
    def test_an_unusable_state_yields_no_frame(self, state: object) -> None:
        assert frame(a_step(state=state)) is None

    def test_a_step_that_was_never_opened_yields_no_frame(self) -> None:
        assert frame(RecordedStep(step=1, commit="a" * 64, reveal=None, nonce=None)) is None

    @pytest.mark.parametrize(
        "scent",
        [{"nine": 0.5}, {"0,0": "warm"}, {"0,0": True}, [], None],
        ids=["bad-key", "text-value", "bool-value", "list", "none"],
    )
    def test_an_unreadable_scent_leaves_the_board_cold(self, scent: object) -> None:
        view = frame(a_step(scent=scent))
        assert view is not None
        assert all(cell.heat == 0.0 for cell in view.cells)

    @pytest.mark.parametrize("barriers", [["0,1"], [[0]], [[0, 1, 2]], "none", None])
    def test_unreadable_barriers_are_simply_not_drawn(self, barriers: object) -> None:
        view = frame(a_step(state={"grid_size": 7, "self": [0, 0], "barriers": barriers}))
        assert view is not None
        assert all(cell.glyph != BARRIER for cell in view.cells)


class TestTheWindowSizesItselfFromTheLog:
    def test_the_side_comes_from_the_first_step_that_names_one(self) -> None:
        assert grid_of(a_replay(a_step(state={"grid_size": 9, "self": [0, 0]}))) == 9

    def test_a_log_naming_no_side_falls_back_to_the_books_floor(self) -> None:
        blind = RecordedStep(step=1, commit="a" * 64, reveal=None, nonce=None)
        assert grid_of(a_replay(blind)) == BOOK_GRID == 7

    def test_an_unopened_first_step_does_not_hide_a_later_side(self) -> None:
        blind = RecordedStep(step=1, commit="a" * 64, reveal=None, nonce=None)
        assert grid_of(a_replay(blind, a_step(2, state={"grid_size": 11, "self": [0, 0]}))) == 11
