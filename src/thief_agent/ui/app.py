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

from .app_frames import STAMP_COLOUR, draw_live, draw_replay
from .app_painter import Canvas, CanvasPainter
from .app_windows import run_live, run_replay

__all__ = [
    "STAMP_COLOUR",
    "Canvas",
    "CanvasPainter",
    "draw_live",
    "draw_replay",
    "main",
    "run_live",
    "run_replay",
]


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
