"""Tests for the opponent-only sampling rule (#53)."""

import pytest

from thief_agent.domain.memory import ScentMemory
from thief_agent.domain.scent import emission


class TestTheSamplingRuleIsStructural:
    def test_no_method_returns_a_merged_view(self) -> None:
        """#53 asks for a property of the API, not a convention. A merged
        view has no legitimate use, so none is offered."""
        readers = {"sample", "strongest"}
        assert readers <= set(dir(ScentMemory))
        assert not any(name for name in dir(ScentMemory) if "both" in name or "merged" in name)

    def test_sampling_never_sees_our_own_emission(self) -> None:
        """The failure this prevents: our own trail is brightest exactly where
        we are, so a pooled field would have the agent confidently track
        itself."""
        memory = ScentMemory()
        memory.emit((3, 3), 7)
        assert memory.sample((3, 3)) == 0.0
        assert memory.strongest() is None

    def test_the_opponents_field_is_what_is_sampled(self) -> None:
        memory = ScentMemory()
        memory.emit((0, 0), 7)
        memory.absorb({"5,5": 0.9, "5,4": 0.62}, 7)
        assert memory.sample((5, 5)) == 0.9
        assert memory.strongest() == (5, 5)

    def test_our_own_field_is_reachable_only_for_transmission(self) -> None:
        memory = ScentMemory()
        memory.emit((3, 3), 7)
        assert memory.outgoing()["3,3"] == 0.9
        assert memory.sample((3, 3)) == 0.0

    def test_the_two_fields_do_not_contaminate_each_other(self) -> None:
        memory = ScentMemory()
        memory.emit((3, 3), 7)
        memory.absorb({"3,3": 0.2}, 7)
        assert memory.sample((3, 3)) == 0.2
        assert memory.outgoing()["3,3"] == 0.9


class TestEmission:
    def test_it_returns_what_it_laid(self) -> None:
        memory = ScentMemory()
        assert memory.emit((3, 3), 7) == emission((3, 3), 7)

    def test_repeated_emission_on_one_cell_does_not_accumulate(self) -> None:
        memory = ScentMemory()
        for _ in range(4):
            memory.emit((3, 3), 7)
        assert memory.outgoing()["3,3"] == 0.9


class TestAbsorbingAnAdversarialField:
    def test_off_board_cells_are_dropped_not_trusted(self) -> None:
        """The field arrives from someone who benefits from us believing wrong
        things. A cell off the board would crash a consumer or quietly widen
        the board we reason about."""
        memory = ScentMemory()
        memory.absorb({"9,9": 0.9, "-1,0": 0.9, "3,3": 0.5}, 7)
        assert memory.opponent.values == {(3, 3): 0.5}

    def test_malformed_keys_are_skipped_rather_than_raising(self) -> None:
        memory = ScentMemory()
        memory.absorb({"north": 0.9, "3,3": 0.5, "1,2,3": 0.4}, 7)
        assert memory.sample((3, 3)) == 0.5

    def test_absorbing_max_merges(self) -> None:
        memory = ScentMemory()
        memory.absorb({"3,3": 0.5}, 7)
        memory.absorb({"3,3": 0.9}, 7)
        memory.absorb({"3,3": 0.2}, 7)
        assert memory.sample((3, 3)) == 0.9


class TestDecay:
    def test_both_fields_age(self) -> None:
        """Ours decays too. We never read it, but we transmit it, and sending
        an un-aged field advertises a trail inconsistent with the model both
        sides hash-locked."""
        memory = ScentMemory()
        memory.emit((3, 3), 7)
        memory.absorb({"5,5": 0.9}, 7)
        memory.decay()
        assert memory.outgoing()["3,3"] == 0.81
        assert round(memory.sample((5, 5)), 3) == 0.81

    def test_a_round_trip_reproduces_the_books_value(self) -> None:
        """Emit, transmit, absorb, age one turn: 0.9 -> 0.81, both sides."""
        mine, theirs = ScentMemory(), ScentMemory()
        mine.emit((2, 2), 7)
        theirs.absorb(mine.outgoing(), 7)
        theirs.decay()
        assert round(theirs.sample((2, 2)), 3) == 0.81


class TestItComposesWithTheRestOfTheEngine:
    def test_the_transmitted_field_is_the_wire_form(self) -> None:
        memory = ScentMemory()
        memory.emit((1, 1), 7)
        wire = memory.outgoing()
        assert all(isinstance(key, str) and "," in key for key in wire)
        assert wire == dict(sorted(wire.items()))

    def test_an_empty_memory_transmits_nothing_and_knows_nothing(self) -> None:
        memory = ScentMemory()
        assert memory.outgoing() == {}
        assert memory.strongest() is None
        assert memory.sample((0, 0)) == 0.0

    @pytest.mark.parametrize("cell", [(0, 0), (6, 6), (0, 3), (3, 3)])
    def test_emission_is_clipped_wherever_we_stand(self, cell: tuple[int, int]) -> None:
        memory = ScentMemory()
        memory.emit(cell, 7)
        assert all(0 <= int(k.split(",")[0]) < 7 for k in memory.outgoing())
