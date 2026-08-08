"""Loading a recorded sub-game and walking it, step by step.

The Replay App reads ``log_<game_id>_g<NN>.json`` — the append-only file from
:mod:`..infra.match_log` — and lets a reader move through it in both
directions. It is the artefact the examiner opens, and the thing that carries
the ``Verified OK`` stamp the final checklist asks for.

**Loading is where a log stops being trusted.** The file on disk is the one
place the record leaves our process, so anything could have happened to it in
between: a hand edit, a truncated write, a step deleted. Everything that
follows — the per-step digest recomputation, the verdict — is only meaningful
if the loader refuses a file it cannot vouch for the *shape* of. A replay that
silently skipped a malformed step would stamp ``Verified OK`` on a log with a
hole in it.

So the loader is strict about structure and says nothing about honesty. Those
are separate questions and separating them is what lets the verdict mean
something: a file that will not load is a broken file, and a file that loads
and fails verification is a tampered one. Collapsing the two would report
somebody's disk error as somebody's fraud.

Navigation is deliberately dumb. ``forward`` and ``back`` clamp at the ends
rather than wrapping or raising, because a reader holding a key down at the
last step wants to stay there, not to be thrown to the beginning or shown a
traceback.
"""

import json
from pathlib import Path

from ..infra.match_log import SLOTS
from .replay_check import StepCheck, check_step
from .replay_model import RecordedStep, Replay, ReplayError

__all__ = ["RecordedStep", "Replay", "ReplayError", "StepCheck", "check_step", "load"]


def load(path: Path) -> Replay:
    """Read a match log, refusing anything that is not one.

    Raises:
        ReplayError: on unreadable JSON, a missing field, a step out of order
            or a duplicate. Structure only — whether the log is *honest* is a
            different question, asked later, and answering both here would
            report a disk error as fraud.
    """
    try:
        body = json.loads(path.read_text())
    except OSError as exc:
        raise ReplayError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReplayError(f"{path.name} is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ReplayError(f"{path.name} is not a match log object")

    rows = body.get("steps")
    if not isinstance(rows, list):
        raise ReplayError(f"{path.name} has no 'steps' list")

    steps: list[RecordedStep] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ReplayError(f"step {index} is not an object")
        missing = [name for name in ("step", *SLOTS) if name not in row]
        if missing:
            raise ReplayError(f"step {index} is missing {missing}")
        if not isinstance(row["step"], int) or isinstance(row["step"], bool):
            raise ReplayError(f"step {index} has a non-integer step number")
        if not isinstance(row["commit"], str):
            raise ReplayError(f"step {row['step']} has no commitment")
        steps.append(
            RecordedStep(
                step=row["step"],
                commit=row["commit"],
                reveal=row["reveal"] if isinstance(row["reveal"], dict) else None,
                nonce=row["nonce"] if isinstance(row["nonce"], str) else None,
            )
        )

    numbers = [recorded.step for recorded in steps]
    if len(set(numbers)) != len(numbers):
        raise ReplayError(f"{path.name} repeats a step number: {numbers}")
    if numbers != sorted(numbers):
        raise ReplayError(f"{path.name} records steps out of order: {numbers}")

    return Replay(
        game_id=str(body.get("game_id", "")),
        sub_game=int(body.get("sub_game", 0)),
        role=str(body.get("role", "")),
        steps=tuple(steps),
    )
