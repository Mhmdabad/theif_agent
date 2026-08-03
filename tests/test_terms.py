"""Tests for translating our config into the signed agreement."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.shared.config import config_sha256, validate
from thief_agent.shared.terms import REQUIRED_TERMS, TermsError, check_required, to_terms


def shipped() -> dict[str, Any]:
    text = (Path(__file__).parents[1] / "config/game.json").read_text()
    loaded: dict[str, Any] = json.loads(text)
    return loaded


class TestTranslation:
    def test_the_shipped_config_translates(self) -> None:
        assert to_terms(shipped())["board_size"] == 7

    def test_values_come_from_appendix_f_not_the_key_names(self) -> None:
        """Key names follow the wire; values still follow the book."""
        terms = to_terms(shipped())
        assert terms["barriers_max"] == 14
        assert terms["max_steps"] == 35
        assert terms["decay_per_step"] == 0.10
        assert terms["emit_intensity"] == 0.9
        assert terms["smell_grid_size"] == 5

    def test_start_positions_are_flat_on_the_wire(self) -> None:
        terms = to_terms(shipped())
        assert terms["thief_start"] == [3, 3]
        assert terms["cop_start"] == [0, 0]

    def test_map_area_becomes_setting(self) -> None:
        assert to_terms(shipped())["setting"] == "New York"

    def test_axis_convention_travels(self) -> None:
        """Both peers must agree it, so it belongs in the agreement."""
        terms = to_terms(shipped())
        assert terms["axis_origin_corner"] == "top-left"
        assert terms["axis_start_index"] == 0

    def test_negotiated_values_are_carried_not_overridden(self) -> None:
        config = copy.deepcopy(shipped())
        config["board_and_agents"]["grid_size"] = 10
        config["movement_and_barriers"]["max_barriers"] = 20
        terms = to_terms(config)
        assert terms["board_size"] == 10
        assert terms["barriers_max"] == 20


class TestRequiredTerms:
    def test_the_shipped_config_resolves_every_required_term(self) -> None:
        check_required(to_terms(shipped()))

    @pytest.mark.parametrize(
        ("section", "key"),
        [
            ("board_and_agents", "grid_size"),
            ("pheromones", "pheromone_decay"),
            ("movement_and_barriers", "max_moves"),
            ("movement_and_barriers", "max_barriers"),
            ("board_and_agents", "thief_start"),
        ],
    )
    def test_a_missing_source_value_fails_loudly(self, section: str, key: str) -> None:
        """A None board size crashes mid-play, or silently plays a different game."""
        config = copy.deepcopy(shipped())
        del config[section][key]
        with pytest.raises(TermsError, match=f"{section}.{key}"):
            to_terms(config)

    def test_an_explicit_null_is_refused_not_carried(self) -> None:
        """JSON null resolves the key but not the value; both must fail."""
        config = copy.deepcopy(shipped())
        config["movement_and_barriers"]["max_barriers"] = None
        with pytest.raises(TermsError, match="did not resolve"):
            to_terms(config)

    def test_an_opponents_incomplete_agreement_is_refused(self) -> None:
        with pytest.raises(TermsError, match="missing required terms"):
            check_required({"board_size": 7})

    def test_every_missing_term_is_named_at_once(self) -> None:
        """One message rather than one round trip per missing key."""
        with pytest.raises(TermsError) as excinfo:
            check_required({})
        for name in ("board_size", "barriers_max", "max_steps"):
            assert name in str(excinfo.value)

    def test_optional_terms_are_not_required(self) -> None:
        assert "setting" not in REQUIRED_TERMS
        assert "num_games" not in REQUIRED_TERMS


class TestAppendixFStillGoverns:
    def test_validation_runs_against_our_own_config(self) -> None:
        """Translating does not weaken the fixed/minimum checks."""
        validate(shipped())

    def test_a_fixed_value_change_is_still_refused_before_translation(self) -> None:
        config = copy.deepcopy(shipped())
        config["scoring"]["capture_cop"] = 99
        with pytest.raises(ValueError, match="disqualifies the team"):
            validate(config)

    def test_the_digest_covers_what_is_exchanged(self) -> None:
        """The digest we advertise must describe the terms we are agreeing."""
        config = shipped()
        before = config_sha256(config)
        changed = copy.deepcopy(config)
        changed["movement_and_barriers"]["max_barriers"] = 20
        assert config_sha256(changed) != before
        assert to_terms(changed)["barriers_max"] != to_terms(config)["barriers_max"]
