"""Reading the client file, and proving git really does ignore the secrets."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.credentials import (
    CREDENTIALS_FILE,
    ClientInfo,
    CredentialsError,
    load,
)

REPO = Path(__file__).resolve().parent.parent

DESKTOP: dict[str, Any] = {
    "installed": {
        "client_id": "1234567890-abcdef.apps.googleusercontent.com",
        "project_id": "uoh26-cops-and-robbers",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_secret": "GOCSPX-not-a-real-secret",
        "redirect_uris": ["http://localhost"],
    }
}

WEB: dict[str, Any] = {"web": dict(DESKTOP["installed"])}


def written(tmp_path: Path, body: object, name: str = CREDENTIALS_FILE) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(body))
    return path


class TestADesktopClientLoads:
    def test_it_returns_the_client_id_and_project(self, tmp_path: Path) -> None:
        info, _ = load(written(tmp_path, DESKTOP))
        assert info.client_id == DESKTOP["installed"]["client_id"]
        assert info.project_id == "uoh26-cops-and-robbers"

    def test_it_returns_the_installed_section_for_the_flow(self, tmp_path: Path) -> None:
        _, section = load(written(tmp_path, DESKTOP))
        assert section == DESKTOP["installed"]

    def test_a_missing_project_id_is_not_fatal(self, tmp_path: Path) -> None:
        """Older downloads omit it. It is for diagnosis, not for the flow."""
        body = {"installed": {k: v for k, v in DESKTOP["installed"].items() if k != "project_id"}}
        info, _ = load(written(tmp_path, body))
        assert info.project_id == ""


class TestTheSecretDoesNotLeakIntoAnythingPrintable:
    def test_the_client_info_has_no_secret_field(self, tmp_path: Path) -> None:
        info, _ = load(written(tmp_path, DESKTOP))
        assert "client_secret" not in repr(info)
        assert DESKTOP["installed"]["client_secret"] not in repr(info)

    def test_the_summary_names_the_project_without_the_secret(self, tmp_path: Path) -> None:
        """The wrong-project mistake from step 1 is what this line is for."""
        info, _ = load(written(tmp_path, DESKTOP))
        assert "uoh26-cops-and-robbers" in info.summary
        assert DESKTOP["installed"]["client_secret"] not in info.summary

    def test_an_unnamed_project_still_reads_as_a_sentence(self) -> None:
        assert "an unnamed project" in ClientInfo(client_id="abc.apps").summary

    def test_no_error_message_quotes_the_secret(self, tmp_path: Path) -> None:
        """Errors get pasted into chat windows and issue trackers."""
        broken = {"installed": {**DESKTOP["installed"], "token_uri": ""}}
        with pytest.raises(CredentialsError) as raised:
            load(written(tmp_path, broken))
        assert DESKTOP["installed"]["client_secret"] not in str(raised.value)


class TestTheWrongClientTypeIsNamedAtLoadTime:
    def test_a_web_client_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CredentialsError, match="Web application"):
            load(written(tmp_path, WEB))

    def test_the_message_names_the_error_it_would_otherwise_cause(self, tmp_path: Path) -> None:
        """redirect_uri_mismatch names a URI nobody configured. That is the trap."""
        with pytest.raises(CredentialsError, match="redirect_uri_mismatch"):
            load(written(tmp_path, WEB))

    def test_the_message_says_editing_redirect_uris_will_not_help(self, tmp_path: Path) -> None:
        """Otherwise the obvious response to the error is an hour in the console."""
        with pytest.raises(CredentialsError, match="no amount of"):
            load(written(tmp_path, WEB))

    def test_a_service_account_key_is_refused_and_explained(self, tmp_path: Path) -> None:
        key = {"type": "service_account", "project_id": "x", "private_key": "-----BEGIN"}
        with pytest.raises(CredentialsError, match="service-account key"):
            load(written(tmp_path, key))


class TestItRefusesWhatItCannotUse:
    def test_a_missing_file_says_where_to_get_one(self, tmp_path: Path) -> None:
        with pytest.raises(CredentialsError, match="Desktop app"):
            load(tmp_path / CREDENTIALS_FILE)

    def test_a_missing_file_points_at_the_runbook(self, tmp_path: Path) -> None:
        with pytest.raises(CredentialsError, match="GMAIL_SETUP.md"):
            load(tmp_path / CREDENTIALS_FILE)

    def test_a_directory_in_place_of_the_file_is_an_error_not_a_crash(self, tmp_path: Path) -> None:
        (tmp_path / CREDENTIALS_FILE).mkdir()
        with pytest.raises(CredentialsError, match="cannot read"):
            load(tmp_path / CREDENTIALS_FILE)

    def test_a_non_json_file_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / CREDENTIALS_FILE
        path.write_text("<html>sign in to download</html>")
        with pytest.raises(CredentialsError, match="is not JSON"):
            load(path)

    def test_a_json_list_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CredentialsError, match="not a credentials object"):
            load(written(tmp_path, [DESKTOP]))

    def test_an_installed_section_that_is_not_an_object_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CredentialsError, match="not an object"):
            load(written(tmp_path, {"installed": "yes"}))

    @pytest.mark.parametrize("field", ["client_id", "client_secret", "auth_uri", "token_uri"])
    def test_a_missing_required_field_names_it(self, tmp_path: Path, field: str) -> None:
        body = {"installed": {k: v for k, v in DESKTOP["installed"].items() if k != field}}
        with pytest.raises(CredentialsError, match=field):
            load(written(tmp_path, body))

    def test_an_emptied_field_counts_as_missing(self, tmp_path: Path) -> None:
        """A hand-edited file that blanked a value, rather than removing it."""
        body = {"installed": {**DESKTOP["installed"], "client_id": ""}}
        with pytest.raises(CredentialsError, match="client_id"):
            load(written(tmp_path, body))

    def test_it_says_to_re_download_rather_than_edit(self, tmp_path: Path) -> None:
        body = {"installed": {**DESKTOP["installed"], "auth_uri": ""}}
        with pytest.raises(CredentialsError, match="re-download it rather than editing"):
            load(written(tmp_path, body))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
class TestGitReallyIgnoresTheSecrets:
    """FR-7.27, checked rather than trusted.

    ``.gitignore`` containing a line is not the same fact as git ignoring the
    file: a pattern can be shadowed by a later negation, and a file already
    tracked stays tracked no matter what the ignore file says. Both have
    happened to other people, both are silent, and a secret pushed even once is
    compromised permanently — deleting it later does not remove it from history.

    So this asks **git**, in this repository, on every CI run.
    """

    @staticmethod
    def ignored(name: str) -> bool:
        return (
            subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO, check=False).returncode
            == 0
        )

    @staticmethod
    def tracked(name: str) -> list[str]:
        listed = subprocess.run(
            ["git", "ls-files", "--", name], cwd=REPO, capture_output=True, text=True, check=False
        )
        return [line for line in listed.stdout.splitlines() if line]

    @pytest.mark.parametrize(
        "name",
        [
            "credentials.json",
            "token.json",
            "token_thief.json",
            "client_secret_1234.apps.googleusercontent.com.json",
            ".env",
        ],
    )
    def test_git_ignores_it(self, name: str) -> None:
        assert self.ignored(name), f"git does not ignore {name}; FR-7.27 requires it"

    @pytest.mark.parametrize("name", ["credentials.json", "token.json", ".env"])
    def test_git_is_not_already_tracking_it(self, name: str) -> None:
        """An ignore rule does nothing for a file that is already tracked."""
        assert self.tracked(name) == []

    def test_no_secret_looking_file_is_tracked_anywhere_in_the_tree(self) -> None:
        listed = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
        )
        suspects = [
            line
            for line in listed.stdout.splitlines()
            if Path(line).name in {"credentials.json", "token.json", ".env"}
            or Path(line).name.startswith("client_secret")
        ]
        assert suspects == [], f"secrets are tracked: {suspects}"

    def test_the_match_log_is_deliberately_not_ignored(self) -> None:
        """The counter-check: a rule broad enough to swallow evidence is a bug too."""
        assert not self.ignored("log_uoh26-s82kma9e_g02.json")
