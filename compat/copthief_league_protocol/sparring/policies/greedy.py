"""Greedy chase and greedy evade, over the observed scent field.

Public-knowledge strategy, and shallow on purpose. Both brains read only what the wire gives them
— the rival's transmitted pheromone trail — because there is nothing else to read: the rival's
position is not in the observation (see ``base.Observation``).

Every tie is broken lexicographically rather than randomly, so a seeded run reproduces exactly.
That is what makes the golden self-play test in CI able to detect behavioural drift at all.
"""

from __future__ import annotations

import random

from sparring.policies.base import Action, Observation
from sparring.rules.board import Board, manhattan
from sparring.rules.scent import hottest


def _sweep(obs: Observation) -> tuple[int, int]:
    """Where to head before any scent has been seen.

    A fixed lawnmower target derived from the step number: with no observation at all, moving
    with a plan beats standing still, and a *deterministic* plan keeps the run reproducible.
    """
    n = obs.board_size
    row = (obs.step // n) % n
    col = obs.step % n
    return (row, col if row % 2 == 0 else n - 1 - col)


def _best_move(obs: Observation, score) -> str:
    """Pick the legal move scoring highest, ties broken by the move's own name."""
    board = Board(obs.board_size)
    ranked = sorted(obs.legal_moves, key=lambda m: (-score(board.step(obs.self_pos, m)), m))
    return ranked[0]


class GreedyChase:
    """Cop: walk down the thief's scent gradient; wall it if it is standing next door."""

    name = "greedy"

    def decide(self, obs: Observation, rng: random.Random) -> Action:
        target = hottest(obs.rival_scent) or _sweep(obs)

        # If the freshest trace is orthogonally adjacent and we still have barriers, spend the
        # turn walling it. Under hidden positions this is a gamble, not a kill: if the thief is
        # actually there, rule 46 makes it a capture, and the thief must say so.
        if obs.barriers_left > 0 and target in obs.barrier_targets and target != obs.self_pos:
            if manhattan(obs.self_pos, target) == 1:
                return Action("STAY", target)

        return Action(_best_move(obs, lambda cell: -manhattan(cell, target)))


class GreedyEvade:
    """Thief: maximise distance from the cop's trace, while keeping room to move."""

    name = "greedy"

    #: Weight on "how many ways out does this cell have". Without it the thief happily reverses
    #: into a corner and loses to rule 47 — captured for having no legal move, without the cop
    #: ever finding it. A round, documented number; nothing was fitted.
    exit_bonus = 0.5

    def decide(self, obs: Observation, rng: random.Random) -> Action:
        threat = hottest(obs.rival_scent)
        board = Board(obs.board_size)
        blocked = set(obs.barriers)

        def score(cell: tuple[int, int]) -> float:
            exits = sum(1 for n in board.neighbours(cell) if n not in blocked)
            away = manhattan(cell, threat) if threat else 0
            return away + self.exit_bonus * exits

        return Action(_best_move(obs, score))
