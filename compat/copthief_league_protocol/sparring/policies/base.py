"""What a brain is allowed to see, and what it may answer.

The observation has **no rival-position field, at all**. That is the point: SPEC section 7
registers ``info_mode: belief`` and notes that under ``wire_shape: reference-v3`` the mode is
enforced *structurally* — the rival's position never crosses the wire — whereas under a shape
that does put it on the wire, the same words are only an honour term. Here the guarantee is the
structural kind, and it is visible in this dataclass: there is nothing for a brain to cheat with.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Observation:
    """Everything a brain is entitled to know at decision time."""

    role: str
    step: int
    self_pos: tuple[int, int]
    board_size: int
    barriers: tuple[tuple[int, int], ...]
    legal_moves: tuple[str, ...]
    barrier_targets: tuple[tuple[int, int], ...]
    barriers_left: int
    steps_left: int
    rival_scent: dict[str, float] = field(default_factory=dict)
    last_hint: str | None = None
    # Deliberately absent: rival_position. See the module docstring.


@dataclass(frozen=True)
class Action:
    """A move, optionally with a barrier placed in the same (movement-forgoing) turn."""

    move: str
    barrier: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.barrier is not None and self.move != "STAY":
            raise ValueError("a barrier is placed only in a turn where the cop forgoes movement "
                             "(book ch.3) — pair it with STAY or not at all")


class Policy(Protocol):
    """Deterministic given its RNG, which is what makes seeded self-play reproducible."""

    name: str

    def decide(self, obs: Observation, rng: random.Random) -> Action:
        ...
