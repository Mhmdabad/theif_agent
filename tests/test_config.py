"""Tests for the Appendix F table and the shared-config validator."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.shared.appendix_f import TABLE, Status
from thief_agent.shared.config import (
    ConfigError,
    canonical_bytes,
    config_sha256,
    load,
    validate,
)

CONFIG_PATH = Path(__file__).parents[1] / "config/game.json"


def shipped() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text())  # type: ignore[no-any-return]


class TestTable:
    def test_every_status_is_represented(self) -> None:
        assert {p.status for p in TABLE} == set(Status)

    def test_no_duplicate_parameters(self) -> None:
        keys = [(p.section, p.key) for p in TABLE]
        assert len(keys) == len(set(keys))

    def test_scoring_is_entirely_fixed(self) -> None:
        scoring = [p for p in TABLE if p.section == "scoring"]
        assert len(scoring) == 6
        assert all(p.status is Status.FIXED for p in scoring)

    def test_pheromones_are_entirely_fixed(self) -> None:
        pher = [p for p in TABLE if p.section == "pheromones"]
        assert len(pher) == 3
        assert all(p.status is Status.FIXED for p in pher)

    def test_rate_limits_are_minimums(self) -> None:
        limiter = [p for p in TABLE if p.section == "rate_limiter_gatekeeper"]
        assert len(limiter) == 5
        assert all(p.status is Status.MINIMUM for p in limiter)


class TestShippedConfig:
    def test_validates_clean(self) -> None:
        validate(shipped())

    def test_loads(self) -> None:
        assert load(CONFIG_PATH)["schema_version"] == "1.2"


class TestFixedValues:
    @pytest.mark.parametrize(
        ("section", "key", "bad"),
        [
            ("scoring", "capture_cop", 99),
            ("scoring", "tie_score", 3),
            ("pheromones", "pheromone_decay", 0.2),
            ("board_and_agents", "num_agents", 3),
            ("network_and_league", "diversity_reward", 20),
        ],
    )
    def test_any_deviation_is_refused(self, section: str, key: str, bad: object) -> None:
        config = copy.deepcopy(shipped())
        config[section][key] = bad
        with pytest.raises(ConfigError, match="disqualifies the team"):
            validate(config)

    def test_move_set_may_not_gain_a_diagonal(self) -> None:
        config = copy.deepcopy(shipped())
        config["movement_and_barriers"]["move_set"].append("NE")
        with pytest.raises(ConfigError, match="disqualifies the team"):
            validate(config)


class TestMinimums:
    @pytest.mark.parametrize(
        ("section", "key", "below"),
        [
            ("board_and_agents", "grid_size", 5),
            ("movement_and_barriers", "max_barriers", 10),
            ("movement_and_barriers", "survival_threshold", 20),
            ("rate_limiter_gatekeeper", "max_retries", 1),
        ],
    )
    def test_below_the_book_value_is_refused(self, section: str, key: str, below: int) -> None:
        config = copy.deepcopy(shipped())
        config[section][key] = below
        with pytest.raises(ConfigError, match="never lowered"):
            validate(config)

    @pytest.mark.parametrize(
        ("section", "key", "above"),
        [
            ("board_and_agents", "grid_size", 10),
            ("movement_and_barriers", "max_barriers", 20),
            ("movement_and_barriers", "survival_threshold", 50),
        ],
    )
    def test_raising_is_allowed(self, section: str, key: str, above: int) -> None:
        config = copy.deepcopy(shipped())
        config[section][key] = above
        validate(config)


class TestNegotiable:
    @pytest.mark.parametrize(
        ("section", "key", "value"),
        [
            ("world", "map_area", "London"),
            ("world", "hint_max_words", 8),
            ("board_and_agents", "axis_origin_corner", "bottom-right"),
            ("board_and_agents", "axis_start_index", 1),
            ("network_and_league", "response_timeout_sec", 5),
        ],
    )
    def test_any_agreed_value_passes(self, section: str, key: str, value: object) -> None:
        config = copy.deepcopy(shipped())
        config[section][key] = value
        validate(config)


class TestReporting:
    def test_missing_parameter_is_reported(self) -> None:
        config = copy.deepcopy(shipped())
        del config["scoring"]["capture_cop"]
        with pytest.raises(ConfigError, match="scoring.capture_cop is missing"):
            validate(config)

    def test_missing_section_is_reported(self) -> None:
        config = copy.deepcopy(shipped())
        del config["pheromones"]
        with pytest.raises(ConfigError, match="pheromones.pheromone_decay is missing"):
            validate(config)

    def test_all_violations_are_listed_not_just_the_first(self) -> None:
        """A misconfigured file is fixed in one pass, not several."""
        config = copy.deepcopy(shipped())
        config["scoring"]["capture_cop"] = 99
        config["scoring"]["survival_thief"] = 1
        config["board_and_agents"]["grid_size"] = 3
        with pytest.raises(ConfigError) as excinfo:
            validate(config)
        message = str(excinfo.value)
        assert "scoring.capture_cop" in message
        assert "scoring.survival_thief" in message
        assert "board_and_agents.grid_size" in message


class TestCanonicalHashing:
    def test_key_order_does_not_change_the_digest(self) -> None:
        """Both peers must hash identical bytes regardless of key order."""
        config = shipped()
        shuffled = dict(reversed(list(config.items())))
        assert config_sha256(config) == config_sha256(shuffled)

    def test_canonical_bytes_have_no_incidental_whitespace(self) -> None:
        assert b", " not in canonical_bytes(shipped())
        assert b": " not in canonical_bytes(shipped())

    def test_digest_is_stable(self) -> None:
        assert config_sha256(shipped()) == config_sha256(shipped())

    def test_any_change_changes_the_digest(self) -> None:
        config = copy.deepcopy(shipped())
        before = config_sha256(config)
        config["world"]["map_area"] = "London"
        assert config_sha256(config) != before
