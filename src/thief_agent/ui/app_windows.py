"""The two ``run_*`` functions, the only code here that touches a real display.

Split out of :mod:`.app`. Both are marked uncovered: a test that opened a window
would need a display CI does not have, and would prove nothing the layout tests
do not already prove.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from ..cli_identity import ROLE
from ..domain.belief import Belief
from .app_frames import draw_live, draw_replay
from .app_painter import CanvasPainter
from .paint import HEAT, TEXT, board_size
from .replay import ReplayError, load
from .replay_frame import grid_of


def run_live(argv: Sequence[str]) -> int:  # pragma: no cover - needs a display
    """Open the live window. Not covered: a test would need a display."""
    import tkinter as tk

    from ..domain.board import BoardState

    state = BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0)
    belief = Belief.uniform(state)
    width, height = board_size(state.grid_size)

    # Our own role and our own cell, never the opponent's: the live window shows
    # local truth only (mandatory rules 8 and 9). ``ROLE`` comes from
    # :mod:`..cli_identity`, so each repository draws the side it plays.
    ours = state.cop if ROLE == "police" else state.thief

    root = tk.Tk()
    root.title(f"{__package__} — live")
    canvas = tk.Canvas(root, width=width, height=height, background="#111318", highlightthickness=0)
    canvas.pack()
    draw_live(state, belief, ROLE, ours, CanvasPainter(canvas))
    root.mainloop()
    return 0


def run_replay(path: Path) -> int:  # pragma: no cover - needs a display
    """Open the Replay App on ``path``. Buttons or arrow keys walk the log.

    The rulebook asks for control buttons, and they earn their place beyond
    compliance: an examiner opening this window has no reason to guess that the
    arrow keys do anything, and a viewer whose controls are invisible is one
    that gets reported as broken.

    The canvas is sized from the log's own board rather than a constant. The
    side is negotiable above the book's floor, so a fixed number renders a
    convincing picture of the wrong board for every pair that agreed a larger
    one — and this window's whole purpose is to be believed.
    """
    import tkinter as tk

    try:
        replay = load(path)
    except ReplayError as exc:
        print(f"cannot replay {path}: {exc}", file=sys.stderr)
        return 1

    grid = grid_of(replay)
    root = tk.Tk()
    root.title(f"{__package__} — replay {path.name}")
    width, height = board_size(grid)
    canvas = tk.Canvas(root, width=width, height=height, background=HEAT[0], highlightthickness=0)
    canvas.pack()
    painter = CanvasPainter(canvas)
    caption = tk.Label(root, text="", anchor="w", background=HEAT[0], foreground=TEXT)
    caption.pack(fill="x")
    status = tk.Label(root, text="", anchor="w", background=HEAT[0], foreground=TEXT)
    status.pack(fill="x")
    controls = tk.Frame(root, background=HEAT[0])
    controls.pack(fill="x")

    def refresh() -> None:
        summary = draw_replay(replay, grid, painter)
        reveal = replay.current.reveal or {}
        caption.config(
            text=f"{replay.role} · sub-game {replay.sub_game} · "
            f"{reveal.get('move', '-')} · {reveal.get('intent', '-')} · "
            f'"{reveal.get("hint", "")}"'
        )
        status.config(text=f"step {replay.current.step} of {replay.numbers()[-1]} — {summary}")

    def first(_: object = None) -> None:
        replay.seek(replay.numbers()[0])
        refresh()

    def previous(_: object = None) -> None:
        replay.back()
        refresh()

    def following(_: object = None) -> None:
        replay.forward()
        refresh()

    def last(_: object = None) -> None:
        replay.seek(replay.numbers()[-1])
        refresh()

    for text, command in (
        ("|< first", first),
        ("< prev", previous),
        ("next >", following),
        ("last >|", last),
    ):
        tk.Button(controls, text=text, command=command).pack(side="left", padx=2, pady=2)

    root.bind("<Left>", previous)
    root.bind("<Right>", following)
    root.bind("<Home>", first)
    root.bind("<End>", last)
    refresh()
    root.mainloop()
    return 0
