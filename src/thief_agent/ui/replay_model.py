"""The shape a recorded step has, and the cursor a reader moves over them.

Split out of :mod:`.replay` to keep each module inside the line budget. This
half is the vocabulary: what a step looked like when the log was written, and
how a reader walks the sequence. It knows nothing about files and nothing about
hashes — reading is :func:`.replay.load`'s job and re-derivation is
:func:`.replay_check.check_step`'s, and keeping the three apart is what lets a
broken file, an unopenable step and a forged one stay three different answers.
"""

from dataclasses import dataclass, field
from typing import Any


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
