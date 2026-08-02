"""Tests for outcome precedence and the Appendix F scoring table."""

import json
from pathlib import Path

import pytest

from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.scoring import (
    BOOK_SCORES,
    BOOK_TIE_SCORE,
    Outcome,
    evaluate,
    scores_for,
    scores_from_config,
)

AXES = AxisConvention()
WALLED = frozenset({(2, 3), (4, 3), (3, 2), (3, 4)})


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


def shipped_scoring() -> dict[str, object]:
    cfg = json.loads((Path(__file__).parents[1] / "config/game.json").read_text())
    return dict(cfg["scoring"])


class TestBookValues:
    def test_scores_match_appendix_f(self) -> None:
        assert BOOK_SCORES[Outcome.CAPTURE] == (20, 5)
        assert BOOK_SCORES[Outcome.SURVIVAL] == (5, 10)
        assert BOOK_SCORES[Outcome.TECHNICAL_LOSS] == (0, 0)
        assert BOOK_TIE_SCORE == 2

    def test_capture_is_the_cops_best_and_survival_the_thiefs(self) -> None:
        assert BOOK_SCORES[Outcome.CAPTURE][0] > BOOK_SCORES[Outcome.SURVIVAL][0]
        assert BOOK_SCORES[Outcome.SURVIVAL][1] > BOOK_SCORES[Outcome.CAPTURE][1]

    def test_shipped_config_matches(self) -> None:
        assert scores_from_config(shipped_scoring()) == BOOK_SCORES


class TestPrecedence:
    def test_ongoing_by_default(self) -> None:
        assert evaluate(make(), AXES) is Outcome.ONGOING

    def test_overlap_is_capture(self) -> None:
        assert evaluate(make(cop=(3, 3), thief=(3, 3)), AXES) is Outcome.CAPTURE

    def test_trapping_is_capture(self) -> None:
        assert evaluate(make(barriers=frozenset({(3, 3)})), AXES) is Outcome.CAPTURE

    def test_enclosure_is_capture(self) -> None:
        assert evaluate(make(barriers=WALLED), AXES) is Outcome.CAPTURE

    def test_survival_at_the_threshold(self) -> None:
        assert evaluate(make(step=35), AXES) is Outcome.SURVIVAL

    def test_capture_beats_survival_on_the_same_turn(self) -> None:
        """The cop closing the last escape as the count matures is a capture."""
        assert evaluate(make(step=40, barriers=WALLED), AXES) is Outcome.CAPTURE

    def test_capture_beats_survival_for_overlap_too(self) -> None:
        assert evaluate(make(cop=(3, 3), thief=(3, 3), step=40), AXES) is Outcome.CAPTURE

    def test_evaluate_never_returns_technical_loss(self) -> None:
        """It is a protocol event, so no board position can produce it."""
        for state in (make(), make(step=40), make(barriers=WALLED)):
            assert evaluate(state, AXES) is not Outcome.TECHNICAL_LOSS

    def test_honours_a_negotiated_threshold(self) -> None:
        assert evaluate(make(step=35), AXES, survival_threshold=50) is Outcome.ONGOING


class TestScoresFor:
    def test_reads_the_book_table_by_default(self) -> None:
        assert scores_for(Outcome.CAPTURE) == (20, 5)

    def test_accepts_an_explicit_table(self) -> None:
        assert scores_for(Outcome.SURVIVAL, BOOK_SCORES) == (5, 10)


class TestFixedValuesAreRefusedWhenAltered:
    @pytest.mark.parametrize(
        "key", ["capture_cop", "capture_thief", "survival_cop", "survival_thief"]
    )
    def test_altered_score_is_rejected(self, key: str) -> None:
        scoring = shipped_scoring()
        scoring[key] = 99
        with pytest.raises(ValueError, match="fixed values may not be renegotiated"):
            scores_from_config(scoring)

    def test_altered_tie_score_is_rejected(self) -> None:
        scoring = shipped_scoring()
        scoring["tie_score"] = 3
        with pytest.raises(ValueError, match="tie_score must be 2"):
            scores_from_config(scoring)

    def test_altered_technical_loss_is_rejected(self) -> None:
        scoring = shipped_scoring()
        scoring["technical_loss"] = 1
        with pytest.raises(ValueError, match="fixed values may not be renegotiated"):
            scores_from_config(scoring)
