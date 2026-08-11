"""Tests for hint generation (#65)."""

import random

import pytest

from thief_agent.domain.bluff import (
    COMPASS,
    TEMPLATES,
    Bluff,
    SelfContradictionError,
    bearing,
    compose,
    contradicts_our_field,
    decoy,
    nearest_landmark,
    plausible_decoy,
    speak,
    vet,
)
from thief_agent.domain.board import BoardState
from thief_agent.domain.hints import DIRECTIONS, LANDMARKS, MAX_WORDS, NUMERIC, parse
from thief_agent.domain.providers import declared_model
from thief_agent.domain.scent import emission
from thief_agent.domain.trail import Trail

BOARD = BoardState(cop=(0, 0), thief=(5, 1), grid_size=7)


def every_hint() -> list[str]:
    return [
        compose(cell, BOARD, (3, 3), random.Random(seed))
        for seed in range(len(TEMPLATES))
        for cell in ((0, 0), (5, 1), (6, 6), (3, 3), (0, 6))
    ]


class TestWhatTheDeclarationAnnounces:
    """The provider decides, not the model name.

    Announcing ``claude-haiku-4-5`` beside ``total_tokens: 0`` is a
    contradiction a marker can see, and rule 54 calls it a false statement.
    """

    def test_template_names_itself_rather_than_a_model_it_never_calls(self) -> None:
        assert declared_model({"provider": "template", "model": "claude-haiku-4-5"}) == "template"

    def test_a_real_provider_names_its_model(self) -> None:
        assert (
            declared_model({"provider": "claude_api", "model": "claude-haiku-4-5"})
            == "claude-haiku-4-5"
        )

    def test_a_provider_with_no_model_names_the_provider(self) -> None:
        assert declared_model({"provider": "ollama"}) == "ollama"

    def test_an_absent_table_is_the_template_default(self) -> None:
        """Matching the default the loader applies, so the two cannot disagree."""
        assert declared_model(None) == "template"


class TestTheWordCap:
    def test_it_is_the_appendix_f_value(self) -> None:
        assert MAX_WORDS == 15

    def test_every_template_fits_once_filled(self) -> None:
        assert all(len(hint.split()) <= MAX_WORDS for hint in every_hint())

    def test_a_hint_is_never_empty(self) -> None:
        assert all(hint.strip() for hint in every_hint())


class TestNoCoordinates:
    def test_nothing_we_emit_could_be_a_coordinate_protocol(self) -> None:
        """Our own parser refuses these; emitting one would be our violation."""
        assert not any(NUMERIC.search(hint) for hint in every_hint())

    def test_no_digits_at_all(self) -> None:
        assert not any(char.isdigit() for hint in every_hint() for char in hint)

    def test_our_own_parser_reads_what_we_write(self) -> None:
        """A hint the opponent cannot parse is silence we paid a turn for."""
        for hint in every_hint():
            assert parse(hint, BOARD, (3, 3)), hint


class TestItDescribesARegion:
    def test_a_hint_names_a_direction_or_a_landmark(self) -> None:
        for hint in every_hint():
            spoken = set(hint.lower().replace(",", " ").split())
            assert spoken & (set(DIRECTIONS) | set(LANDMARKS)), hint

    def test_only_compass_words_the_parser_reads_back(self) -> None:
        """'north-east' would be honest and unparseable, which helps nobody."""
        assert all(word in DIRECTIONS for word, _ in COMPASS)

    def test_the_larger_displacement_wins(self) -> None:
        assert bearing((3, 3), (0, 4)) == "north"
        assert bearing((3, 3), (4, 6)) == "east"

    def test_a_zero_displacement_still_yields_a_word(self) -> None:
        assert bearing((3, 3), (3, 3)) in DIRECTIONS


class TestDeterminism:
    def test_the_same_seed_gives_the_same_sentence(self) -> None:
        """A hint that differed between a match and its replay is one the
        audit cannot check."""
        assert compose((5, 1), BOARD, (3, 3), random.Random(4)) == compose(
            (5, 1), BOARD, (3, 3), random.Random(4)
        )

    def test_the_nearest_landmark_is_stable_under_ties(self) -> None:
        assert nearest_landmark((3, 3), BOARD) == nearest_landmark((3, 3), BOARD)

    def test_it_works_without_an_rng(self) -> None:
        assert compose((5, 1), BOARD, (3, 3))


class TestLying:
    def test_a_lie_reads_the_same_as_a_truth(self) -> None:
        """Phrasing that changed when we lie is a tell worth more to the
        opponent than the lie costs them."""
        truth = compose((5, 1), BOARD, (3, 3), random.Random(1))
        lie = compose(decoy((5, 1), BOARD), BOARD, (3, 3), random.Random(1))
        assert truth != lie
        assert truth.split()[0] == lie.split()[0]

    def test_the_decoy_is_far_from_the_truth(self) -> None:
        """A lie one square off is a lie the trail confirms — we would spend
        credibility to tell them something true."""
        for cell in ((0, 0), (5, 1), (2, 3)):
            far = decoy(cell, BOARD)
            assert abs(far[0] - cell[0]) + abs(far[1] - cell[1]) >= BOARD.grid_size - 1

    def test_the_decoy_is_on_the_board(self) -> None:
        for cell in ((0, 0), (6, 6), (3, 3)):
            assert BOARD.in_bounds(decoy(cell, BOARD))

    def test_a_centre_cell_still_produces_a_distant_decoy(self) -> None:
        """The regression. Mirroring lands (2, 3) two squares away, close
        enough that our own emission reaches it — a lie the trail confirms."""
        for cell in ((3, 3), (2, 3), (3, 4)):
            far = decoy(cell, BOARD)
            assert BOARD.in_bounds(far)
            assert abs(far[0] - cell[0]) + abs(far[1] - cell[1]) >= BOARD.grid_size - 1

    def test_it_is_stable_under_ties(self) -> None:
        assert decoy((3, 3), BOARD) == decoy((3, 3), BOARD)


class TestLandmarks:
    def test_it_names_the_closest_one(self) -> None:
        assert nearest_landmark((0, 3), BOARD) == "uptown"

    def test_landmarks_scale_with_the_board(self) -> None:
        big = BoardState(cop=(0, 0), thief=(3, 3), grid_size=11)
        assert nearest_landmark((10, 10), big) == nearest_landmark((6, 6), BOARD)

    def test_every_named_place_is_one_the_parser_knows(self) -> None:
        for hint in every_hint():
            named = [word for word in hint.lower().split() if word in LANDMARKS]
            assert named, hint


class TestIntentIsChosenFirst:
    """#66: the flag is decided before the sentence, not after."""

    def test_intent_is_an_argument_not_a_result(self) -> None:
        """Deciding afterwards would let the label be picked to suit whatever
        came out, and the committed flag is meant to be a promise."""
        assert speak((5, 1), BOARD, (3, 3), "truth").intent == "truth"
        assert speak((5, 1), BOARD, (3, 3), "lie").intent == "lie"

    def test_a_truthful_hint_points_at_where_we_are(self) -> None:
        assert speak((5, 1), BOARD, (3, 3), "truth").about == (5, 1)

    def test_a_lie_points_elsewhere(self) -> None:
        assert speak((5, 1), BOARD, (3, 3), "lie").about != (5, 1)

    @pytest.mark.parametrize("bad", ["maybe", "TRUTH", "", "bluff"])
    def test_an_unknown_intent_is_refused(self, bad: str) -> None:
        with pytest.raises(ValueError, match="intent must be one of"):
            speak((5, 1), BOARD, (3, 3), bad)

    def test_the_flag_travels_with_the_text(self) -> None:
        spoken = speak((5, 1), BOARD, (3, 3), "lie")
        assert spoken.text and spoken.intent == "lie" and spoken.about


class TestSelfConsistency:
    """#67: never send a claim our own field refutes."""

    @staticmethod
    def trail_through(*cells: tuple[int, int]) -> dict[tuple[int, int], float]:
        laid = Trail()
        for cell in cells:
            laid.deposit(emission(cell, BOARD.grid_size))
            laid.decay()
        return laid.values

    def test_a_claim_our_own_scent_refutes_is_refused(self) -> None:
        """Our trail is public and unforgeable. A claim the opponent can
        disprove by reading it is a free credibility donation."""
        here = self.trail_through((5, 1))
        far = Bluff(intent="lie", text="north", about=(0, 6))
        with pytest.raises(SelfContradictionError, match="convict on arrival"):
            vet(far, here)

    def test_a_claim_our_own_scent_supports_is_allowed(self) -> None:
        """A credible lie points at somewhere we genuinely have been."""
        walked = self.trail_through((0, 5), (5, 1))
        assert vet(Bluff(intent="lie", text="north", about=(0, 5)), walked)

    def test_truthful_hints_are_never_vetted(self) -> None:
        """Running the check on them would refuse honest hints in the opening
        turns, before our trail has accumulated."""
        honest = Bluff(intent="truth", text="south", about=(5, 1))
        assert vet(honest, {}) is honest

    def test_it_is_the_opponents_own_detector_pointed_at_us(self) -> None:
        assert contradicts_our_field(
            Bluff(intent="lie", text="x", about=(0, 6)), self.trail_through((5, 1)), 0.81
        )

    def test_a_plausible_decoy_aims_at_our_own_history(self) -> None:
        """The flaw the guard exposed: a corner lie is refuted by our own
        emission the moment the opponent reads it."""
        walked = self.trail_through((0, 5), (5, 1))
        assert plausible_decoy((5, 1), BOARD, walked) == (0, 5)

    def test_with_no_trail_it_falls_back_and_the_guard_refuses(self) -> None:
        """Correct for the opening turns: nothing to be credible with, so we
        should be telling the truth."""
        assert plausible_decoy((5, 1), BOARD, {}) == decoy((5, 1), BOARD)

    def test_speak_uses_the_credible_decoy_when_given_a_field(self) -> None:
        walked = self.trail_through((0, 5), (5, 1))
        assert speak((5, 1), BOARD, (3, 3), "lie", own_field=walked).about == (0, 5)

    def test_it_is_stable_across_calls(self) -> None:
        walked = self.trail_through((0, 5), (5, 1))
        assert plausible_decoy((5, 1), BOARD, walked) == plausible_decoy((5, 1), BOARD, walked)


class TestTheFlagIsValidatedOnTheObjectToo:
    def test_a_bluff_cannot_be_built_with_a_bad_intent(self) -> None:
        """speak() guards the entry point; the dataclass guards anything that
        constructs one directly — including a payload rebuilt off the wire."""
        with pytest.raises(ValueError, match="intent must be one of"):
            Bluff(intent="perhaps", text="north", about=(0, 0))

    def test_a_valid_one_is_immutable(self) -> None:
        """The flag is committed alongside the move; revising it after the
        hash is sent is exactly what the commitment forbids."""
        spoken = Bluff(intent="lie", text="north", about=(0, 0))
        with pytest.raises(AttributeError):
            spoken.intent = "truth"  # type: ignore[misc]
