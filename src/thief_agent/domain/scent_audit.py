"""Checking a scent field that arrived from someone who wants us wrong.

Chapter 4 rests its whole belief layer on one sentence: *the scent map cannot
lie*. That is true of a field an agent computes for itself and false of a field
that arrives as JSON from an opponent. Between the two sits this module.

Three separate questions are asked of every field, and each catches something
the others cannot:

**Is it well formed?** :func:`check_field` refuses a cell off the board, a key
that is not ``row,col``, a value that is not a finite non-negative number, a
value brighter than a fresh emission at its own centre, a value carrying more
precision than the wire transmits, and a field with more cells than the board
has. Every one of these is a value a consumer downstream would otherwise index,
sum, or renormalise against.

**Was it fixed before the turn?** That is :mod:`..domain.crypto`'s job — the
field is sealed into the phase-1 commitment — and it proves only that the
opponent chose the field early. It does not prove the field is *true*.

**Could the physics have produced it?** That is what this module exists for.
Given the agreed start, the agreed axes and the movement history both sides
revealed, the opponent's trail is **re-derived from scratch** — emission on
every action, decay once per full turn — and compared with every field they
disclosed. A field that is well formed, correctly hashed and impossible is
caught here and nowhere else.

Without the third check the cryptography is decorative. An opponent could
commit to a trail centred anywhere it liked, open every commitment honestly,
and walk away with a clean audit while having lied about the one witness the
rulebook calls unfalsifiable. The invariant the project wants is *a hint may
lie, the scent may not*, and it holds only because the trail is recomputed
rather than believed.

**A reconstruction that cannot proceed is itself a failure.** If a revealed
move is illegal on the agreed board, the two peers no longer share a board and
nothing after that point can be checked — so the audit stops and says so at
the step it stopped, rather than continuing against a state only one side has.
"""

import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .actions import Action, apply_action
from .axes import AxisConvention
from .board import Agent, BoardState, Position
from .rules import advance_turn, position_of
from .scent import CENTRE_INTENSITY, DEFAULT_FALLOFF, GRID_SIZE, PRECISION, Falloff, emission
from .trail import Trail

CELL = re.compile(r"^(0|[1-9][0-9]*),(0|[1-9][0-9]*)$")
"""A wire cell key, exactly as :meth:`~.trail.Trail.snapshot` renders one.

Deliberately narrower than ``int()`` would accept. ``" 1,2"``, ``"+1,2"`` and
``"01,2"`` all parse as integers and none of them is a key we would ever emit,
so accepting them would mean two peers whose fields compare unequal while both
believe they agree — the failure the pre-series lock exists to prevent.
"""


class ScentFieldError(ValueError):
    """Raised when a scent field cannot be trusted, or cannot be re-derived.

    A ``ValueError`` rather than anything more dramatic because the caller's
    job is to turn it into a recorded audit failure. An exception escaping an
    audit would be a crash mid-match, which is a technical loss scoring zero
    for both sides — the opponent's malformed field must cost *them* the
    verdict, not both of us the game.
    """


@dataclass(frozen=True, slots=True)
class StepPlay:
    """One step as the audit sees it: both actions, and what they disclosed.

    Frozen because it is evidence. The audit's whole claim is that these are
    the values that crossed the wire, and a record the auditor could edit
    proves nothing about the peer who sent it.
    """

    step: int
    ours: Action
    theirs: Action | None
    disclosed: dict[str, float] | None


def check_field(wire: dict[str, float], board_size: int) -> dict[Position, float]:
    """Parse a received field, refusing anything we would not want to read.

    Returns the field keyed by cell, so a caller that gets a value back has one
    it may use. Nothing is dropped silently: an opponent that sends one bad
    cell has sent a bad field, and quietly keeping the rest would let them
    steer our belief with the half we accepted.

    Raises:
        ScentFieldError: on any structural or physical impossibility.
    """
    if not isinstance(wire, dict):
        raise ScentFieldError(f"scent field must be an object, got {type(wire).__name__}")
    if len(wire) > board_size * board_size:
        raise ScentFieldError(
            f"scent field has {len(wire)} cells, more than the {board_size * board_size} "
            f"a {board_size}x{board_size} board contains"
        )
    field: dict[Position, float] = {}
    for key, value in wire.items():
        if not isinstance(key, str) or not CELL.match(key):
            raise ScentFieldError(f"cell key {key!r} is not 'row,col'")
        row, _, col = key.partition(",")
        cell = (int(row), int(col))
        if not (0 <= cell[0] < board_size and 0 <= cell[1] < board_size):
            raise ScentFieldError(f"cell {key!r} is off a {board_size}x{board_size} board")
        field[cell] = _intensity(key, value)
    return field


def _intensity(key: str, value: object) -> float:
    """One cell's value, checked against the model both peers hash-locked.

    Booleans are refused explicitly: ``isinstance(True, int)`` is true in
    Python, so ``{"1,1": true}`` would otherwise be absorbed as an intensity of
    one — brighter than any emission the model can produce.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScentFieldError(f"intensity at {key!r} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ScentFieldError(f"intensity at {key!r} must be finite, got {number!r}")
    if number < 0.0:
        raise ScentFieldError(
            f"intensity at {key!r} is negative ({number!r}); the rulebook clamps at zero, "
            "because there is no such thing as evidence the opponent was *not* somewhere"
        )
    if number > CENTRE_INTENSITY:
        raise ScentFieldError(
            f"intensity at {key!r} is {number!r}, above the Appendix F centre intensity "
            f"of {CENTRE_INTENSITY}; no cell can be fresher than a fresh emission"
        )
    if number != round(number, PRECISION):
        raise ScentFieldError(
            f"intensity at {key!r} carries more precision than the wire transmits: "
            f"{number!r} is not {PRECISION} decimals"
        )
    return number


def _agent(role: str) -> Agent:
    return "cop" if role == "police" else "thief"


def _walk(
    start: BoardState, axes: AxisConvention, role: str, plays: Sequence[StepPlay]
) -> Iterator[tuple[StepPlay, Position, Position]]:
    """Replay the match, yielding where each side stood after its own action.

    The order mirrors :class:`~..runtime.subgame.SubGame` exactly — turn
    counter, our action, then theirs — because a reconstruction that advanced
    the board differently from the loop that played it would report an honest
    peer as a forger.

    Raises:
        ScentFieldError: naming the step at which the revealed history stopped
            being playable. Every later step is unauditable rather than clean.
    """
    mine, yours = _agent(role), _agent("thief" if role == "police" else "police")
    state = start
    for play in plays:
        try:
            state = advance_turn(state)
            state = apply_action(state, mine, play.ours, axes)
            here = position_of(state, mine)
            if play.theirs is not None:
                state = apply_action(state, yours, play.theirs, axes)
        except ValueError as exc:
            raise ScentFieldError(
                f"step {play.step}: the revealed move cannot be replayed on the agreed "
                f"board ({exc}); from here the two peers no longer share a board"
            ) from exc
        yield play, here, position_of(state, yours)


def replay(
    start: BoardState, axes: AxisConvention, role: str, plays: Sequence[StepPlay]
) -> list[tuple[Position, Position]]:
    """Where both sides stood after acting, one entry per step.

    Raises:
        ScentFieldError: if the revealed history is not playable.
    """
    return [(here, there) for _, here, there in _walk(start, axes, role, plays)]


def trail_snapshots(
    cells: Sequence[Position],
    board_size: int,
    intensity: float = CENTRE_INTENSITY,
    grid_size: int = GRID_SIZE,
    falloff: Falloff = DEFAULT_FALLOFF,
) -> list[dict[str, float]]:
    """The wire field an agent standing on each of ``cells`` in turn would show.

    Emission happens on **every** action, standing still included — the
    rulebook's field is laid down by occupying a cell, not by leaving one — and
    decay fires **once per full turn**, after the snapshot for that turn has
    been taken. Snapshotting before decaying is what makes the field an agent
    transmits at step *t* the field it actually laid at step *t*.
    """
    trail = Trail()
    snapshots = []
    for cell in cells:
        trail.deposit(emission(cell, board_size, intensity, grid_size, falloff))
        snapshots.append(trail.snapshot())
        trail.decay()
    return snapshots


def audit_scent(
    start: BoardState,
    axes: AxisConvention,
    role: str,
    plays: Sequence[StepPlay],
    *,
    require_bound: bool = True,
    falloff: Falloff = DEFAULT_FALLOFF,
) -> tuple[str, ...]:
    """Re-derive the opponent's trail and say where it disagrees with theirs.

    ``role`` is **ours**; the field audited is the opponent's, because a peer
    reading its own trail would be reading information the rules never granted
    it.

    ``require_bound`` is the fail-closed switch. A peer that discloses no field
    has given us nothing that can be checked, and unverifiable scent is not
    weaker evidence than verified scent — it is *no* evidence with the
    appearance of some. The only honest ways to play are with a bound field or
    with none at all agreed in advance, so the downgrade exists, is named, and
    is never the default.

    Every step is reported rather than stopping at the first disagreement: the
    opponent is entitled to the whole list, and a dispute settled on one step
    tends to be reopened on the next.
    """
    failures: list[str] = []
    trail = Trail()
    try:
        for play, _, theirs in _walk(start, axes, role, plays):
            trail.deposit(emission(theirs, start.grid_size, falloff=falloff))
            expected = trail.snapshot()
            trail.decay()
            failures.extend(_disagreements(play, expected, start.grid_size, require_bound))
    except ScentFieldError as exc:
        failures.append(str(exc))
    return tuple(failures)


def _disagreements(
    play: StepPlay, expected: dict[str, float], board_size: int, require_bound: bool
) -> list[str]:
    """What is wrong with one step's disclosed field, if anything."""
    if play.disclosed is None:
        if not require_bound:
            return []
        return [
            f"step {play.step}: no scent field was disclosed, so nothing they emitted can "
            "be checked; unverifiable scent is refused rather than believed"
        ]
    try:
        check_field(play.disclosed, board_size)
    except ScentFieldError as exc:
        return [f"step {play.step}: {exc}"]
    if play.disclosed != expected:
        return [
            f"step {play.step}: the disclosed scent field is not the one their own revealed "
            f"moves produce ({_where(play.disclosed)} against {_where(expected)}); a hint may "
            "lie, a trail may not"
        ]
    return []


def _where(field: dict[str, float]) -> str:
    """The peak of a field, for an accusation the other side can check."""
    if not field:
        return "an empty field"
    cell = min(field, key=lambda key: (-field[key], key))
    return f"peak {field[cell]} at {cell}"
