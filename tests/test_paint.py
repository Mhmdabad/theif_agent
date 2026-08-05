"""What the window draws, checked without opening one."""

from pathlib import Path
from typing import NamedTuple

import pytest

from thief_agent.domain.belief import Belief
from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.infra.ceremony import StepCeremony
from thief_agent.infra.match_log import MatchLog
from thief_agent.ui.app import STAMP_COLOUR, CanvasPainter, draw_live, draw_replay, main
from thief_agent.ui.banner import Tone, banner
from thief_agent.ui.paint import (
    BARRIER_FILL,
    HEAT,
    OURS,
    SUSPECT,
    board_size,
    cell_box,
    paint_banner,
    paint_board,
)
from thief_agent.ui.replay import load
from thief_agent.ui.verdict import Stamp
from thief_agent.ui.view import View, render


class Rect(NamedTuple):
    x0: int
    y0: int
    x1: int
    y1: int
    fill: str
    outline: str


class Text(NamedTuple):
    x: int
    y: int
    body: str
    fill: str


class Recording:
    """A painter that keeps everything, so the layout can be read back."""

    def __init__(self) -> None:
        self.rects: list[Rect] = []
        self.texts: list[Text] = []

    def rectangle(self, x0: int, y0: int, x1: int, y1: int, fill: str, outline: str) -> None:
        self.rects.append(Rect(x0, y0, x1, y1, fill, outline))

    def text(self, x: int, y: int, body: str, fill: str) -> None:
        self.texts.append(Text(x, y, body, fill))

    def clear(self) -> None:
        self.rects.clear()
        self.texts.clear()

    def fill_at(self, cell: tuple[int, int]) -> str:
        x0, y0, _, _ = cell_box(cell)
        return next(r.fill for r in self.rects if (r.x0, r.y0) == (x0, y0))

    def glyph_at(self, cell: tuple[int, int]) -> str:
        x0, y0, x1, y1 = cell_box(cell)
        centre = ((x0 + x1) // 2, (y0 + y1) // 2)
        return next((t.body for t in self.texts if (t.x, t.y) == centre), "")


def a_board(grid: int = 6) -> BoardState:
    # The cop sits away from (0, 0) on purpose: a uniform belief peaks on the
    # first cell, and a board where our marker and the suspect marker coincide
    # cannot tell the two colours apart.
    return BoardState(
        grid_size=grid, cop=(3, 3), thief=(4, 4), barriers=frozenset({(2, 2)}), step=3
    )


def a_view(state: BoardState | None = None, belief: Belief | None = None) -> View:
    board = state or a_board()
    return render(board, belief or Belief.uniform(board), "thief", board.cop, "C", "T")


class TestTheBoardIsDrawn:
    def test_every_square_gets_a_rectangle(self) -> None:
        painter = Recording()
        paint_board(a_view(), painter)
        assert len(painter.rects) == 36

    def test_our_position_carries_our_glyph(self) -> None:
        painter = Recording()
        paint_board(a_view(), painter)
        assert painter.glyph_at((3, 3)) == "C"

    def test_a_barrier_cell_is_darker_than_the_coldest_belief(self) -> None:
        """A barrier is not a cell with no belief; it must not read as one."""
        painter = Recording()
        paint_board(a_view(), painter)
        assert painter.fill_at((2, 2)) == BARRIER_FILL
        assert HEAT[0] != BARRIER_FILL

    def test_a_barrier_carries_no_glyph(self) -> None:
        painter = Recording()
        paint_board(a_view(), painter)
        assert painter.glyph_at((2, 2)) == ""

    def test_rows_map_to_y_and_columns_to_x(self) -> None:
        """A board drawn transposed is a mirror of the truth and looks fine."""
        first, second = cell_box((0, 1)), cell_box((1, 0))
        assert first[0] > second[0], "column should move x"
        assert second[1] > first[1], "row should move y"


class TestDeeperRedMeansHigherProbability:
    def test_the_peak_is_the_hottest_band(self) -> None:
        """Whatever the belief, its argmax is the reddest square on the board."""
        painter = Recording()
        view = a_view()
        paint_board(view, painter)
        assert view.suspected is not None
        assert painter.fill_at(view.suspected) == HEAT[-1]

    def test_our_own_marker_is_never_the_suspect_colour(self) -> None:
        """Even when the belief peaks on our own cell — same pixel, opposite meaning."""
        state = BoardState(grid_size=6, cop=(0, 0), thief=(4, 4), barriers=frozenset(), step=1)
        painter = Recording()
        view = a_view(state)
        paint_board(view, painter)
        assert view.suspected == (0, 0), "the belief should peak on our own cell here"
        assert [t.fill for t in painter.texts if t.body == "C"] == [OURS]

    def test_the_suspected_cell_is_marked_and_coloured_apart(self) -> None:
        painter = Recording()
        view = a_view()
        paint_board(view, painter)
        assert view.suspected is not None
        marked = [t for t in painter.texts if t.fill == SUSPECT]
        assert len(marked) == 1
        assert marked[0].body == "T?", "the mark is a guess about the thief, not a bare ?"

    def test_our_marker_is_not_the_suspect_colour(self) -> None:
        painter = Recording()
        paint_board(a_view(), painter)
        ours = [t for t in painter.texts if t.body == "C"]
        assert ours and ours[0].fill == OURS

    def test_the_bands_run_dark_to_red(self) -> None:
        """Not a presentation preference — FR-7.14 wants this photographed."""
        assert len(HEAT) == 5
        assert HEAT[0] != HEAT[-1]


class TestTheBanner:
    def test_a_live_turn_is_drawn_in_its_tone(self) -> None:
        painter = Recording()
        paint_banner(banner(StepCeremony(step=1, role="thief")), 6, painter)
        assert painter.rects[0].fill == Tone.GO.value

    def test_the_banner_spans_the_window(self) -> None:
        painter = Recording()
        paint_banner(banner(StepCeremony(step=1, role="thief")), 6, painter)
        assert painter.rects[0].x1 == board_size(6)[0]

    def test_the_text_is_drawn(self) -> None:
        painter = Recording()
        paint_banner(banner(StepCeremony(step=1, role="thief")), 6, painter)
        assert "YOUR TURN" in painter.texts[0].body


class TestTheCanvasAdapter:
    """Four delegating lines, checked against a fake canvas."""

    class FakeCanvas:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

        def create_rectangle(self, *coords: object, **options: object) -> object:
            self.calls.append(("rect", coords, options))
            return None

        def create_text(self, *coords: object, **options: object) -> object:
            self.calls.append(("text", coords, options))
            return None

        def delete(self, tag: str) -> object:
            self.calls.append(("delete", (tag,), {}))
            return None

    def test_a_rectangle_reaches_the_canvas(self) -> None:
        canvas = self.FakeCanvas()
        CanvasPainter(canvas).rectangle(1, 2, 3, 4, "#fff", "#000")
        kind, coords, options = canvas.calls[0]
        assert kind == "rect"
        assert coords == (1, 2, 3, 4)
        assert options["fill"] == "#fff"

    def test_text_reaches_the_canvas(self) -> None:
        canvas = self.FakeCanvas()
        CanvasPainter(canvas).text(5, 6, "C", "#fff")
        kind, coords, options = canvas.calls[0]
        assert kind == "text"
        assert options["text"] == "C"

    def test_clear_wipes_everything(self) -> None:
        canvas = self.FakeCanvas()
        CanvasPainter(canvas).clear()
        assert canvas.calls[0] == ("delete", ("all",), {})


class TestTheLiveWindowIsNeverGivenTheirCell:
    def test_drawing_a_frame_uses_only_our_position(self) -> None:
        """Enforced by render()'s signature, exercised here end to end."""
        canvas = TestTheCanvasAdapter.FakeCanvas()
        state = a_board()
        draw_live(state, Belief.uniform(state), "thief", state.cop, CanvasPainter(canvas))
        assert canvas.calls, "nothing was drawn"

    def test_the_thiefs_true_cell_is_not_drawn_as_a_certainty(self) -> None:
        painter = Recording()
        paint_board(a_view(), painter)
        glyphs = [t.body for t in painter.texts]
        assert "T" not in glyphs, "the opponent's real marker was drawn as a certainty"
        assert "T?" in glyphs, "the belief's peak should be marked as a guess"


def sealed_log(tmp_path: Path, corrupt: bool = False) -> Path:
    log = MatchLog(game_id="uoh26-s82kma9e", sub_game=1, role="thief", game_uid="u-1")
    for step in (1, 2):
        board = BoardState(
            grid_size=6, cop=(1, step), thief=(4, 4), barriers=frozenset(), step=step
        )
        record = step_record(board, "thief", "N", "truth", f"s{step}")
        secret = f"{step:032x}"
        log.commit(step, commit_of(record, secret))
        log.reveal(step, {**record, "move": "S"} if corrupt and step == 2 else record)
        log.disclose(step, secret)
    return log.write(tmp_path)


class TestTheReplayStamp:
    def test_a_clean_log_stamps_green(self, tmp_path: Path) -> None:
        painter = Recording()
        summary = draw_replay(load(sealed_log(tmp_path)), painter)  # type: ignore[arg-type]
        assert painter.rects[0].fill == STAMP_COLOUR[Stamp.VERIFIED_OK]
        assert "Verified OK" in summary

    def test_a_tampered_log_stamps_blazing_red(self, tmp_path: Path) -> None:
        painter = Recording()
        summary = draw_replay(load(sealed_log(tmp_path, corrupt=True)), painter)  # type: ignore[arg-type]
        assert painter.rects[0].fill == STAMP_COLOUR[Stamp.TAMPERED]
        assert "TAMPERED" in summary

    def test_the_verdict_covers_the_whole_log_not_the_step_on_screen(self, tmp_path: Path) -> None:
        """Otherwise a tampered log reads clean while the reader stays early in it."""
        replay = load(sealed_log(tmp_path, corrupt=True))
        assert replay.current.step == 1, "the reader is on an honest step"
        painter = Recording()
        draw_replay(replay, painter)  # type: ignore[arg-type]
        assert painter.rects[0].fill == STAMP_COLOUR[Stamp.TAMPERED]

    def test_the_stamp_says_the_words_the_rulebook_uses(self, tmp_path: Path) -> None:
        painter = Recording()
        draw_replay(load(sealed_log(tmp_path)), painter)  # type: ignore[arg-type]
        assert painter.texts[0].body == "Verified OK"


class TestTheWindowFits:
    @pytest.mark.parametrize("grid", [4, 8, 12])
    def test_it_grows_with_the_board(self, grid: int) -> None:
        width, height = board_size(grid)
        assert width < height, "the banner strip adds to the height"
        assert width > grid * 40


class TestTheCommandLine:
    """The window itself needs a display; choosing one does not."""

    def test_replay_without_a_log_is_refused(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["replay"]) == 1
        assert "needs a log file" in capsys.readouterr().err

    def test_replay_opens_the_named_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[Path] = []

        def record(path: Path) -> int:
            opened.append(path)
            return 0

        monkeypatch.setattr("thief_agent.ui.app.run_replay", record)
        log = sealed_log(tmp_path)
        assert main(["replay", str(log)]) == 0
        assert opened == [log]

    def test_live_needs_no_argument(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("thief_agent.ui.app.run_live", lambda _: 0)
        assert main(["live"]) == 0

    def test_an_unknown_window_is_rejected_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            main(["sideways"])
