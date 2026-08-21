"""Configuration, the App. F binding table, and the one run mode this package has.

**There is no ``counted`` mode and no ``rehearsal`` mode here**, and that is the design. Sparring
is the one legitimate "rules armed, no report owed" state; a mode whose preflight demanded a
deliverable report would make the server refuse itself at startup, so the modes that would demand
one simply do not exist. What cannot be selected cannot be selected by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from sparring import DEFAULT_GROUP_ID
from sparring.deadlines import Budgets
from sparring.rules.scent import REFERENCE_MODEL


class RunMode(str, Enum):
    """The only value that exists. See the module docstring."""

    SPARRING = "sparring"


#: App. F. `fixed` values may not move at all — deviation disqualifies the team. `minimum` values
#: may be raised by mutual agreement but never lowered. Absent explicit agreement the example
#: value is the default the code must use.
BINDING: dict[str, tuple[str, object]] = {
    "board_size": ("minimum", 7),
    "num_agents": ("fixed", 2),
    "axis_origin_corner": ("negotiable", "top-left"),
    "axis_start_index": ("negotiable", 0),
    "thief_start": ("negotiable", [3, 3]),
    "cop_start": ("negotiable", [0, 0]),
    "barriers_max": ("minimum", 14),
    "max_steps": ("minimum", 35),
    "survival_threshold": ("minimum", 35),
    "emit_intensity": ("fixed", 0.9),
    "decay_per_step": ("fixed", 0.1),
    "smell_grid_size": ("fixed", 5),
    "hint_max_words": ("negotiable", 15),
    "num_games": ("fixed", 6),
}

#: The 14 keys of the signed terms — flat, and closed. A pair cannot record a choice by adding a
#: key here without breaking the signature, which is the entire reason SPEC section 7's
#: locked-model declarations exist.
TERMS_KEYS = ("board_size", "smell_grid_size", "decay_per_step", "emit_intensity",
              "min_center_intensity", "max_steps", "barriers_max", "setting", "hint_max_words",
              "axis_origin_corner", "axis_start_index", "thief_start", "cop_start", "num_games")


@dataclass
class SparConfig:
    """Everything a sparring peer needs. Deliberately small, and deliberately mail-free."""

    mode: RunMode = RunMode.SPARRING
    group_id: str = DEFAULT_GROUP_ID
    group_name: str = "Sparring Peer (uncounted)"
    opponent_group: str | None = None

    board_size: int = 7
    smell_grid_size: int = 5
    decay_per_step: float = 0.1
    emit_intensity: float = 0.9
    min_center_intensity: float = 0.5
    max_steps: int = 35
    survival_threshold: int = 35
    barriers_max: int = 14
    setting: str = "Haifa"
    hint_max_words: int = 15
    axis_origin_corner: str = "top-left"
    axis_start_index: int = 0
    thief_start: tuple[int, int] = (3, 3)
    cop_start: tuple[int, int] = (0, 0)
    num_games: int = 6

    scent_model: str = REFERENCE_MODEL
    info_mode: str = "belief"
    policy: str = "greedy"
    natural_role: str = "police"
    seed: int = 1234
    lie_rate: float = 0.25
    hint_lang: str = "mixed"
    budgets: Budgets = field(default_factory=Budgets)

    def terms(self) -> dict:
        """The flat signed set, in the shape the kit's ``terms_signature`` vector pins."""
        return {
            "board_size": self.board_size,
            "smell_grid_size": self.smell_grid_size,
            "decay_per_step": self.decay_per_step,
            "emit_intensity": self.emit_intensity,
            "min_center_intensity": self.min_center_intensity,
            "max_steps": self.max_steps,
            "barriers_max": self.barriers_max,
            "setting": self.setting,
            "hint_max_words": self.hint_max_words,
            "axis_origin_corner": self.axis_origin_corner,
            "axis_start_index": self.axis_start_index,
            "thief_start": list(self.thief_start),
            "cop_start": list(self.cop_start),
            "num_games": self.num_games,
        }
