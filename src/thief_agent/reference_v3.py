"""Run the vendored cohort reference-v3 peer with this agent's search brains."""

from __future__ import annotations

import random
import sys
from pathlib import Path

_COMPAT_ROOT = Path(__file__).resolve().parents[2] / "compat" / "copthief_league_protocol"
if str(_COMPAT_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPAT_ROOT))

from sparring.policies import REGISTRY  # noqa: E402
from sparring.policies.base import Action, Observation  # noqa: E402

from .domain.actions import MoveAction, PlaceBarrier  # noqa: E402
from .domain.board import BoardState  # noqa: E402
from .reference_v3_commits import install as _install_commit_exchange  # noqa: E402
from .reference_v3_series_consensus import install as _install_series_consensus  # noqa: E402
from .strategy.police_search import SearchingPolice  # noqa: E402
from .strategy.thief_search import SearchingThief  # noqa: E402

__all__ = ["Observation", "PoliceSearchPolicy", "ThiefSearchPolicy", "main"]


def _rival_estimate(obs: Observation) -> tuple[int, int]:
    if obs.rival_scent:
        cell = max(obs.rival_scent, key=obs.rival_scent.__getitem__)
        row, col = cell.split(",", 1)
        return int(row), int(col)
    return (3, 3) if obs.role == "police" else (0, 0)


def _wire_move(move: str) -> str:
    return move if move == "STAY" else f"MOVE:{move}"


def _fallback(obs: Observation, rival: tuple[int, int]) -> Action:
    """Choose a purposeful legal move if the full search cannot be translated."""
    offsets = {
        "MOVE:N": (-1, 0),
        "MOVE:S": (1, 0),
        "MOVE:W": (0, -1),
        "MOVE:E": (0, 1),
        "STAY": (0, 0),
    }
    ranked = []
    for index, move in enumerate(obs.legal_moves):
        dr, dc = offsets.get(move, (0, 0))
        landed = obs.self_pos[0] + dr, obs.self_pos[1] + dc
        distance = abs(landed[0] - rival[0]) + abs(landed[1] - rival[1])
        value = -distance if obs.role == "police" else distance
        ranked.append((value, -index, move))
    return Action(max(ranked)[2] if ranked else "STAY")


class SearchPolicy:
    """Translate the kit observation into the existing hidden-state brain API."""

    name = "s82kma9e-search"

    def __init__(self, role: str) -> None:
        self.role = role
        self.brain = SearchingPolice() if role == "police" else SearchingThief()

    def decide(self, obs: Observation, rng: random.Random) -> Action:
        rival = _rival_estimate(obs)
        if self.role == "police":
            self.brain.max_barriers = len(obs.barriers) + obs.barriers_left
        state = BoardState(
            grid_size=obs.board_size,
            cop=obs.self_pos if self.role == "police" else rival,
            thief=rival if self.role == "police" else obs.self_pos,
            barriers=frozenset(obs.barriers),
            step=obs.step,
        )
        belief = {rival: 1.0}
        try:
            chosen = self.brain.decide(
                state,
                belief=belief,
                threat=rival,
                concentration=1.0,
                uncertainty=0.0,
                rng=rng,
            ).action
            if isinstance(chosen, PlaceBarrier) and chosen.at in obs.barrier_targets:
                return Action("STAY", chosen.at)
            if isinstance(chosen, MoveAction):
                move = _wire_move(chosen.move)
                if move in obs.legal_moves:
                    return Action(move)
        except (RuntimeError, ValueError):
            pass
        return _fallback(obs, rival)


class PoliceSearchPolicy(SearchPolicy):
    def __init__(self) -> None:
        super().__init__("police")


class ThiefSearchPolicy(SearchPolicy):
    def __init__(self) -> None:
        super().__init__("thief")


REGISTRY["search"] = {"police": PoliceSearchPolicy, "thief": ThiefSearchPolicy}
_install_commit_exchange()
_install_series_consensus()


def main() -> int:
    from sparring.cli import main as reference_main

    return int(reference_main())


if __name__ == "__main__":
    raise SystemExit(main())
