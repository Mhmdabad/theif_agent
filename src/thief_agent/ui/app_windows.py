"""The two ``run_*`` functions, the only code here that touches a real display.

Split out of :mod:`.app`. Both are marked uncovered: a test that opened a window
would need a display CI does not have, and would prove nothing the layout tests
do not already prove.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from ..domain.belief import Belief
from .app_frames import draw_live, draw_replay
from .app_painter import CanvasPainter
from .paint import BANNER_HEIGHT, HEAT, board_size
from .replay import ReplayError, load


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
