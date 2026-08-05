"""What a stored credential must satisfy before this agent will use it."""

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.gmail_auth import SEND_SCOPE
from thief_agent.infra.token_store import (
    TOKEN_PATH_ENV,
    StoredToken,
    TokenError,
    read,
    save,
    token_path,
)

CLIENT = "1234567890-abcdef.apps.googleusercontent.com"
OTHER = "9999999999-zzzzzz.apps.googleusercontent.com"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

GOOD: dict[str, Any] = {
    "client_id": CLIENT,
    "refresh_token": "1//refresh-not-real",
    "token": "ya29.access-not-real",
    "scopes": [SEND_SCOPE],
    "expiry": "2099-01-01T00:00:00Z",
}


def stored(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "token_thief.json"
    path.write_text(json.dumps({**GOOD, **overrides}))
    return path


class TestWhereTheTokenLives:
    def test_it_is_named_per_agent_not_token_json(self) -> None:
        """Two files called token.json in sibling directories invite a copy."""
        assert token_path("thief_agent", {}).name == "token_thief.json"
        assert token_path("thief_agent", {}).name == "token_thief.json"

    def test_the_environment_overrides_it(self) -> None:
        chosen = token_path("thief_agent", {TOKEN_PATH_ENV: "/secure/elsewhere.json"})
        assert chosen == Path("/secure/elsewhere.json")

    def test_it_reads_the_real_environment_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TOKEN_PATH_ENV, "/tmp/from-env.json")
        assert token_path("thief_agent") == Path("/tmp/from-env.json")


class TestAGoodTokenLoads:
    def test_it_returns_the_refresh_token_and_scopes(self, tmp_path: Path) -> None:
        token = read(stored(tmp_path), CLIENT)
        assert token.refresh_token == GOOD["refresh_token"]
        assert token.scopes == (SEND_SCOPE,)

    def test_a_future_expiry_is_not_expired(self, tmp_path: Path) -> None:
        assert not read(stored(tmp_path), CLIENT).expired

    def test_a_past_expiry_is_expired_and_that_is_fine(self, tmp_path: Path) -> None:
        """An expired access token is the ordinary case — it means refresh."""
        past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        token = read(stored(tmp_path, expiry=past), CLIENT)
        assert token.expired
        assert token.refresh_token

    def test_a_naive_expiry_is_read_as_utc(self, tmp_path: Path) -> None:
        assert not read(stored(tmp_path, expiry="2099-01-01T00:00:00"), CLIENT).expired

    @pytest.mark.parametrize("value", ["not a date", 17, None])
    def test_an_unreadable_expiry_is_unknown_rather_than_fatal(
        self, tmp_path: Path, value: object
    ) -> None:
        """One wasted refresh beats one lost report."""
        token = read(stored(tmp_path, expiry=value), CLIENT)
        assert token.expiry is None
        assert not token.expired

    def test_the_summary_does_not_contain_the_refresh_token(self, tmp_path: Path) -> None:
        token = read(stored(tmp_path), CLIENT)
        assert GOOD["refresh_token"] not in token.summary
        assert "current" in token.summary


class TestTheThreeRefusals:
    def test_an_over_scoped_token_is_refused(self, tmp_path: Path) -> None:
        """Delegated to check_granted, so there is one rule about scope."""
        with pytest.raises(TokenError, match="will not hold"):
            read(stored(tmp_path, scopes=[SEND_SCOPE, READ_SCOPE]), CLIENT)

    def test_a_token_with_no_refresh_token_is_refused(self, tmp_path: Path) -> None:
        """Usable for an hour, then dead at whatever moment that hour ends."""
        with pytest.raises(TokenError, match="stops working within the hour"):
            read(stored(tmp_path, refresh_token=""), CLIENT)

    def test_the_refresh_less_message_explains_why_it_happened(self, tmp_path: Path) -> None:
        """Google omits it when the client was authorised before — so it is confusing."""
        body = {k: v for k, v in GOOD.items() if k != "refresh_token"}
        path = tmp_path / "token_thief.json"
        path.write_text(json.dumps(body))
        with pytest.raises(TokenError, match="authorised before"):
            read(path, CLIENT)

    def test_a_token_from_another_client_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(TokenError, match="different client"):
            read(stored(tmp_path, client_id=OTHER), CLIENT)

    def test_the_foreign_client_message_names_the_likely_cause(self, tmp_path: Path) -> None:
        """Copying one agent's token to the other is the way this happens."""
        with pytest.raises(TokenError, match="copied between the two"):
            read(stored(tmp_path, client_id=OTHER), CLIENT)


class TestEveryRefusalSaysHowToFixIt:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"scopes": [SEND_SCOPE, READ_SCOPE]},
            {"refresh_token": ""},
            {"client_id": OTHER},
        ],
    )
    def test_it_names_the_command_to_run(self, tmp_path: Path, overrides: dict[str, Any]) -> None:
        with pytest.raises(TokenError, match="infra.authorize"):
            read(stored(tmp_path, **overrides), CLIENT)

    def test_it_warns_about_the_seven_day_expiry(self, tmp_path: Path) -> None:
        """The failure code cannot prevent, so the message carries it instead."""
        with pytest.raises(TokenError, match="seven days"):
            read(tmp_path / "token_thief.json", CLIENT)

    def test_the_module_named_matches_the_package(self, tmp_path: Path) -> None:
        with pytest.raises(TokenError, match="thief_agent.infra.authorize"):
            read(tmp_path / "token_thief.json", CLIENT, package="thief_agent")


class TestItRefusesWhatItCannotRead:
    def test_a_missing_file_is_a_token_error(self, tmp_path: Path) -> None:
        with pytest.raises(TokenError, match="no token_thief.json"):
            read(tmp_path / "token_thief.json", CLIENT)

    def test_a_directory_is_a_token_error_not_a_crash(self, tmp_path: Path) -> None:
        (tmp_path / "token_thief.json").mkdir()
        with pytest.raises(TokenError, match="cannot read"):
            read(tmp_path / "token_thief.json", CLIENT)

    def test_a_non_json_file_is_a_token_error(self, tmp_path: Path) -> None:
        path = tmp_path / "token_thief.json"
        path.write_text("half a fi")
        with pytest.raises(TokenError, match="is not JSON"):
            read(path, CLIENT)

    def test_a_json_list_is_a_token_error(self, tmp_path: Path) -> None:
        path = tmp_path / "token_thief.json"
        path.write_text("[]")
        with pytest.raises(TokenError, match="not a token object"):
            read(path, CLIENT)

    def test_a_missing_scope_field_is_a_token_error(self, tmp_path: Path) -> None:
        body = {k: v for k, v in GOOD.items() if k != "scopes"}
        path = tmp_path / "token_thief.json"
        path.write_text(json.dumps(body))
        with pytest.raises(TokenError, match="expected a list of scope strings"):
            read(path, CLIENT)

    def test_a_space_separated_scope_field_is_accepted(self, tmp_path: Path) -> None:
        """Some libraries write 'scope' as a string rather than 'scopes' as a list."""
        body = {k: v for k, v in GOOD.items() if k != "scopes"} | {"scope": SEND_SCOPE}
        path = tmp_path / "token_thief.json"
        path.write_text(json.dumps(body))
        assert read(path, CLIENT).scopes == (SEND_SCOPE,)


class TestSaving:
    def test_it_round_trips_through_read(self, tmp_path: Path) -> None:
        path = save(tmp_path / "token_thief.json", GOOD)
        assert read(path, CLIENT).refresh_token == GOOD["refresh_token"]

    def test_the_file_is_readable_only_by_its_owner(self, tmp_path: Path) -> None:
        """A refresh token readable by every account on a shared machine."""
        path = save(tmp_path / "token_thief.json", GOOD)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_an_existing_world_readable_file_is_narrowed(self, tmp_path: Path) -> None:
        """Overwriting must not inherit permissions from what was there before."""
        path = tmp_path / "token_thief.json"
        path.write_text("{}")
        path.chmod(0o644)
        save(path, GOOD)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        path = save(tmp_path / "nested" / "deeper" / "token_thief.json", GOOD)
        assert path.exists()

    def test_it_truncates_rather_than_appending(self, tmp_path: Path) -> None:
        path = tmp_path / "token_thief.json"
        path.write_text(json.dumps({**GOOD, "refresh_token": "old"}) + "\n" * 200)
        save(path, GOOD)
        assert json.loads(path.read_text())["refresh_token"] == GOOD["refresh_token"]


class TestTheStoredTokenObject:
    def test_a_token_with_no_expiry_is_not_expired(self) -> None:
        token = StoredToken(client_id=CLIENT, refresh_token="r", scopes=(SEND_SCOPE,))
        assert not token.expired
        assert "current" in token.summary

    def test_an_expired_token_says_so_in_its_summary(self) -> None:
        token = StoredToken(
            client_id=CLIENT,
            refresh_token="r",
            scopes=(SEND_SCOPE,),
            expiry=datetime(2000, 1, 1, tzinfo=UTC),
        )
        assert "expired" in token.summary
