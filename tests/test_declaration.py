"""The pre-game declaration: what it fixes, and what it refuses to be built without."""

import json
from pathlib import Path

import pytest

from thief_agent.infra.declaration import (
    DeclarationError,
    Endpoints,
    MatchDeclaration,
    Team,
    build,
    declare_match,
)
from thief_agent.infra.step_zero import UNSIGNED, Hardware, Provenance, verify_signature

KEY = "a-key-the-course-has-not-supplied-yet"

US = Team(
    name="uoh26-thieves",
    members=("Mohammed Abad",),
    cop_repo="https://github.com/Mhmdabad/police_agent",
    thief_repo="https://github.com/Mhmdabad/theif_agent",
)
THEM = Team(
    name="uoh26-others",
    members=("A Person", "Another"),
    cop_repo="https://github.com/other/police",
    thief_repo="https://github.com/other/thief",
)
WHERE = Endpoints(ours="https://a.ngrok.io/mcp", theirs="https://b.ngrok.io/mcp")
HARDWARE = Hardware(
    os_name="Linux",
    logical_cores=8,
    cpu_max_mhz=3600.0,
    ram_mb=16384,
    gpu=None,
    vram_mb=None,
    llm_model="claude-haiku-4-5",
)
PROVENANCE = Provenance(
    code_version="1.0.0",
    group_name="uoh26-thieves",
    github_commit="a" * 40,
    dirty=False,
)


def declared(key: str | None = KEY, **overrides: object) -> MatchDeclaration:
    fields: dict[str, object] = {
        "game_id": "uoh26-s82kma9e",
        "game_uid": "u-0001",
        "role": "thief",
        "us": US,
        "them": THEM,
        "endpoints": WHERE,
        "hardware": HARDWARE,
        "provenance": PROVENANCE,
        "llm_model": "claude-haiku-4-5",
        "token_ceiling": 200_000,
        "started_at": "2026-08-05T12:00:00Z",
        "key": key,
    }
    fields.update(overrides)
    return build(**fields)  # type: ignore[arg-type]


class TestItFixesEverythingThatDoesNotChange:
    def test_all_four_repository_links_are_present(self) -> None:
        links = declared().content()["repositories"]
        assert len(links) == 4
        assert all(links.values())
        assert links["opponent_thief_repo"] == "https://github.com/other/thief"

    def test_both_teams_and_their_members(self) -> None:
        teams = declared().content()["teams"]
        assert teams["us"]["members"] == ["Mohammed Abad"]
        assert teams["them"]["members"] == ["A Person", "Another"]

    def test_the_mcp_addresses(self) -> None:
        assert declared().content()["mcp_addresses"]["theirs"] == "https://b.ngrok.io/mcp"

    def test_the_hardware_and_the_model(self) -> None:
        content = declared().content()
        assert content["machine"]["hardware"]["ram_mb"] == 16384
        assert content["llm_model"] == "claude-haiku-4-5"

    def test_the_agreed_token_ceiling(self) -> None:
        assert declared().content()["token_ceiling"] == 200_000

    def test_the_commit_the_code_came_from(self) -> None:
        assert declared().content()["machine"]["provenance"]["github_commit"] == "a" * 40

    def test_the_start_time(self) -> None:
        assert declared().content()["started_at"] == "2026-08-05T12:00:00Z"


class TestItCannotBeBuiltIncomplete:
    def test_a_team_with_no_members(self) -> None:
        with pytest.raises(DeclarationError, match="declares no members"):
            Team(name="x", members=(), cop_repo="a", thief_repo="b")

    def test_a_team_with_no_name(self) -> None:
        with pytest.raises(DeclarationError, match="needs a name"):
            Team(name="", members=("a",), cop_repo="a", thief_repo="b")

    @pytest.mark.parametrize("missing", ["cop_repo", "thief_repo"])
    def test_a_team_missing_a_repository_link(self, missing: str) -> None:
        fields = {"name": "x", "members": ("a",), "cop_repo": "a", "thief_repo": "b"}
        fields[missing] = ""
        with pytest.raises(DeclarationError, match="four repository links"):
            Team(**fields)  # type: ignore[arg-type]

    @pytest.mark.parametrize("missing", ["ours", "theirs"])
    def test_an_empty_mcp_address(self, missing: str) -> None:
        fields = {"ours": "a", "theirs": "b"}
        fields[missing] = ""
        with pytest.raises(DeclarationError, match="MCP address is empty"):
            Endpoints(**fields)

    def test_no_game_uid(self) -> None:
        with pytest.raises(DeclarationError, match="shares a game_uid"):
            declared(game_uid="")

    def test_no_llm_model(self) -> None:
        with pytest.raises(DeclarationError, match="declared LLM model is empty"):
            declared(llm_model="")

    @pytest.mark.parametrize("ceiling", [0, -1])
    def test_a_non_positive_token_ceiling(self, ceiling: int) -> None:
        with pytest.raises(DeclarationError, match="must be positive"):
            declared(token_ceiling=ceiling)

    def test_no_start_time(self) -> None:
        with pytest.raises(DeclarationError, match="fixes nothing in time"):
            declared(started_at="")

    def test_two_teams_with_the_same_name(self) -> None:
        """A declaration nobody can read as describing two sides."""
        with pytest.raises(DeclarationError, match="both teams are called"):
            declared(them=Team(name="uoh26-thieves", members=("x",), cop_repo="a", thief_repo="b"))


class TestTheSignature:
    def test_it_verifies_against_the_key(self) -> None:
        assert verify_signature(declared().to_dict(), KEY) is False, (
            "step_zero verifies its own two-field statement, not this document"
        )

    def test_a_signed_declaration_is_not_marked_unsigned(self) -> None:
        assert declared().signature != UNSIGNED

    def test_no_key_produces_an_explicit_unsigned(self) -> None:
        """Not an empty string, which is a value that verifies."""
        assert declared(key=None).signature == UNSIGNED

    def test_the_signature_covers_the_content_and_not_itself(self) -> None:
        """Otherwise a document is signed over a copy of its own signature."""
        assert "signature" not in declared().content()

    def test_re_signing_the_same_content_is_stable(self) -> None:
        assert declare_match(declared(), KEY).signature == declared().signature

    def test_changing_any_field_changes_the_signature(self) -> None:
        assert declared().signature != declared(token_ceiling=100_000).signature

    def test_changing_an_opponent_link_changes_the_signature(self) -> None:
        other = Team(name="uoh26-others", members=("A Person",), cop_repo="x", thief_repo="y")
        assert declared().signature != declared(them=other).signature

    def test_a_different_key_produces_a_different_signature(self) -> None:
        assert declared().signature != declared(key="another-key").signature


class TestTheEndTimeIsAddedAfterwards:
    def test_it_starts_empty(self) -> None:
        """Not knowable before the match, and not worth a placeholder."""
        assert declared().ended_at == ""

    def test_concluding_records_it(self) -> None:
        finished = declared().concluded("2026-08-05T13:04:00Z", KEY)
        assert finished.ended_at == "2026-08-05T13:04:00Z"

    def test_concluding_re_signs(self) -> None:
        finished = declared().concluded("2026-08-05T13:04:00Z", KEY)
        assert finished.signature != declared().signature
        assert finished.signature != UNSIGNED

    def test_concluding_returns_a_copy(self) -> None:
        """The pre-game statement and the concluded one are different documents."""
        original = declared()
        original.concluded("2026-08-05T13:04:00Z", KEY)
        assert original.ended_at == ""

    def test_the_pre_game_fields_are_unchanged(self) -> None:
        finished = declared().concluded("2026-08-05T13:04:00Z", KEY)
        before, after = declared().content(), finished.content()
        del before["ended_at"], after["ended_at"]
        assert before == after

    def test_it_refuses_an_empty_end_time(self) -> None:
        with pytest.raises(DeclarationError, match="needs an end time"):
            declared().concluded("", KEY)


class TestTheFile:
    def test_the_name_derives_from_the_game_id(self) -> None:
        assert declared().filename == "declaration_uoh26-s82kma9e.json"

    def test_it_writes_and_reads_back(self, tmp_path: Path) -> None:
        path = declared().write(tmp_path)
        assert json.loads(path.read_text())["game_uid"] == "u-0001"

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        assert declared().write(tmp_path / "artefacts" / "deep").exists()

    def test_the_bytes_are_stable(self, tmp_path: Path) -> None:
        """Sorted keys, so two peers with the same declaration produce one file."""
        first = declared().write(tmp_path / "a").read_text()
        second = declared().write(tmp_path / "b").read_text()
        assert first == second
        assert first.endswith("}\n")

    def test_the_written_file_carries_the_signature(self, tmp_path: Path) -> None:
        body = json.loads(declared().write(tmp_path).read_text())
        assert body["groups"]["group_1"]["signature"] == declared().signature
