"""Tests for barrier-aware reachability tracking (#38)."""

import logging
from dataclasses import replace

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.rules import target_of
from thief_agent.strategy.containment import (
    SHRINK_THRESHOLD,
    WINDOW,
    ContainmentTracker,
)
from thief_agent.strategy.thief_brain import ThiefBrain, manhattan

AXES = AxisConvention()


def make(**kw: object) -> BoardState:
    cop = kw.get("cop", (0, 0))
    thief = kw.get("thief", (3, 3))
    barriers = kw.get("barriers", frozenset())
    step = kw.get("step", 0)
    assert isinstance(cop, tuple) and isinstance(thief, tuple)
    assert isinstance(barriers, frozenset | set) and isinstance(step, int)
    return BoardState(cop=cop, thief=thief, grid_size=7, barriers=frozenset(barriers), step=step)


def walk(tracker: ContainmentTracker, *states: BoardState) -> None:
    for state in states:
        tracker.observe(state, AXES)


class TestObservation:
    def test_it_records_area_and_barrier_count(self) -> None:
        tracker = ContainmentTracker()
        entry = tracker.observe(make(), AXES)
        assert entry.area == 49
        assert entry.barriers == 0
        assert entry.step == 0

    def test_observing_the_same_step_twice_is_a_no_op(self) -> None:
        """A decision must not depend on how often the tracker was consulted."""
        tracker = ContainmentTracker()
        state = make()
        first = tracker.observe(state, AXES)
        assert tracker.observe(state, AXES) is first
        assert len(tracker.history) == 1

    def test_a_new_step_is_a_new_record(self) -> None:
        tracker = ContainmentTracker()
        walk(tracker, make(step=0), make(step=1))
        assert len(tracker.history) == 2

    def test_area_is_zero_before_anything_is_seen(self) -> None:
        assert ContainmentTracker().area == 0


class TestTrend:
    def test_one_observation_is_a_value_not_a_direction(self) -> None:
        """Guessing a direction here would have the thief flee its own start."""
        tracker = ContainmentTracker()
        tracker.observe(make(), AXES)
        assert tracker.trend == 0
        assert not tracker.closing

    def test_a_steady_region_has_no_trend(self) -> None:
        tracker = ContainmentTracker()
        walk(tracker, make(step=0), make(step=1), make(step=2))
        assert tracker.trend == 0
        assert not tracker.closing

    def test_a_shrinking_region_reads_negative(self) -> None:
        tracker = ContainmentTracker()
        walk(
            tracker,
            make(step=0),
            make(step=1, barriers={(0, 0)}),
            make(step=2, barriers={(0, 0), (0, 1)}),
        )
        assert tracker.trend == -2

    def test_one_lost_cell_is_not_a_containment_plan(self) -> None:
        """A wall going up where the thief was never going. Not a direction."""
        tracker = ContainmentTracker()
        walk(tracker, make(step=0), make(step=1, barriers={(0, 0)}))
        assert tracker.trend == -1
        assert not tracker.closing

    def test_two_lost_cells_is(self) -> None:
        tracker = ContainmentTracker()
        walk(
            tracker,
            make(step=0),
            make(step=1, barriers={(0, 0)}),
            make(step=2, barriers={(0, 0), (0, 1)}),
        )
        assert tracker.trend <= -SHRINK_THRESHOLD
        assert tracker.closing

    def test_the_window_forgets_old_turns(self) -> None:
        """Barriers are permanent, so a lifetime total only ever grows. The
        window is what keeps this a rate rather than a running tally."""
        tracker = ContainmentTracker()
        walls = {(0, 0), (0, 1), (0, 2)}
        walk(tracker, make(step=0), make(step=1, barriers=walls))
        assert tracker.closing
        walk(tracker, make(step=2, barriers=walls), make(step=3, barriers=walls))
        assert len(tracker.history) == WINDOW + 1
        assert tracker.trend == 0
        assert not tracker.closing

    def test_a_sealed_pocket_shows_the_collapse(self) -> None:
        tracker = ContainmentTracker()
        pocket = {(0, 2), (1, 2), (2, 2), (2, 1), (2, 0)}
        walk(tracker, make(thief=(0, 0), step=0), make(thief=(0, 0), barriers=pocket, step=1))
        assert tracker.area == 4
        assert tracker.closing


class TestAvailableToTheScorer:
    def test_the_brain_observes_each_turn(self) -> None:
        brain = ThiefBrain(axes=AXES)
        brain.decide(make(step=0))
        brain.decide(make(step=1, barriers={(0, 0)}))
        assert [entry.step for entry in brain.reach.history] == [0, 1]

    def test_deciding_twice_on_one_turn_gives_the_same_answer(self) -> None:
        """The tracker is memory, and memory in a decision path is where
        replayability usually dies."""
        brain = ThiefBrain(axes=AXES)
        state = make(step=0)
        assert brain.decide(state).action == brain.decide(state).action
        assert len(brain.reach.history) == 1

    def test_outside_a_trap_distance_still_leads(self) -> None:
        brain = ThiefBrain(axes=AXES)
        state = make(cop=(0, 0), thief=(3, 3))
        brain.reach.observe(state, AXES)
        assert not brain.reach.closing
        assert brain._rank(state, "S", state.cop)[1] > brain._rank(state, "N", state.cop)[1]

    def test_inside_one_the_ranking_leads_with_degree(self) -> None:
        """The swap #38 exists to enable, asserted on the tuple itself."""
        brain = ThiefBrain(axes=AXES)
        walls = {(6, 0), (6, 1), (6, 2)}
        walk(brain.reach, make(step=0), make(barriers=walls, step=1))
        assert brain.reach.closing
        state = make(cop=(5, 5), thief=(1, 1), barriers=walls, step=1)
        assert brain._rank(state, "S", state.cop)[1] == 4
        assert brain._rank(state, "N", state.cop)[1] == 3

    def test_a_closing_region_reverses_the_choice(self) -> None:
        """Same board, same threat; only the history differs.

        From (0, 1) with the cop at (5, 5), the distance-led policy takes W
        into the corner (0, 0), gaining a cell of distance and landing on
        degree-2 ground. Once the region is closing, degree leads and the thief
        goes S to (1, 1) — **toward** the cop, giving up distance for open
        board. The cop does not have to enter a pocket it is sealing, so
        distance bought inside one buys nothing.
        """
        walls = frozenset({(6, 0), (6, 1), (6, 2)})
        opening = BoardState(cop=(5, 5), thief=(0, 1), grid_size=7, step=0)
        closing = replace(opening, barriers=walls, step=1)

        calm = ThiefBrain(axes=AXES)
        calm.reach.observe(opening, AXES)
        assert not calm.reach.closing
        assert target_of(
            opening.thief,
            calm.decide(opening, threat=opening.cop).action.move,  # type: ignore[union-attr]
            AXES,
        ) == (0, 0)

        trapped = ThiefBrain(axes=AXES)
        walk(trapped.reach, opening, closing)
        assert trapped.reach.closing
        moved_to = target_of(
            closing.thief,
            trapped.decide(closing, threat=closing.cop).action.move,  # type: ignore[union-attr]
            AXES,
        )
        assert moved_to == (1, 1)
        assert manhattan(moved_to, closing.cop) < manhattan(closing.thief, closing.cop)

    def test_the_veto_survives_the_swap(self) -> None:
        """A trap is when a cramped cell is most tempting and most fatal."""
        brain = ThiefBrain(axes=AXES)
        walls = {(6, 0), (6, 1), (6, 2)}
        walk(brain.reach, make(step=0), make(barriers=walls, step=1))
        assert brain.reach.closing
        state = make(cop=(3, 0), thief=(0, 1), barriers=walls, step=1)
        assert brain.is_cramped(state, "W", state.cop)
        assert brain._rank(state, "W", state.cop)[0] == 0
        assert brain._rank(state, "S", state.cop)[0] == 1

    def test_the_trend_is_logged_every_turn(self, caplog: pytest.LogCaptureFixture) -> None:
        brain = ThiefBrain(axes=AXES)
        with caplog.at_level(logging.INFO, logger="thief_agent.strategy.thief_brain"):
            brain.decide(make(step=0))
        assert "area=49" in caplog.text and "trend=+0" in caplog.text

    def test_an_unobserved_tracker_says_so(self) -> None:
        assert str(ContainmentTracker()) == "reach: unobserved"

    def test_a_closing_tracker_says_so(self) -> None:
        tracker = ContainmentTracker()
        walk(tracker, make(step=0), make(step=1, barriers={(0, 0), (0, 1), (1, 0)}))
        assert "CLOSING" in str(tracker)


class TestStayIsFirstClass:
    """#39: STAY is scored alongside the four moves, and charged for."""

    def test_it_is_among_the_candidates_not_a_fallback(self) -> None:
        assert "STAY" in ThiefBrain(axes=AXES).options(make())

    def test_arriving_somewhere_costs_nothing(self) -> None:
        brain = ThiefBrain(axes=AXES)
        brain.reach.observe(make(step=0), AXES)
        assert brain.reach.linger == 0
        assert brain.scent_cost(make(step=0), "STAY") == 0

    def test_each_turn_held_adds_a_cell_to_the_bill(self) -> None:
        brain = ThiefBrain(axes=AXES)
        here = make(thief=(3, 3), step=1)
        walk(brain.reach, make(thief=(3, 3), step=0), here)
        assert brain.scent_cost(here, "STAY") == 1
        walk(brain.reach, make(thief=(3, 3), step=2))
        assert brain.scent_cost(make(thief=(3, 3), step=2), "STAY") == 2

    def test_moving_clears_it(self) -> None:
        brain = ThiefBrain(axes=AXES)
        walk(brain.reach, make(thief=(3, 3), step=0), make(thief=(3, 3), step=1))
        assert brain.reach.linger == 1
        walk(brain.reach, make(thief=(3, 4), step=2))
        assert brain.reach.linger == 0

    def test_returning_later_is_not_lingering(self) -> None:
        """Consecutive occupancy, not lifetime visits. Decay is real."""
        brain = ThiefBrain(axes=AXES)
        walk(
            brain.reach,
            make(thief=(3, 3), step=0),
            make(thief=(3, 4), step=1),
            make(thief=(3, 3), step=2),
        )
        assert brain.reach.linger == 0

    def test_fresh_ground_is_free(self) -> None:
        """Moving somewhere we have not been carries no bill; that is the point."""
        brain = ThiefBrain(axes=AXES)
        here = make(thief=(3, 3), step=1)
        walk(brain.reach, make(thief=(3, 3), step=0), here)
        assert all(brain.scent_cost(here, move) == 0 for move in ("N", "S", "E", "W"))

    def test_going_back_is_charged_like_staying(self) -> None:
        """The bounce the old meter could not see.

        Charging only ``STAY`` priced sitting still and missed the cheaper
        disguise: two adjacent cells share almost all of one emission field, so
        alternating between them lights the same neighbourhood as brightly as
        camping — while the cell changes every turn, which is all ``linger``
        was watching.
        """
        brain = ThiefBrain(axes=AXES)
        here = make(thief=(3, 3), step=2)
        walk(
            brain.reach,
            make(thief=(3, 3), step=0),
            make(thief=(3, 4), step=1),
            here,
        )
        assert brain.reach.linger == 0, "the old meter saw nothing here"
        assert brain.scent_cost(here, "E") == 1, "going back to (3, 4) is not free"

    def test_stay_is_chosen_when_it_dominates(self) -> None:
        """Closing region, and standing still is the only degree-4 cell that
        is not also nearer the cop. Waiting is the right answer."""
        walls = {(6, 0), (6, 1), (6, 2)}
        brain = ThiefBrain(axes=AXES)
        walk(brain.reach, make(step=0), make(cop=(5, 5), thief=(1, 1), barriers=walls, step=1))
        assert brain.reach.closing
        state = make(cop=(5, 5), thief=(1, 1), barriers=walls, step=1)
        action = brain.decide(state, threat=state.cop).action
        assert isinstance(action, MoveAction)
        assert action.move == "STAY"

    def test_and_abandoned_once_the_signal_is_paid_for(self) -> None:
        """Same position, one turn of lingering. The beacon costs the cell of
        distance that made waiting worth it."""
        walls = {(6, 0), (6, 1), (6, 2)}
        held = make(cop=(5, 5), thief=(1, 1), barriers=walls, step=1)
        later = make(cop=(5, 5), thief=(1, 1), barriers=walls, step=2)
        brain = ThiefBrain(axes=AXES)
        walk(brain.reach, make(step=0), held, later)
        assert brain.reach.linger == 1
        action = brain.decide(later).action
        assert isinstance(action, MoveAction)
        assert action.move != "STAY"

    def test_a_thief_with_nowhere_to_go_still_stays(self) -> None:
        """The cost is a weight, not a veto. No scent bill makes an illegal
        move legal."""
        walls = frozenset({(2, 3), (4, 3), (3, 2), (3, 4)})
        state = make(thief=(3, 3), barriers=walls, step=5)
        brain = ThiefBrain(axes=AXES)
        for step in range(5):
            walk(brain.reach, make(thief=(3, 3), barriers=walls, step=step))
        assert brain.scent_cost(state, "STAY") >= 4
        action = brain.decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move == "STAY"

    def test_the_cost_is_charged_to_distance_not_to_the_veto(self) -> None:
        """Geometry decides whether a cell is cramped; scent does not."""
        brain = ThiefBrain(axes=AXES)
        walk(brain.reach, make(thief=(3, 3), step=0), make(thief=(3, 3), step=1))
        state = make(cop=(0, 0), thief=(3, 3), step=1)
        assert not brain.is_cramped(state, "STAY", state.cop)
        assert brain._rank(state, "STAY", state.cop)[1] == 6 - 1
