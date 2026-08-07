"""Tests for the exchanged scent fixture (#54).

The fixture is *generated* from the engine, because it is hash-locked and must
describe what we actually do. These tests are what stop that from being
circular: every number is checked against the rulebook's own printed values,
typed in by hand.
"""

import pytest

from thief_agent.domain.fixture import FIXTURE_BOARD, FIXTURE_CENTRE, ScentFixture, build
from thief_agent.domain.scent import CHEBYSHEV, PRECISION

FIGURE_4_CENTRE_ROW = [0.20, 0.62, 0.90, 0.62, 0.20]
"""Middle row of rulebook figure 4 (PDF p. 44), transcribed."""

BOOK_DECAY = (0.81, 0.729, 0.656)
"""0.9 decayed at rho = 0.10 for three turns, hand-computed.

The first value is the one PDF p. 47 uses in the lie-detection example.
Subtractive decay would give 0.80, 0.70, 0.60 — distinguishable at every step.
"""


class TestItMatchesTheBook:
    def test_the_decay_series_is_the_hand_computed_one(self) -> None:
        assert build().decay_series == BOOK_DECAY

    def test_the_first_value_is_the_lie_detection_example(self) -> None:
        """PDF p. 47: the cop expects a fresh northern trace of 0.81."""
        assert build().decay_series[0] == 0.81

    def test_it_is_not_the_subtractive_series(self) -> None:
        assert build().decay_series != (0.80, 0.70, 0.60)

    def test_the_emission_matches_figure_4(self) -> None:
        emission = build().emission
        row = [emission[f"{FIXTURE_CENTRE[0]},{col}"] for col in range(FIXTURE_BOARD)]
        assert [round(value, 2) for value in row] == FIGURE_4_CENTRE_ROW

    def test_the_centre_is_the_appendix_f_intensity(self) -> None:
        assert build().emission["2,2"] == 0.9


class TestItIsShareable:
    def test_it_is_unclipped(self) -> None:
        """A fixture cut off by a board edge would agree with a peer for the
        wrong reason: both sides comparing absences rather than values."""
        assert len(build().emission) == 25

    def test_every_value_fits_the_wire_precision(self) -> None:
        """A fixture carrying more digits than the protocol transmits would
        fail comparison against a peer who implemented the model correctly."""
        fixture = build()
        for value in fixture.emission.values():
            assert round(value, PRECISION) == value
        for value in fixture.decay_series:
            assert round(value, PRECISION) == value

    def test_the_terms_form_is_json_safe(self) -> None:
        import json

        assert json.loads(json.dumps(build().as_terms()))["model"] == "gaussian"

    def test_it_names_every_parameter_the_other_side_needs(self) -> None:
        terms = build().as_terms()
        assert set(terms) == {
            "model",
            "centre",
            "board_size",
            "centre_intensity",
            "grid_size",
            "decay_rate",
            "emission",
            "decay_series",
            "binding",
        }

    def test_it_is_stable_across_calls(self) -> None:
        assert build().as_terms() == build().as_terms()


class TestItTracksTheEngine:
    def test_a_negotiated_model_produces_a_different_fixture(self) -> None:
        """The point of generating rather than transcribing: whatever we
        actually run is what gets hashed."""
        gaussian, chebyshev = build(), build(falloff=CHEBYSHEV)
        assert chebyshev.model == "chebyshev"
        assert chebyshev.emission["2,2"] == 0.9
        assert chebyshev.emission["1,2"] == 0.6
        assert gaussian.emission["1,2"] != chebyshev.emission["1,2"]

    def test_decay_is_unaffected_by_the_falloff_choice(self) -> None:
        """Two independent agreement terms. Negotiating one must not silently
        change the other."""
        assert build(falloff=CHEBYSHEV).decay_series == BOOK_DECAY

    def test_it_is_a_value_not_a_view(self) -> None:
        assert isinstance(build(), ScentFixture)
        with pytest.raises(AttributeError):
            build().model = "tampered"  # type: ignore[misc]
