"""Public-knowledge brains. Nothing tuned, ever — and that is checked, not promised.

``guards/purity.py`` holds this package to a tiny import surface: no file reads, no weights-file
extensions, nothing outside ``random`` / ``math`` / ``dataclasses`` / ``typing`` / ``enum`` /
``collections`` and the rules modules. A brain that cannot open a file cannot load a trained
model, so "no tuned weights" is a property of the source rather than a claim about our intentions.

Why it matters for a peer other people run: a practice opponent answering with a tuned brain would
hand a future counted opponent a free sample of the exact thing being graded.
"""

from sparring.policies.base import Action, Observation, Policy
from sparring.policies.greedy import GreedyChase, GreedyEvade
from sparring.policies.random_walk import RandomWalk

#: Everything on offer. Named, public, and boring by design.
REGISTRY = {
    "random": {"police": RandomWalk, "thief": RandomWalk},
    "greedy": {"police": GreedyChase, "thief": GreedyEvade},
}

__all__ = ["Action", "Observation", "Policy", "GreedyChase", "GreedyEvade", "RandomWalk",
           "REGISTRY"]
