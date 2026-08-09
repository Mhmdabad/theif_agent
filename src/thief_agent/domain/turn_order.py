"""Applying both sides' actions to one board when neither saw the other.

Commit-Reveal makes a turn simultaneous: both peers seal an action before
either reveals one, so each chooses against the board as it stood at the start
of the turn. Advancing that board is the one place where "simultaneous" has to
be turned into a sequence, and doing it naively silently breaks the promise.

**The bug this exists to fix.** Both call sites applied one action to the
board and then the other *to the result*, so the second action's legality was
judged against a board that already contained the first. A cop sealing a cell
and a thief stepping into it — chosen in the same turn, neither aware of the
other — resolved as ``thief cannot play S: (5, 6) -> (6, 6)``: a move that was
legal when it was committed, refused because the barrier had been applied
first. The peer that hit it aborted the whole match, which is a technical loss
scoring **zero for both sides**. It reproduced deterministically.

So both actions are validated and resolved against the *pre-turn* board, and
only their effects are merged: each side's new position from its own
resolution, and the union of the barriers. Order stops mattering, which is the
property that makes the two peers' boards agree — and they must, because the
audit re-derives this same sequence and a disagreement here reads as forgery.

**A vacated cell is not a capture.** A cop that seals the square the thief is
leaving no longer catches it: the thief committed to leaving before the
barrier existed. Rule 46's trapping capture still fires on the cell the thief
actually occupies once both actions have landed, which is the only reading
under which the cop is not rewarded for knowledge it did not have.
"""

from dataclasses import replace

from .actions import Action, apply_action
from .axes import AxisConvention
from .board import Agent, BoardState
from .rules import position_of

__all__ = ["advance_both"]


def advance_both(
    state: BoardState,
    mine: Agent,
    ours: Action,
    theirs: Action | None,
    axes: AxisConvention,
    yours: Agent | None = None,
) -> BoardState:
    """One board advanced by both actions, each judged against ``state``.

    Args:
        state: the board both sides chose against, before either action lands.
        mine: which side ``ours`` belongs to.
        theirs: the opponent's action, or ``None`` when they have not revealed
            one — a turn we advance alone rather than guess at.
        yours: the opponent's side; derived from ``mine`` when omitted.

    Raises:
        IllegalMoveError, IllegalActionError: if either action is illegal on
            the pre-turn board. Illegal *there* is genuinely illegal — it is
            only illegality created by the other side's simultaneous action
            that this function refuses to invent.
    """
    ours_applied = apply_action(state, mine, ours, axes)
    if theirs is None:
        return ours_applied
    them: Agent = yours or ("cop" if mine == "thief" else "thief")
    theirs_applied = apply_action(state, them, theirs, axes)
    merged = replace(ours_applied, barriers=ours_applied.barriers | theirs_applied.barriers)
    where = position_of(theirs_applied, them)
    return replace(merged, cop=where) if them == "cop" else replace(merged, thief=where)
