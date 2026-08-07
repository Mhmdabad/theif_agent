"""Tests for replay determinism (#41).

The acceptance criterion is *across processes and runs*, and the two are not
the same claim. Within one process a policy can be perfectly reproducible and
still differ from the peer replaying it, because Python randomises string and
tuple hashing per process: anything that reads a ``set`` or ``dict`` in
iteration order is stable for a run and unstable for a match.

So the cross-process half is tested by actually starting other processes with
different ``PYTHONHASHSEED`` values, rather than asserted in a docstring.
"""

import logging
import os
import subprocess
import sys
from dataclasses import replace

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.strategy.thief_brain import ThiefBrain

AXES = AxisConvention()

DECIDE = """
import json, sys
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.strategy.thief_brain import ThiefBrain

axes = AxisConvention()
brain = ThiefBrain(axes=axes, seed=7)
walls = frozenset({(1, 1), (2, 2), (3, 1), (0, 4), (4, 4), (5, 2)})
moves = []
for step in range(6):
    state = BoardState(
        cop=(min(6, step), 0), thief=(3, 3), grid_size=7, barriers=walls, step=step
    )
    moves.append(brain.decide(state).action.move)
print(json.dumps(moves))
"""


def run_with_hash_seed(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run(
        [sys.executable, "-c", DECIDE], env=env, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make(**kw: object) -> BoardState:
    cop = kw.get("cop", (0, 0))
    thief = kw.get("thief", (3, 3))
    barriers = kw.get("barriers", frozenset())
    step = kw.get("step", 0)
    assert isinstance(cop, tuple) and isinstance(thief, tuple)
    assert isinstance(barriers, frozenset | set) and isinstance(step, int)
    return BoardState(cop=cop, thief=thief, grid_size=7, barriers=frozenset(barriers), step=step)


class TestAcrossProcesses:
    def test_hash_randomisation_does_not_change_the_moves(self) -> None:
        """#41's acceptance criterion, tested rather than asserted.

        Four processes, four different hash seeds. If any decision read a set
        or dict in iteration order, these would disagree — and they would
        disagree only between peers, never within our own test run, which is
        the failure that survives to a match and is blamed on the network.
        """
        results = {run_with_hash_seed(seed) for seed in ("0", "1", "42", "12345")}
        assert len(results) == 1, f"hash seed changed the decisions: {results}"

    def test_the_subprocess_actually_decided_something(self) -> None:
        """Guards against a sweep that agrees because it produced nothing."""
        assert len(run_with_hash_seed("0").strip("[]").split(",")) == 6


class TestAcrossRuns:
    def test_a_whole_match_replays_identically(self) -> None:
        """One turn agreeing is not the claim.

        The brain carries a tracker, so a divergence can appear only after
        several turns of accumulated history. Both runs feed the same eight
        states to a brain that keeps its memory, which is how a peer replaying
        the match would do it.
        """
        walls = frozenset({(1, 1), (2, 2), (3, 1)})
        states = [
            make(cop=(min(6, step), 0), thief=(3, 3), barriers=walls, step=step)
            for step in range(8)
        ]
        played = ThiefBrain(axes=AXES, seed=3)
        first = [played.decide(state).action for state in states]

        replayed = ThiefBrain(axes=AXES, seed=3)
        second = [replayed.decide(state).action for state in states]

        assert len(first) == 8
        assert first == second
        assert replayed.reach.history == played.reach.history

    def test_replaying_without_the_history_is_a_different_run(self) -> None:
        """Why the test above feeds one brain rather than eight.

        A fresh brain per turn has no trend to read, so it is not replaying
        the match — it is playing eight unrelated first turns. Stating this
        keeps the replay test from being weakened later into the easy version
        that would pass without the tracker existing.
        """
        walls = frozenset({(6, 0), (6, 1), (6, 2)})
        states = [make(cop=(5, 5), thief=(1, 1), step=0)] + [
            make(cop=(5, 5), thief=(1, 1), barriers=walls, step=step) for step in (1, 2)
        ]
        continuous = ThiefBrain(axes=AXES, seed=3)
        with_memory = [continuous.decide(state, threat=state.cop).action for state in states]
        without = [
            ThiefBrain(axes=AXES, seed=3).decide(state, threat=state.cop).action for state in states
        ]
        assert with_memory != without

    def test_the_tracker_makes_history_part_of_the_decision(self) -> None:
        """Not a determinism failure — a reason determinism has to be tested
        over a sequence rather than a single call."""
        walls = frozenset({(6, 0), (6, 1), (6, 2)})
        closing = make(cop=(5, 5), thief=(1, 1), barriers=walls, step=1)

        cold = ThiefBrain(axes=AXES, seed=3)
        assert not cold.reach.closing

        warm = ThiefBrain(axes=AXES, seed=3)
        warm.reach.observe(make(step=0), AXES)
        warm.reach.observe(closing, AXES)
        assert warm.reach.closing

        assert cold._rank(closing, "S", closing.cop) != warm._rank(closing, "S", closing.cop)

    def test_two_brains_fed_the_same_history_agree(self) -> None:
        walls = frozenset({(6, 0), (6, 1), (6, 2)})
        history = [make(step=0), make(barriers=walls, step=1)]
        one, two = ThiefBrain(axes=AXES, seed=5), ThiefBrain(axes=AXES, seed=5)
        for state in history:
            assert one.decide(state).action == two.decide(state).action


class TestTheSeedIsRecoverable:
    def test_it_is_on_every_turn_not_once_at_startup(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A transcript is what a bug report is rebuilt from, and a seed in a
        line that was rotated away is a seed the reproduction does not have."""
        with caplog.at_level(logging.INFO, logger="thief_agent.strategy.thief_brain"):
            brain = ThiefBrain(axes=AXES, seed=4242)
            brain.decide(make(step=0))
            brain.decide(make(step=1))
        assert caplog.text.count("seed=4242") == 2

    def test_it_survives_on_the_object(self) -> None:
        assert ThiefBrain(axes=AXES, seed=99).seed == 99

    def test_the_default_is_recorded_too(self, caplog: pytest.LogCaptureFixture) -> None:
        """Zero is a seed. An unlogged default is the one nobody can reproduce."""
        with caplog.at_level(logging.INFO, logger="thief_agent.strategy.thief_brain"):
            ThiefBrain(axes=AXES).decide(make())
        assert "seed=0" in caplog.text


class TestNoHiddenRandomness:
    def test_the_policy_does_not_draw_from_the_rng_at_all(self) -> None:
        """Ties break by MOVES order, so the stream should be untouched. If a
        later change starts drawing, this fails and the seed becomes load
        bearing rather than decorative."""
        brain = ThiefBrain(axes=AXES, seed=11)
        before = brain.rng.getstate()
        for step in range(5):
            brain.decide(make(cop=(step, 0), step=step))
        assert brain.rng.getstate() == before

    def test_the_global_rng_is_never_used(self) -> None:
        import random

        random.seed(1)
        first = ThiefBrain(axes=AXES, seed=0).decide(make(cop=(2, 2))).action
        random.seed(999999)
        second = ThiefBrain(axes=AXES, seed=0).decide(make(cop=(2, 2))).action
        assert first == second
        assert isinstance(first, MoveAction)

    def test_config_and_state_alone_determine_the_action(self) -> None:
        """Identical state plus identical config, phrased as #41 phrases it."""
        state = make(cop=(2, 2), thief=(5, 5))
        assert (
            ThiefBrain(axes=AXES, seed=7, min_open_neighbours=3).decide(state).action
            == ThiefBrain(axes=AXES, seed=7, min_open_neighbours=3).decide(state).action
        )

    def test_a_different_config_may_legitimately_differ(self) -> None:
        """The claim is state+config, not state alone."""
        state = replace(make(cop=(0, 0), thief=(6, 6)))
        strict = ThiefBrain(axes=AXES, seed=7, min_open_neighbours=3).decide(state).action
        blind = ThiefBrain(axes=AXES, seed=7, min_open_neighbours=0).decide(state).action
        assert strict != blind
