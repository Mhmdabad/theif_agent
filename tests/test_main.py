"""The command somebody actually types, and what it tells them before it binds."""

from collections.abc import Callable
from pathlib import Path

import pytest

from thief_agent.__main__ import CONFIG, StartupError, describe, load_private, main, where_we_are

REPO = Path(__file__).resolve().parent.parent
NO_TUNNEL: dict[str, str] = {}


NO_NGROK = None
"""No ngrok probe at all.

Passing ``None`` is how :func:`~thief_agent.infra.tunnel.discover` is told not to
look. Left at the default, these checks probe the real ngrok API on this
machine and pass or fail depending on whether a tunnel happens to be running —
a test that reports the developer's desktop rather than the code.
"""


def where_we_are_url(environ: dict[str, str]) -> str:
    return where_we_are(environ, NO_NGROK)


def private() -> dict[str, object]:
    return load_private(REPO / CONFIG)


class TestCheckReportsWithoutBinding:
    def test_it_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(REPO)
        assert main(["check"], environ=NO_TUNNEL) == 0

    def test_it_names_this_agent_and_its_role(self, capsys: pytest.CaptureFixture[str]) -> None:
        lines = describe(private(), NO_TUNNEL)
        assert lines[0] == "thief-agent (thief)"

    def test_it_reports_the_port_it_would_listen_on(self) -> None:
        assert "8802" in describe(private(), NO_TUNNEL)[1]

    def test_it_reports_the_opponent(self) -> None:
        assert "8801" in describe(private(), NO_TUNNEL)[3]

    def test_it_lists_the_four_tools(self) -> None:
        tools = describe(private(), NO_TUNNEL)[4]
        for name in ("negotiate", "receive_turn", "submit_audit", "receive_control"):
            assert name in tools

    def test_nothing_is_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The question is 'would this work', asked five minutes before a match."""
        monkeypatch.chdir(REPO)
        monkeypatch.setattr(
            "thief_agent.__main__.serve",
            lambda *_: pytest.fail("check must not start a server"),
        )
        assert main(["check"], environ=NO_TUNNEL) == 0


class TestWhereWeSayWeAre:
    def test_no_tunnel_is_reported_rather_than_refused(self) -> None:
        """Localhost is permitted while developing; refusing would block every run."""
        assert "not publicly reachable" in where_we_are(NO_TUNNEL, NO_NGROK)

    def test_the_warning_names_what_it_is_not_good_enough_for(self) -> None:
        assert "league match" in where_we_are(NO_TUNNEL, NO_NGROK)

    def test_a_public_url_is_used(self) -> None:
        assert (
            where_we_are_url({"PUBLIC_URL": "https://abc.ngrok.io"}) == "https://abc.ngrok.io/mcp"
        )

    def test_a_loopback_url_that_was_set_on_purpose_is_an_error(self) -> None:
        """Somebody set an address and got it wrong, which is worse than not setting one."""
        with pytest.raises(StartupError, match="unusable"):
            where_we_are_url({"PUBLIC_URL": "http://127.0.0.1:8801"})

    def test_the_error_explains_the_cost(self) -> None:
        with pytest.raises(StartupError, match="not reachable from another machine"):
            where_we_are_url({"PUBLIC_URL": "http://localhost:8801"})


class TestItFailsWithAReasonRatherThanATraceback:
    def test_a_missing_config_exits_one(self, tmp_path: Path) -> None:
        assert main(["check", "--config", str(tmp_path / "absent.toml")], environ=NO_TUNNEL) == 1

    def test_the_missing_config_message_says_where_to_run_it(self, tmp_path: Path) -> None:
        with pytest.raises(StartupError, match="repository root"):
            load_private(tmp_path / "absent.toml")

    def test_an_unreadable_config_is_named(self, tmp_path: Path) -> None:
        (tmp_path / "broken.toml").write_text("this is not = = toml")
        with pytest.raises(StartupError, match="cannot read"):
            load_private(tmp_path / "broken.toml")

    def test_a_directory_in_place_of_the_config(self, tmp_path: Path) -> None:
        (tmp_path / "dir.toml").mkdir()
        with pytest.raises(StartupError, match="cannot read"):
            load_private(tmp_path / "dir.toml")

    def test_a_config_with_no_network_section_exits_one(self, tmp_path: Path) -> None:
        (tmp_path / "thin.toml").write_text('version = "1.0"\n')
        assert main(["check", "--config", str(tmp_path / "thin.toml")], environ=NO_TUNNEL) == 1

    def test_the_failure_goes_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["check", "--config", str(tmp_path / "absent.toml")], environ=NO_TUNNEL)
        assert "cannot start" in capsys.readouterr().err

    def test_a_bad_public_url_stops_it_before_the_socket(self, tmp_path: Path) -> None:
        """The check runs first, so the failure is on our terminal not in their match."""
        assert main(["check"], environ={"PUBLIC_URL": "http://127.0.0.1:1"}) == 1


class TestServing:
    def test_it_starts_the_server_with_the_configured_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(REPO)
        started: list[object] = []
        monkeypatch.setattr(
            "thief_agent.__main__.serve", lambda host, settings: started.append(settings)
        )
        assert main([], environ=NO_TUNNEL) == 0
        assert len(started) == 1
        assert getattr(started[0], "port", None) == 8802

    def test_serve_is_the_default_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(REPO)
        started: list[object] = []
        monkeypatch.setattr("thief_agent.__main__.serve", lambda *_: started.append(True))
        main([], environ=NO_TUNNEL)
        assert started, "no argument should mean serve"

    def test_it_reads_the_real_environment_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(REPO)
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        monkeypatch.setattr("thief_agent.__main__.serve", lambda *_: None)
        assert main([]) == 0


def record_play(seen: list[object]) -> Callable[..., int]:
    def play(*args: object) -> int:
        seen.append(args)
        return 0

    return play


class TestPlayRefusesWithoutAnAgreedGameId:
    """Both sides name their files from it; a mismatch is two unrelated sets."""

    def test_play_without_a_game_id_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(REPO)
        assert main(["play"], environ=NO_TUNNEL) == 1

    def test_the_message_says_it_must_be_agreed_beforehand(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(REPO)
        main(["play"], environ=NO_TUNNEL)
        assert "agreed with the opponent" in capsys.readouterr().err

    def test_a_game_id_gets_it_past_the_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It then tries to reach an opponent, which is where it belongs."""
        monkeypatch.chdir(REPO)
        started: list[object] = []
        monkeypatch.setattr("thief_agent.__main__.play", record_play(started))
        assert (
            main(["play", "--game-id", "uoh26-test"], environ={"PUBLIC_URL": "https://a.ngrok.io"})
            == 0
        )
        assert started, "play was never reached"


class TestPlayRefusesWithoutAPublicAddress:
    """`serve` tolerates no tunnel. `play` cannot — it announces to an opponent.

    Every check here passes ``NO_NGROK`` so the result describes the code
    rather than whether a tunnel happens to be running on this machine.
    """

    def test_no_tunnel_stops_it_before_the_handshake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(REPO)
        assert main(["play", "--game-id", "uoh26-x"], environ=NO_TUNNEL) == 1

    def test_the_message_explains_the_cost_to_both_sides(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Not '' must use one of ['https', 'http'], which helps nobody."""
        monkeypatch.chdir(REPO)
        monkeypatch.setattr("thief_agent.__main__.read_ngrok_api", None)
        main(["play", "--game-id", "uoh26-x"], environ=NO_TUNNEL)
        error = capsys.readouterr().err
        assert "start a tunnel" in error.lower()
        assert "zero for both sides" in error

    def test_a_public_url_gets_it_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(REPO)
        started: list[object] = []
        monkeypatch.setattr("thief_agent.__main__.play", record_play(started))
        assert (
            main(
                ["play", "--game-id", "uoh26-x"],
                environ={"PUBLIC_URL": "https://abc.ngrok.io"},
            )
            == 0
        )
        assert started

    def test_serve_still_runs_without_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local development must not be conditional on a tunnel."""
        monkeypatch.chdir(REPO)
        monkeypatch.setattr("thief_agent.__main__.serve", lambda *_: None)
        assert main([], environ=NO_TUNNEL) == 0
