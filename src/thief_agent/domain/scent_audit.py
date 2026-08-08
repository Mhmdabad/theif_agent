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

from collections.abc import Sequence

from .axes import AxisConvention
from .board import BoardState, Position
from .scent import CENTRE_INTENSITY, DEFAULT_FALLOFF, GRID_SIZE, Falloff, emission
from .scent_audit_disagreement import _disagreements
from .scent_audit_replay import StepPlay, _walk, replay
from .scent_audit_wire import CELL, ScentFieldError, check_field
from .trail import Trail

__all__ = [
    "CELL",
    "ScentFieldError",
    "StepPlay",
    "audit_scent",
    "check_field",
    "replay",
    "trail_snapshots",
]
"""Everything this module exported before its parts moved into siblings.

The split is an arrangement of files, not a change to the interface: importers
and the pre-series source offer both name ``domain/scent_audit.py``, so every
public name it answered to stays answerable here.
"""


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
