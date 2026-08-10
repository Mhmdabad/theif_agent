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
from .replay_frame import frame
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


def draw_replay(replay: Replay, grid: int, painter: CanvasPainter) -> str:
    """One frame of the Replay App: the step on screen, under the log's stamp.

    The verdict is computed over the *whole* log rather than the step on screen.
    A viewer that stamped each step as the reader arrived at it would show
    ``Verified OK`` on a tampered log for as long as the reader stayed early in
    it, which is the one thing this window must never do.

    The board underneath is the opposite: it is *only* the current step, because
    that is what makes the arrow keys mean anything. Drawing nothing here was a
    bug and a quiet one — the controls worked, the cursor moved, the verdict was
    right, and the window looked frozen because the one thing that varies from
    step to step was never painted.

    ``grid`` is passed in rather than taken from the frame so the stamp spans
    the canvas even on a step that reveals no board. Deriving it here from the
    frame is how the stamp came to be drawn one cell wide: the strip was sized
    from a placeholder, and a ``Verified OK`` far wider than its own banner is
    the one graphic in this project an examiner is required to photograph.

    The stamp goes down **first**, before the board. The two do not overlap —
    the banner owns the strip above ``BANNER_HEIGHT`` and the board everything
    below — so the order is free on screen and not free in the tests, which
    read the verdict off the first rectangle painted. Keeping it first is what
    lets them go on asserting the thing they care about.
    """
    result = walk(replay)
    view = frame(replay.current)
    painter.clear()
    paint_stamp(result.stamp.text, STAMP_COLOUR[result.stamp], grid, painter)
    if view is not None:
        paint_board(view, painter)
    return str(result)
