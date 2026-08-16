"""Uniform random over legal actions — the honest floor.

Worth having as more than a placeholder: a random opponent exercises your protocol across a much
wider spread of game states than a purposeful one, and protocol bugs are what a practice peer is
for. It will also occasionally trap a careless thief by accident, which is a real reminder that
rule 47 exists.
"""

from __future__ import annotations

import random

from sparring.policies.base import Action, Observation


class RandomWalk:
    name = "random"

    #: How often the cop spends a turn walling instead of moving. A round number, documented as
    #: illustrative rather than tuned — there is no experiment behind it and there must not be.
    barrier_probability = 0.15

    def decide(self, obs: Observation, rng: random.Random) -> Action:
        if (obs.role == "police" and obs.barrier_targets and obs.barriers_left > 0
                and rng.random() < self.barrier_probability):
            target = rng.choice(sorted(obs.barrier_targets))
            # Never wall ourselves in: a cop with no legal move cannot chase anything, and
            # unlike the thief it does not lose for it — it just stops playing.
            if target != obs.self_pos or len(obs.legal_moves) > 1:
                return Action("STAY", target)
        return Action(rng.choice(sorted(obs.legal_moves)))
