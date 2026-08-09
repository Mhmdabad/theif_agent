"""One frame of each window: what the live board draws, and what the replay stamps.

Split out of :mod:`.app`. Neither function is handed the opponent's true cell —
:func:`~.view.render` has no parameter for it, so the leak is impossible rather
than merely avoided.
"""

from ..domain.belief import Belief
from ..domain.board import BoardState, Position
from .app_painter import CanvasPainter
from .paint import paint_board, paint_stamp
from .replay import Replay
from .verdict import Stamp, walk
from .view import render

STAMP_COLOUR = {
    Stamp.VERIFIED_OK: "#2f9e44",
    Stamp.TAMPERED: "#e03131",
    Stamp.INCOMPLETE: "#868e96",
}
"""Green, blazing red, grey. FR-7.12 names the first two."""


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
