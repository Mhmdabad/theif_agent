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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..infra.match_log import SLOTS


class ReplayError(ValueError):
    """Raised when a log cannot be read as a sub-game at all."""


@dataclass(frozen=True, slots=True)
class RecordedStep:
    """One step as the log recorded it."""

    step: int
    commit: str
    reveal: dict[str, Any] | None
    nonce: str | None

    @property
    def openable(self) -> bool:
        """Whether this step carries everything needed to re-derive its digest."""
        return self.reveal is not None and self.nonce is not None


@dataclass
class Replay:
    """A loaded sub-game and a cursor into it."""

    game_id: str
    sub_game: int
    role: str
    steps: tuple[RecordedStep, ...]
    cursor: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.steps:
            raise ReplayError("a sub-game with no steps cannot be replayed")

    @property
    def current(self) -> RecordedStep:
        return self.steps[self.cursor]

    @property
    def at_start(self) -> bool:
        return self.cursor == 0

    @property
    def at_end(self) -> bool:
        return self.cursor == len(self.steps) - 1

    def forward(self) -> RecordedStep:
        """Advance one step, stopping at the last rather than wrapping."""
        self.cursor = min(self.cursor + 1, len(self.steps) - 1)
        return self.current

    def back(self) -> RecordedStep:
        """Retreat one step, stopping at the first."""
        self.cursor = max(self.cursor - 1, 0)
        return self.current

    def seek(self, step: int) -> RecordedStep:
        """Jump to a step by its number.

        Raises:
            ReplayError: if the log has no such step. Named rather than
                clamped, because a reader asking for step 12 of a nine-step
                game has misread something and should be told.
        """
        for index, recorded in enumerate(self.steps):
            if recorded.step == step:
                self.cursor = index
                return self.current
        raise ReplayError(f"step {step} is not in this log; it holds {self.numbers()}")

    def numbers(self) -> list[int]:
        return [recorded.step for recorded in self.steps]


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
