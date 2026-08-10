"""The board one recorded step describes, rebuilt without a window.

The verdict is arithmetic and needs no picture, but the rulebook asks the
Replay App to let a reader *walk* a recorded sub-game, forward and back. A
window that stamps a verdict over an empty canvas gives them nothing to walk
through: every step looks the same, so the controls appear broken even when the
cryptography is perfect. This module turns one :class:`.replay_model.RecordedStep`
back into the :class:`~.view.View` the live window already knows how to draw, so
both windows share one drawing routine and a replayed barrier cannot come out
looking different from a live one.

**A replayed frame is still local truth.** The only board it can describe is the
one the log's own author sealed: ``state.self`` is that author's cell,
``state.barriers`` the squares it had seen closed, ``scent`` the field it
emitted. The opponent's position was never written to the file, so the rule
against a bird's-eye view (mandatory rules 8 and 9) holds here the way it holds
in :func:`~.view.render` — by absence. There is no argument, and no key, that
could carry it.

The heat channel therefore carries **scent** rather than belief, and the
difference is worth naming rather than glossing: the live window shades by where
the opponent probably *is*, this one by where the author demonstrably *was*.
Both are honest and neither is the other.

Nothing here raises. A log that survived :func:`~.replay.load` is structurally a
log, but a ``reveal`` is a record the *opponent* composed, and a viewer that
crashed on a malformed field would be reporting their bad data as our bug.
Anything unreadable yields ``None``, and the window draws the verdict alone.
"""

from typing import Any

from ..domain.board import Position
from .replay_model import RecordedStep, Replay
from .view import BARRIER, EMPTY, Cell, View

__all__ = ["BOOK_GRID", "GLYPH", "frame", "grid_of"]

GLYPH = {"police": "C", "thief": "T"}
"""Whose letter sits on the author's cell, chosen by the role the *log* names.

Hard-coded here and a parameter in :func:`~.view.render`, for the same reason in
both places. The live window draws the role this repository plays, which is what
differs between the two; a replay draws the role its file names, which does not.
"""

BOOK_GRID = 7
"""Fallback side when no step names one. Appendix F table 13 row 1."""


def _position(value: object) -> Position | None:
    """A ``[row, col]`` pair, or ``None`` for anything that is not one."""
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    row, col = value
    if isinstance(row, bool) or isinstance(col, bool):
        return None
    if not isinstance(row, int) or not isinstance(col, int):
        return None
    return (row, col)


def _positive(value: object) -> int | None:
    """A positive integer — a grid side or a step number — or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _barriers(value: object) -> set[Position]:
    if not isinstance(value, list):
        return set()
    return {cell for cell in map(_position, value) if cell is not None}


def _scent(value: object) -> dict[Position, float]:
    """The emitted field, keyed ``"row,col"`` the way the wire records it."""
    if not isinstance(value, dict):
        return {}
    trail: dict[Position, float] = {}
    for key, intensity in value.items():
        row, _, col = str(key).partition(",")
        if not row.lstrip("-").isdigit() or not col.lstrip("-").isdigit():
            continue
        if isinstance(intensity, bool) or not isinstance(intensity, int | float):
            continue
        trail[(int(row), int(col))] = float(intensity)
    return trail


def _state(recorded: RecordedStep) -> dict[str, Any] | None:
    reveal = recorded.reveal
    if reveal is None:
        return None
    state = reveal.get("state")
    return state if isinstance(state, dict) else None


def grid_of(replay: Replay) -> int:
    """The board's side, from the first step that names one.

    Read from the log rather than assumed, because the side is negotiable above
    the book's floor: a window hard-coded to one number draws a wrong-sized
    board for every pair that agreed a larger one, and draws it convincingly.
    """
    for recorded in replay.steps:
        state = _state(recorded)
        side = _positive(state.get("grid_size")) if state else None
        if side is not None:
            return side
    return BOOK_GRID


def frame(recorded: RecordedStep) -> View | None:
    """The board this step reveals, or ``None`` if it revealed nothing usable."""
    state = _state(recorded)
    reveal = recorded.reveal
    if state is None or reveal is None:
        return None
    side = _positive(state.get("grid_size"))
    if side is None:
        return None
    ours = _position(state.get("self"))
    barriers = _barriers(state.get("barriers"))
    trail = _scent(reveal.get("scent"))
    role = str(reveal.get("role", ""))
    mine = GLYPH.get(role, "?")
    cells = []
    for row in range(side):
        for col in range(side):
            here = (row, col)
            if here == ours:
                glyph = mine
            elif here in barriers:
                glyph = BARRIER
            else:
                glyph = EMPTY
            cells.append(Cell(row=row, col=col, glyph=glyph, heat=trail.get(here, 0.0)))
    numbered = _positive(state.get("step"))
    return View(
        role=role,
        cells=tuple(cells),
        grid_size=side,
        suspected=None,
        step=numbered if numbered is not None else recorded.step,
    )
