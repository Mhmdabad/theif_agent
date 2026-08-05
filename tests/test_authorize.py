"""The authorization flow, with the browser replaced by a seam."""

import json
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from thief_agent.infra.authorize import Runner, authorize, google_flow, main
from thief_agent.infra.credentials import CREDENTIALS_FILE, CredentialsError
from thief_agent.infra.gmail_auth import SEND_SCOPE
from thief_agent.infra.token_store import TokenError, read

CLIENT = "1234567890-abcdef.apps.googleusercontent.com"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

DESKTOP: dict[str, Any] = {
    "installed": {
        "client_id": CLIENT,
        "project_id": "uoh26-cops-and-robbers",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_secret": "GOCSPX-not-a-real-secret",
    }
}

GRANTED: dict[str, Any] = {
    "client_id": CLIENT,
    "refresh_token": "1//refresh-not-real",
    "token": "ya29.access-not-real",
    "scopes": [SEND_SCOPE],
    "expiry": "2099-01-01T00:00:00Z",
}


def client_file(tmp_path: Path, body: object = DESKTOP) -> Path:
    path = tmp_path / CREDENTIALS_FILE
    path.write_text(json.dumps(body))
    return path


def returning(body: object, seen: list[Any] | None = None) -> Runner:
    """A stand-in for the browser flow, recording what it was handed."""

    def runner(client: dict[str, Any], scopes: Sequence[str]) -> dict[str, Any]:
        if seen is not None:
            seen.append((client, tuple(scopes)))
        return cast("dict[str, Any]", body)

    return runner


class TestTheHappyPath:
    def test_it_writes_a_token_the_store_will_accept(self, tmp_path: Path) -> None:
        """The two halves have to agree, or neither is worth having."""
        written = authorize(client_file(tmp_path), tmp_path / "t.json", returning(GRANTED))
        assert read(written, CLIENT).refresh_token == GRANTED["refresh_token"]

    def test_the_written_file_is_owner_only(self, tmp_path: Path) -> None:
        written = authorize(client_file(tmp_path), tmp_path / "t.json", returning(GRANTED))
        assert stat.S_IMODE(written.stat().st_mode) == 0o600

    def test_it_asks_only_for_the_send_scope(self, tmp_path: Path) -> None:
        seen: list[Any] = []
        authorize(client_file(tmp_path), tmp_path / "t.json", returning(GRANTED, seen))
        assert seen[0][1] == (SEND_SCOPE,)

    def test_it_hands_the_flow_the_installed_section(self, tmp_path: Path) -> None:
        seen: list[Any] = []
        authorize(client_file(tmp_path), tmp_path / "t.json", returning(GRANTED, seen))
        assert seen[0][0] == DESKTOP["installed"]


class TestTheClientIsCheckedBeforeTheBrowserOpens:
    def test_a_web_client_is_refused_without_running_the_flow(self, tmp_path: Path) -> None:
        """Otherwise somebody approves consent for a client that cannot work."""
        seen: list[Any] = []
        with pytest.raises(CredentialsError, match="Web application"):
            authorize(
                client_file(tmp_path, {"web": DESKTOP["installed"]}),
                tmp_path / "t.json",
                returning(GRANTED, seen),
            )
        assert seen == [], "the flow ran before the client file was judged"

    def test_a_missing_client_file_is_refused_without_running_the_flow(
        self, tmp_path: Path
    ) -> None:
        seen: list[Any] = []
        with pytest.raises(CredentialsError):
            authorize(tmp_path / CREDENTIALS_FILE, tmp_path / "t.json", returning(GRANTED, seen))
        assert seen == []


class TestWhatComesBackIsJudgedToo:
    def test_an_over_scoped_grant_is_refused(self, tmp_path: Path) -> None:
        wider = {**GRANTED, "scopes": [SEND_SCOPE, READ_SCOPE]}
        with pytest.raises(TokenError, match="granted more than this agent asked for"):
            authorize(client_file(tmp_path), tmp_path / "t.json", returning(wider))

    def test_a_grant_with_no_refresh_token_is_refused(self, tmp_path: Path) -> None:
        without = {k: v for k, v in GRANTED.items() if k != "refresh_token"}
        with pytest.raises(TokenError, match="no refresh token"):
            authorize(client_file(tmp_path), tmp_path / "t.json", returning(without))

    def test_the_refresh_less_message_says_to_revoke(self, tmp_path: Path) -> None:
        without = {**GRANTED, "refresh_token": ""}
        with pytest.raises(TokenError, match="myaccount.google.com/permissions"):
            authorize(client_file(tmp_path), tmp_path / "t.json", returning(without))

    def test_a_flow_returning_something_that_is_not_a_credential(self, tmp_path: Path) -> None:
        with pytest.raises(TokenError, match="not a credential"):
            authorize(client_file(tmp_path), tmp_path / "t.json", returning("ok"))

    @pytest.mark.parametrize(
        "body",
        [
            {**GRANTED, "scopes": [SEND_SCOPE, READ_SCOPE]},
            {**GRANTED, "refresh_token": ""},
            "not a credential",
        ],
    )
    def test_nothing_is_written_when_the_grant_is_refused(
        self, tmp_path: Path, body: object
    ) -> None:
        """A refusal after the flow is not too late — the file is what matters."""
        destination = tmp_path / "t.json"
        with pytest.raises(TokenError):
            authorize(client_file(tmp_path), destination, returning(body))
        assert not destination.exists()


class TestTheRealFlowIsWiredCorrectly:
    """Exercised with the library's own entry point replaced, so no browser opens."""

    def test_it_wraps_the_client_in_installed_and_passes_the_scopes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        class FakeCredentials:
            @staticmethod
            def to_json() -> str:
                return json.dumps(GRANTED)

        class FakeFlow:
            @staticmethod
            def from_client_config(config: dict[str, Any], scopes: list[str]) -> "FakeFlow":
                seen["config"], seen["scopes"] = config, scopes
                return FakeFlow()

            @staticmethod
            def run_local_server(port: int) -> FakeCredentials:
                seen["port"] = port
                return FakeCredentials()

        module = pytest.importorskip("google_auth_oauthlib.flow")
        monkeypatch.setattr(module, "InstalledAppFlow", FakeFlow)

        body = google_flow(DESKTOP["installed"], [SEND_SCOPE])
        assert body == GRANTED
        assert seen["config"] == {"installed": DESKTOP["installed"]}
        assert seen["scopes"] == [SEND_SCOPE]
        assert seen["port"] == 0, "an ephemeral port, so two agents can authorize at once"


class TestTheRunnerIsResolvedAtCallTimeNotImportTime:
    """A regression test for a hang, not a style preference.

    ``runner: Runner = google_flow`` in the signature binds the default once,
    when the module is imported. Substituting the module attribute afterwards
    then changes nothing, and ``main()`` calls the real flow — which opens a
    browser and blocks forever on a local callback server. In a suite that is
    supposed to touch no network, the symptom is a test run that never ends.
    """

    def test_substituting_the_module_attribute_takes_effect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Any] = []
        monkeypatch.setattr("thief_agent.infra.authorize.google_flow", returning(GRANTED, seen))
        authorize(client_file(tmp_path), tmp_path / "t.json")
        assert seen, "the default was captured at import time and the real flow ran"

    def test_an_explicit_runner_still_wins(self, tmp_path: Path) -> None:
        seen: list[Any] = []
        authorize(client_file(tmp_path), tmp_path / "t.json", returning(GRANTED, seen))
        assert len(seen) == 1


class TestTheCommandLine:
    def test_a_successful_run_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        client_file(tmp_path)
        monkeypatch.setattr(
            "thief_agent.infra.authorize.google_flow", returning(GRANTED), raising=True
        )
        assert main([str(tmp_path / CREDENTIALS_FILE)]) == 0

    def test_a_failure_exits_one_rather_than_raising(self, tmp_path: Path) -> None:
        """A traceback at a setup step tells a person nothing they can act on."""
        assert main([str(tmp_path / "absent.json")]) == 1

    def test_it_defaults_to_credentials_json_in_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert main([]) == 1, "no credentials.json here, so it should fail cleanly"

    def test_it_reads_sys_argv_when_given_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["authorize", str(tmp_path / "absent.json")])
        assert main() == 1

    def test_the_failure_is_reported_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main([str(tmp_path / "absent.json")])
        assert "authorization failed" in capsys.readouterr().err
