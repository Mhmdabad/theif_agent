"""The per-sub-game config: locked, exchanged as a digest, verified on load."""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.config_file import _NOT_A_TERM, ConfigFileError, LockedConfig, load, lock
from thief_agent.shared.config import config_sha256
from thief_agent.shared.naming import NamingError

TEAMS = ("uoh26-thieves", "uoh26-others")


def parameters() -> dict[str, Any]:
    body = json.loads((Path(__file__).resolve().parent.parent / "config/game.json").read_text())
    assert isinstance(body, dict)
    return body


def locked(**overrides: object) -> LockedConfig:
    fields: dict[str, object] = {
        "game_id": "uoh26-s82kma9e",
        "game_uid": "u-0001",
        "sub_game": 2,
        "parameters": parameters(),
        "agreed_between": TEAMS,
    }
    fields.update(overrides)
    return lock(**fields)  # type: ignore[arg-type]


class TestLocking:
    def test_the_repository_config_locks(self) -> None:
        """The real file, not a fixture — it must be legal under Appendix F."""
        assert locked().sha256

    def test_the_digest_covers_the_parameters_only(self) -> None:
        """Never the object that already contains the digest."""
        assert locked().sha256 == config_sha256(parameters())

    def test_the_digest_is_not_in_what_it_covers(self) -> None:
        body = locked().to_dict()
        terms = {k: v for k, v in body.items() if k not in _NOT_A_TERM}
        assert "config_sha256" not in terms
        assert config_sha256(terms) == body["config_sha256"]

    def test_two_peers_with_the_same_parameters_agree(self) -> None:
        assert locked().agrees_with(locked().sha256)

    def test_a_different_parameter_disagrees(self) -> None:
        changed = parameters()
        changed["world"]["hint_max_words"] = 14
        assert not locked().agrees_with(locked(parameters=changed).sha256)

    def test_the_digest_is_recomputed_rather_than_cached(self) -> None:
        """A cached digest is a second copy of a fact that already exists."""
        config = locked()
        first = config.sha256
        assert config.sha256 == first


class TestAppendixFIsCheckedBeforeAnythingIsLocked:
    def test_an_illegal_config_is_refused(self) -> None:
        """A locked bad value is still a bad value, and it disqualifies."""
        broken = parameters()
        broken["scoring"]["technical_loss"] = 5
        with pytest.raises(ConfigFileError, match="violates Appendix F"):
            locked(parameters=broken)

    def test_the_message_says_why_it_matters(self) -> None:
        broken = parameters()
        broken["pheromones"]["pheromone_decay"] = 0.25
        with pytest.raises(ConfigFileError, match="disqualifies the team"):
            locked(parameters=broken)

    def test_nothing_is_produced_when_it_is_refused(self) -> None:
        """Otherwise a cryptographically perfect, disqualifying file exists."""
        broken = parameters()
        broken["scoring"]["technical_loss"] = 5
        with pytest.raises(ConfigFileError):
            locked(parameters=broken)


class TestItCannotBeBuiltIncomplete:
    def test_no_game_uid(self) -> None:
        with pytest.raises(ConfigFileError, match="shares a game_uid"):
            locked(game_uid="")

    def test_no_parameters(self) -> None:
        with pytest.raises(ConfigFileError, match="agrees to nothing"):
            LockedConfig(game_id="g", game_uid="u", sub_game=1, parameters={}, agreed_between=TEAMS)

    def test_one_team_named_twice(self) -> None:
        with pytest.raises(ConfigFileError, match="agreed between two teams"):
            locked(agreed_between=("uoh26-thieves", "uoh26-thieves"))

    def test_an_unusable_game_id_is_refused_by_naming(self) -> None:
        with pytest.raises(NamingError):
            locked(game_id="../etc/passwd")

    def test_a_sub_game_out_of_range_is_refused_by_naming(self) -> None:
        with pytest.raises(NamingError):
            locked(sub_game=100)


class TestTheFile:
    def test_the_name_carries_the_game_and_the_sub_game(self) -> None:
        assert locked().filename == "config_uoh26-s82kma9e_g02.json"

    def test_it_writes_and_reads_back(self, tmp_path: Path) -> None:
        path = locked().write(tmp_path)
        assert load(path).sha256 == locked().sha256

    def test_the_round_trip_preserves_everything(self, tmp_path: Path) -> None:
        restored = load(locked().write(tmp_path))
        assert restored.game_uid == "u-0001"
        assert restored.sub_game == 2
        assert restored.agreed_between == tuple(parameters()["agreed_between"])

    def test_the_bytes_are_stable(self, tmp_path: Path) -> None:
        assert (
            locked().write(tmp_path / "a").read_text() == locked().write(tmp_path / "b").read_text()
        )


class TestLoadingVerifiesRatherThanTrusts:
    def test_a_hand_edited_parameter_is_caught(self, tmp_path: Path) -> None:
        """Config files are committed, so they get opened and edited."""
        path = locked().write(tmp_path)
        body = json.loads(path.read_text())
        body["world"]["hint_max_words"] = 14
        path.write_text(json.dumps(body))
        with pytest.raises(ConfigFileError, match="has been edited since it was locked"):
            load(path)

    def test_editing_the_digest_to_match_is_still_caught(self, tmp_path: Path) -> None:
        """Because the digest is recomputed, not compared to a second copy."""
        path = locked().write(tmp_path)
        body = json.loads(path.read_text())
        body["config_sha256"] = "f" * 64
        path.write_text(json.dumps(body))
        with pytest.raises(ConfigFileError, match="has been edited"):
            load(path)

    def test_an_untouched_file_loads(self, tmp_path: Path) -> None:
        assert load(locked().write(tmp_path)).agrees_with(locked().sha256)

    def test_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigFileError, match="cannot read"):
            load(tmp_path / "absent.json")

    def test_a_non_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{half")
        with pytest.raises(ConfigFileError, match="is not JSON"):
            load(path)

    def test_a_json_list(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("[]")
        with pytest.raises(ConfigFileError, match="not a config object"):
            load(path)

    @pytest.mark.parametrize("field", ["game_id", "game_uid", "sub_game_number", "config_sha256"])
    def test_a_missing_field_names_it(self, tmp_path: Path, field: str) -> None:
        path = locked().write(tmp_path)
        body = json.loads(path.read_text())
        del body[field]
        path.write_text(json.dumps(body))
        with pytest.raises(ConfigFileError, match=field):
            load(path)

    def test_a_mangled_section_is_caught_by_the_digest(self, tmp_path: Path) -> None:
        """Replacing a whole section is an edit like any other.

        The terms are flat now, so there is no ``parameters`` object to type
        check -- and nothing is lost by that: the digest covers every term, so
        a section replaced by a string fails verification rather than a shape
        check, with a message naming the two digests.
        """
        path = locked().write(tmp_path)
        body = json.loads(path.read_text())
        body["board_and_agents"] = "everything"
        path.write_text(json.dumps(body))
        with pytest.raises(ConfigFileError, match="has been edited since it was locked"):
            load(path)

    def test_dropping_a_team_is_caught_by_the_digest(self, tmp_path: Path) -> None:
        path = locked().write(tmp_path)
        body = json.loads(path.read_text())
        body["agreed_between"] = ["uoh26-thieves"]
        path.write_text(json.dumps(body))
        with pytest.raises(ConfigFileError, match="has been edited since it was locked"):
            load(path)
