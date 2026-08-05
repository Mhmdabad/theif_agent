"""The two windows a person actually looks at, and the screenshots FR-7.14 wants.

Two apps, both Tkinter:

* ``python -m thief_agent.ui.app live`` — the board as *we* see it, with the
  belief heatmap and the turn banner.
* ``python -m thief_agent.ui.app replay <log.json>`` — a recorded sub-game,
  stepped with the arrow keys, stamped ``Verified OK`` or ``TAMPERED``.

**The live window is never handed the opponent's true cell.** Not "does not draw
it" — is not given it. :func:`~.view.render` has no parameter for it, so the
window physically cannot leak what the agent is not supposed to know, and that
is enforced by a signature rather than by discipline.

**Almost nothing here is Tk.** The layout is computed in :mod:`.paint` against a
Protocol and tested against a recording painter; :class:`CanvasPainter` is four
delegating lines, tested against a fake canvas. Only the two ``run_*`` functions
touch a real display, and they are marked uncovered — a test that opened a
window would need a display CI does not have, and would prove nothing the layout
tests do not already prove.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from ..domain.belief import Belief
from ..domain.board import BoardState, Position
from .paint import BANNER_HEIGHT, CELL, HEAT, board_size, paint_board, paint_stamp
from .replay import Replay, ReplayError, load
from .verdict import Stamp, walk
from .view import render

STAMP_COLOUR = {
    Stamp.VERIFIED_OK: "#2f9e44",
    Stamp.TAMPERED: "#e03131",
    Stamp.INCOMPLETE: "#868e96",
}
"""Green, blazing red, grey. FR-7.12 names the first two."""


class Canvas(Protocol):
    """The slice of ``tkinter.Canvas`` this module uses.

    Describes the exact three calls made below, not the library. A looser
    Protocol — ``*args: object`` — reads as more accommodating and is in fact
    *stricter on the implementation*: it promises callers may pass anything,
    which a real ``tkinter.Canvas`` does not honour, so the real canvas would
    not satisfy it. That is the same mistake ``ToolHost`` made about ``FastMCP``
    in #285, caught here by mypy for the same reason: a Protocol is only true
    once something concrete is passed to it.
    """

    def create_rectangle(
        self, x0: int, y0: int, x1: int, y1: int, *, fill: str, outline: str
    ) -> object: ...

    def create_text(
        self, x: int, y: int, *, text: str, fill: str, font: tuple[str, int]
    ) -> object: ...

    def delete(self, tag: str) -> object: ...


class CanvasPainter:
    """Adapts a Tk canvas to :class:`~.paint.Painter`. Four lines, no logic."""

    def __init__(self, canvas: Canvas) -> None:
        self.canvas = canvas

    def rectangle(self, x0: int, y0: int, x1: int, y1: int, fill: str, outline: str) -> None:
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline)

    def text(self, x: int, y: int, body: str, fill: str) -> None:
        self.canvas.create_text(x, y, text=body, fill=fill, font=("TkFixedFont", CELL // 2))

    def clear(self) -> None:
        self.canvas.delete("all")


def draw_live(
    state: BoardState, belief: Belief, role: str, ours: Position, painter: CanvasPainter
) -> None:
    """One frame of the live window.

    ``render`` is given our position and our belief, and nothing else. There is
    no argument through which the opponent's true cell could arrive.
    """
    glyph, other = ("C", "T") if role == "police" else ("T", "C")
    view = render(state, belief, role, ours, glyph, other)
    painter.clear()
    paint_board(view, painter)


def draw_replay(replay: Replay, painter: CanvasPainter) -> str:
    """One frame of the Replay App, and the stamp that goes above it.

    The verdict is computed over the *whole* log rather than the step on screen.
    A viewer that stamped each step as the reader arrived at it would show
    ``Verified OK`` on a tampered log for as long as the reader stayed early in
    it, which is the one thing this window must never do.
    """
    result = walk(replay)
    painter.clear()
    paint_stamp(result.stamp.text, STAMP_COLOUR[result.stamp], 1, painter)
    return str(result)


def run_live(argv: Sequence[str]) -> int:  # pragma: no cover - needs a display
    """Open the live window. Not covered: a test would need a display."""
    import tkinter as tk

    from ..domain.board import BoardState

    state = BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0)
    belief = Belief.uniform(state)
    width, height = board_size(state.grid_size)

    root = tk.Tk()
    root.title(f"{__package__} — live")
    canvas = tk.Canvas(root, width=width, height=height, background="#111318", highlightthickness=0)
    canvas.pack()
    draw_live(state, belief, "police", state.cop, CanvasPainter(canvas))
    root.mainloop()
    return 0


def run_replay(path: Path) -> int:  # pragma: no cover - needs a display
    """Open the Replay App on ``path``, arrow keys to step."""
    import tkinter as tk

    try:
        replay = load(path)
    except ReplayError as exc:
        print(f"cannot replay {path}: {exc}", file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title(f"{__package__} — replay {path.name}")
    width, height = board_size(8)
    canvas = tk.Canvas(root, width=width, height=height + BANNER_HEIGHT, background=HEAT[0])
    canvas.pack()
    painter = CanvasPainter(canvas)
    label = tk.Label(root, text="", anchor="w", background=HEAT[0], foreground="#f8f9fa")
    label.pack(fill="x")

    def refresh() -> None:
        summary = draw_replay(replay, painter)
        label.config(text=f"step {replay.current.step} of {replay.numbers()} — {summary}")

    def step_forward(_: object) -> None:
        replay.forward()
        refresh()

    def step_back(_: object) -> None:
        replay.back()
        refresh()

    root.bind("<Right>", step_forward)
    root.bind("<Left>", step_back)
    refresh()
    root.mainloop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Pick a window. Returns an exit code rather than raising."""
    parser = argparse.ArgumentParser(prog=f"python -m {__package__}.app")
    parser.add_argument("window", choices=("live", "replay"))
    parser.add_argument("log", nargs="?", type=Path, help="log_<game_id>_g<NN>.json, for replay")
    arguments = parser.parse_args(argv)

    if arguments.window == "replay":
        if arguments.log is None:
            print("replay needs a log file", file=sys.stderr)
            return 1
        return run_replay(arguments.log)
    return run_live([])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
