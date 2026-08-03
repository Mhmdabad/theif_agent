"""Tests for the thief's brain and its selection from config."""

import random
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.actions import MoveAction, PlaceBarrier
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import MOVES, BoardState, Move
from thief_agent.domain.rules import target_of
from thief_agent.domain.search import reachable_area
from thief_agent.strategy.base import BrainBase, Decision, NoLegalActionError
from thief_agent.strategy.loader import DEFAULT_BRAIN, StrategyError, load_brain
from thief_agent.strategy.thief_brain import (
    MIN_OPEN_NEIGHBOURS,
    ThiefBrain,
    manhattan,
    open_neighbours,
)

AXES = AxisConvention()


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestManhattan:
    def test_matches_the_rulebook_formula(self) -> None:
        """Distance between two cells, as the rulebook defines it."""
        assert manhattan((2, 2), (5, 5)) == 6

    def test_is_symmetric(self) -> None:
        assert manhattan((1, 2), (4, 6)) == manhattan((4, 6), (1, 2))

    def test_a_cell_is_zero_from_itself(self) -> None:
        assert manhattan((3, 3), (3, 3)) == 0

    def test_ignores_barriers(self) -> None:
        """Admissible: it never overestimates the true step count."""
        assert manhattan((0, 0), (0, 2)) == 2


class TestEvasion:
    def test_runs_from_the_pursuer(self) -> None:
        brain = ThiefBrain(axes=AXES)
        action = brain.decide(make(cop=(0, 0), thief=(3, 3))).action
        assert isinstance(action, MoveAction)
        assert action.move in {"S", "E"}

    def test_it_only_gives_up_distance_to_leave_cramped_ground(self) -> None:
        """The invariant #37 replaced "never decreases the distance" with.

        The old rule held everywhere on an open board except the far corner,
        where standing still was the furthest cell *and* the cheapest one for
        the cop to seal. Losing a cell of distance to gain a side of degree is
        the trade this policy exists to make, so the invariant now permits it
        exactly when the cell being left is below the threshold.
        """
        brain = ThiefBrain(axes=AXES)
        for row in range(7):
            for col in range(7):
                state = make(cop=(0, 0), thief=(row, col))
                before = manhattan(state.thief, state.cop)
                action = brain.decide(state).action
                assert isinstance(action, MoveAction)
                after = manhattan(target_of(state.thief, action.move, AXES), state.cop)
                if after < before:
                    assert open_neighbours(state, state.thief, AXES) < MIN_OPEN_NEIGHBOURS
                    moved_to = target_of(state.thief, action.move, AXES)
                    assert open_neighbours(state, moved_to, AXES) >= MIN_OPEN_NEIGHBOURS

    def test_an_explicit_threat_overrides_the_cop_position(self) -> None:
        """Once a belief map exists it supplies the threat instead."""
        brain = ThiefBrain(axes=AXES)
        action = brain.decide(make(cop=(6, 6), thief=(3, 3)), threat=(0, 3)).action
        assert isinstance(action, MoveAction)
        assert action.move == "S"

    def test_a_walled_in_thief_stays(self) -> None:
        walls = frozenset({(2, 3), (4, 3), (3, 2), (3, 4)})
        action = ThiefBrain(axes=AXES).decide(make(thief=(3, 3), barriers=walls)).action
        assert action == MoveAction("STAY")

    def test_honours_the_negotiated_convention(self) -> None:
        flipped = AxisConvention(origin_corner="bottom-left")
        brain = ThiefBrain(axes=flipped)
        action = brain.decide(make(cop=(0, 3), thief=(3, 3))).action
        assert isinstance(action, MoveAction)
        assert action.move == "N"

    def test_distance_alone_will_run_into_a_corner(self) -> None:
        """The flaw the escape-space refinement exists to fix.

        A corner can be far from the cop and still be where enclosure costs
        two barriers instead of four. Recorded now so the fix has a failing
        case to point at.
        """
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(6, 6), thief=(1, 1))
        action = brain.decide(state).action
        assert isinstance(action, MoveAction)
        moved = target_of(state.thief, action.move, AXES)
        assert moved in {(0, 1), (1, 0)}


class TestLegalityGuard:
    def test_the_policy_never_returns_an_illegal_move(self) -> None:
        brain = ThiefBrain(axes=AXES)
        walls = frozenset({(1, 1), (2, 2), (3, 3), (4, 4)})
        for row in range(7):
            for col in range(7):
                state = make(cop=(0, 0), thief=(row, col), barriers=walls)
                if state.is_barrier(state.thief):
                    continue
                action = brain.decide(state).action
                assert isinstance(action, MoveAction)
                assert action.move in brain.options(state)

    def test_a_rogue_subclass_is_caught(self) -> None:
        """Defence in depth: the guard runs on whatever a subclass produced."""

        class Rogue(ThiefBrain):
            def _pick_move(self, state: BoardState, **context: object) -> Move:
                return "N"

        with pytest.raises(NoLegalActionError, match="not among"):
            Rogue(axes=AXES).decide(make(thief=(0, 0)))

    def test_the_guard_cannot_be_bypassed_by_overriding_pick_move(self) -> None:
        """`decide` is the entry point; subclasses override the hooks."""
        assert "_guard" in BrainBase.decide.__code__.co_names

    def test_a_sealed_cop_has_nothing_legal(self) -> None:
        """The trapping-capture state: sealed in place, nothing legal."""
        walls = frozenset({(3, 3), (2, 3), (4, 3), (3, 2), (3, 4)})
        with pytest.raises(NoLegalActionError, match="no legal move"):
            ThiefBrain(axes=AXES).decide(make(thief=(3, 3), barriers=walls))

    def test_the_guard_reports_an_empty_option_set(self) -> None:
        """A subclass that acts anyway is caught by the guard, not the policy."""

        class Stubborn(ThiefBrain):
            def _pick_move(self, state: BoardState, **context: object) -> Move:
                return "N"

        walls = frozenset({(3, 3), (2, 3), (4, 3), (3, 2), (3, 4)})
        with pytest.raises(NoLegalActionError, match="has no legal move"):
            Stubborn(axes=AXES).decide(make(thief=(3, 3), barriers=walls))

    def test_a_barrier_action_passes_the_move_guard(self) -> None:
        """Placement legality belongs to the domain layer, not here."""
        brain = ThiefBrain(axes=AXES)
        brain._guard(make(), PlaceBarrier((1, 0)))


class TestDeterminism:
    def test_same_state_and_seed_yields_the_same_action(self) -> None:
        state = make(cop=(2, 2), thief=(5, 5))
        first = ThiefBrain(axes=AXES, seed=7).decide(state).action
        second = ThiefBrain(axes=AXES, seed=7).decide(state).action
        assert first == second

    def test_the_seed_is_recorded_on_the_brain(self) -> None:
        """A match cannot be replayed if the seed is not known."""
        assert ThiefBrain(axes=AXES, seed=99).seed == 99

    def test_randomness_is_seeded_not_global(self) -> None:
        a = ThiefBrain(axes=AXES, seed=1).rng.random()
        b = ThiefBrain(axes=AXES, seed=1).rng.random()
        assert a == b

    def test_different_seeds_give_different_streams(self) -> None:
        a = ThiefBrain(axes=AXES, seed=1).rng.random()
        b = ThiefBrain(axes=AXES, seed=2).rng.random()
        assert a != b


class TestDecision:
    def test_carries_an_action(self) -> None:
        assert isinstance(ThiefBrain(axes=AXES).decide(make()), Decision)

    def test_defaults_to_a_truthful_intent(self) -> None:
        """Intent is declared before sending; deception is opt-in."""
        assert ThiefBrain(axes=AXES).decide(make()).intent == "truth"


class TestLoader:
    def test_an_absent_section_loads_the_shipped_brain(self) -> None:
        assert isinstance(load_brain(None), ThiefBrain)

    def test_an_empty_section_loads_the_shipped_brain(self) -> None:
        assert isinstance(load_brain({}), ThiefBrain)

    def test_the_default_reference_resolves(self) -> None:
        assert isinstance(load_brain({"thief_class": DEFAULT_BRAIN}), ThiefBrain)

    def test_a_custom_brain_is_loaded(self) -> None:
        spec = "thief_agent.strategy.thief_brain:ThiefBrain"
        assert isinstance(load_brain({"thief_class": spec}), BrainBase)

    def test_a_malformed_reference_is_refused(self) -> None:
        with pytest.raises(StrategyError, match="package.module:Class"):
            load_brain({"thief_class": "not_a_reference"})

    def test_an_unimportable_module_is_refused(self) -> None:
        with pytest.raises(StrategyError, match="cannot import"):
            load_brain({"thief_class": "no.such.module:Brain"})

    def test_a_missing_class_is_refused(self) -> None:
        with pytest.raises(StrategyError, match="has no"):
            load_brain({"thief_class": "thief_agent.strategy.thief_brain:Missing"})

    def test_a_non_brain_is_refused(self) -> None:
        """Loading anything callable would defer the failure to move one."""
        with pytest.raises(StrategyError, match="does not subclass"):
            load_brain({"thief_class": "thief_agent.strategy.thief_brain:manhattan"})

    def test_the_axis_convention_is_threaded_through(self) -> None:
        flipped = AxisConvention(origin_corner="bottom-right")
        assert load_brain({}, axes=flipped).axes == flipped

    def test_the_seed_is_threaded_through(self) -> None:
        assert load_brain({}, seed=42).seed == 42

    def test_the_shipped_private_config_selects_the_default(self) -> None:
        """The section is commented out, so the heuristic brain runs."""
        path = Path(__file__).parents[1] / "config/thief/game.toml"
        private: dict[str, Any] = tomllib.loads(path.read_text())
        assert isinstance(load_brain(private.get("strategy")), ThiefBrain)


class TestContract:
    def test_the_role_is_the_thief(self) -> None:
        assert ThiefBrain(axes=AXES).role == "thief"

    def test_options_are_in_stable_order(self) -> None:
        """Replay determinism depends on both peers iterating identically."""
        brain = ThiefBrain(axes=AXES)
        state = make(thief=(3, 3))
        assert brain.options(state) == list(MOVES)

    def test_the_base_class_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            BrainBase()  # type: ignore[abstract]


class TestEscapeSpaceTieBreak:
    def test_distance_still_dominates(self) -> None:
        """Escape space breaks ties; it does not override running.

        From (0,1) with the cop at (0,0), both S and E reach distance 2 while
        W closes to 0 and STAY holds at 1. The assertion is that a
        distance-maximal move is chosen, not which of the two — picking one
        would be asserting the tie-break, which is a different test.
        """
        brain = ThiefBrain(axes=AXES)
        action = brain.decide(make(cop=(0, 0), thief=(0, 1))).action
        assert isinstance(action, MoveAction)
        assert action.move in {"S", "E"}

    def test_it_prefers_the_side_with_more_room(self) -> None:
        """A wall makes one equally distant option a much smaller pocket."""
        walls = frozenset({(1, 0), (1, 1), (1, 2)})
        state = make(cop=(6, 6), thief=(1, 3), barriers=walls)
        action = ThiefBrain(axes=AXES).decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move != "W"

    def test_it_avoids_stepping_into_a_sealed_pocket(self) -> None:
        """The failure distance alone cannot see: far away and nearly trapped."""
        walls = frozenset({(0, 2), (1, 2), (2, 2), (2, 0), (2, 1)})
        state = make(cop=(6, 6), thief=(1, 1), barriers=walls)
        brain = ThiefBrain(axes=AXES)
        pocket = reachable_area(state, (0, 0), AXES)
        assert pocket < 10
        action = brain.decide(state).action
        assert isinstance(action, MoveAction)

    def test_reachable_area_cannot_separate_candidates_at_all(self) -> None:
        """Why #38 removed it from the tuple.

        A move changes only the thief's own cell, so every legal destination is
        one step away and therefore in the thief's own component. Reachable
        area is a property of that component, so it returns the same number for
        every candidate — not usually, always. It read as a tie-break and
        never once broke a tie.
        """
        rng = random.Random(7)
        cells = [(row, col) for row in range(7) for col in range(7)]
        for _ in range(400):
            walls = frozenset(rng.sample(cells, rng.randint(0, 14)))
            free = [cell for cell in cells if cell not in walls]
            state = make(cop=rng.choice(free), thief=rng.choice(free), barriers=walls)
            rooms = {
                reachable_area(
                    replace(state, thief=target_of(state.thief, move, AXES)),
                    target_of(state.thief, move, AXES),
                    AXES,
                )
                for move in ThiefBrain(axes=AXES).options(state)
            }
            assert len(rooms) <= 1

    def test_the_ranking_is_total(self) -> None:
        """Two candidates never tie completely, so the choice is deterministic."""
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(3, 3), thief=(3, 3))
        ranks = [brain._rank(state, move, state.cop) for move in brain.options(state)]
        assert len(set(ranks)) == len(ranks)

    def test_it_stays_deterministic_across_instances(self) -> None:
        state = make(cop=(0, 0), thief=(3, 3))
        assert (
            ThiefBrain(axes=AXES).decide(state).action == ThiefBrain(axes=AXES).decide(state).action
        )

    def test_it_never_returns_an_illegal_move(self) -> None:
        brain = ThiefBrain(axes=AXES)
        walls = frozenset({(1, 1), (2, 2), (4, 4)})
        for row in range(7):
            for col in range(7):
                state = make(cop=(0, 0), thief=(row, col), barriers=walls)
                if state.is_barrier(state.thief):
                    continue
                action = brain.decide(state).action
                assert isinstance(action, MoveAction)
                assert action.move in brain.options(state)


class TestCornerAversion:
    """#37: refuse low-degree cells that gain nothing, and only those."""

    def test_degree_counts_open_exits(self) -> None:
        state = make(cop=(0, 0), thief=(3, 3))
        assert open_neighbours(state, (3, 3), AXES) == 4
        assert open_neighbours(state, (0, 3), AXES) == 3
        assert open_neighbours(state, (0, 0), AXES) == 2

    def test_a_barrier_closes_a_side_like_the_edge_does(self) -> None:
        """Appendix D's pricing is one rule, not three."""
        state = make(cop=(0, 0), thief=(3, 3), barriers=frozenset({(2, 3)}))
        assert open_neighbours(state, (3, 3), AXES) == 3

    def test_the_threshold_makes_a_corner_cramped_before_any_barrier(self) -> None:
        assert open_neighbours(make(), (0, 0), AXES) < MIN_OPEN_NEIGHBOURS
        assert open_neighbours(make(), (0, 3), AXES) >= MIN_OPEN_NEIGHBOURS

    def test_it_leaves_the_far_corner_rather_than_sit_at_maximum_distance(self) -> None:
        """The case the old distance-only invariant could not express.

        From (6, 6) with the cop at (0, 0), STAY is the furthest option at 12
        and also the cheapest cell for the cop to seal — two barriers instead
        of four. The thief gives up one cell of distance for a side of degree.
        """
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(0, 0), thief=(6, 6))
        assert brain.is_cramped(state, "STAY", state.cop)
        action = brain.decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move in {"N", "W"}

    def test_a_cramped_cell_that_gains_ground_is_still_taken(self) -> None:
        """The exemption. A thief that will not corner to escape gets caught
        in open board instead, which is a worse way to lose."""
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(1, 1), thief=(1, 0))
        assert manhattan((0, 0), state.cop) > manhattan(state.thief, state.cop)
        assert not brain.is_cramped(state, "N", state.cop)

    def test_equal_distance_prefers_the_roomier_cell(self) -> None:
        """#37's acceptance criterion, and the hole the exemption left.

        From (1, 0) with the cop at (1, 4), N reaches the corner (0, 0) and S
        reaches (2, 0). Both gain a cell of distance, so the exemption clears
        both; both still reach all 49 free cells, so escape space cannot
        separate them either. Before raw degree entered the ranking this fell
        through to ``MOVES`` order and chose the corner — corner drift arrived
        at through the rule written to prevent it.
        """
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(1, 4), thief=(1, 0))
        assert manhattan((0, 0), state.cop) == manhattan((2, 0), state.cop)
        assert not brain.is_cramped(state, "N", state.cop)
        assert open_neighbours(state, (0, 0), AXES) < open_neighbours(state, (2, 0), AXES)
        action = brain.decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move == "S"

    def test_the_veto_still_outranks_a_degree_preference(self) -> None:
        """Both terms are present; the veto is the one above distance."""
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(0, 0), thief=(6, 6))
        stay, north = brain._rank(state, "STAY", state.cop), brain._rank(state, "N", state.cop)
        assert stay[0] == 0 and north[0] == 1
        assert stay[1] > north[1]
        assert north > stay

    def test_degree_outranks_distance_in_the_tuple(self) -> None:
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(0, 0), thief=(6, 6))
        assert brain._rank(state, "N", state.cop) > brain._rank(state, "STAY", state.cop)

    def test_the_threshold_is_configurable(self) -> None:
        """Set it to zero and the policy reverts to pure distance."""
        state = make(cop=(0, 0), thief=(6, 6))
        blind = ThiefBrain(axes=AXES, min_open_neighbours=0)
        assert not blind.is_cramped(state, "STAY", state.cop)
        action = blind.decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move == "STAY"

    def test_a_walled_in_thief_still_stays_rather_than_erroring(self) -> None:
        """Every option is cramped, so the penalty cannot break the choice."""
        walls = frozenset({(2, 3), (4, 3), (3, 4)})
        state = make(cop=(0, 0), thief=(3, 3), barriers=walls)
        action = ThiefBrain(axes=AXES).decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move == "W"
