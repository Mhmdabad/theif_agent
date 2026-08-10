"""The command somebody actually types, and what it tells them before it binds."""

import argparse
from collections.abc import Callable
from pathlib import Path

import pytest

from thief_agent.__main__ import (
    CONFIG,
    MAX_DEPTH,
    StartupError,
    describe,
    describe_failure,
    load_private,
    main,
    require_playable,
    safely_describe,
    where_we_are,
)

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


class TestSayingWhatWentWrong:
    """A failure that prints nothing after the colon is worse than a traceback.

    The sixth live warm-up ended with `the match did not finish:` and no text,
    after most of a sub-game had been played. Every fact about the failure was
    discarded at the last step.
    """

    def test_a_plain_message_is_passed_through(self) -> None:
        assert describe_failure(ValueError("the board is the wrong size")) == (
            "the board is the wrong size (ValueError)"
        )

    def test_an_exception_group_is_unwrapped(self) -> None:
        """anyio and the MCP client raise these, often with a blank outer message."""
        group = ExceptionGroup("", [ConnectionError("tunnel is down"), TimeoutError("no reply")])
        said = describe_failure(group)
        assert "tunnel is down" in said
        assert "no reply" in said

    def test_several_arguments_are_joined_rather_than_shown_as_a_tuple(self) -> None:
        """`MatchAborted(TechnicalLoss.TIMEOUT, why)` renders as a tuple otherwise."""
        said = describe_failure(RuntimeError("timeout", "the opponent stopped answering"))
        assert said.startswith("timeout; the opponent stopped answering")
        assert "(" not in said.split("(RuntimeError")[0]

    def test_a_silent_exception_names_its_cause(self) -> None:
        """When there is no message, the chain is the only information left."""
        try:
            try:
                raise ConnectionError("nothing is listening behind the tunnel")
            except ConnectionError as inner:
                raise RuntimeError from inner
        except RuntimeError as exc:
            said = describe_failure(exc)
        assert "carried no message" in said
        assert "nothing is listening behind the tunnel" in said

    def test_a_silent_exception_with_no_cause_still_says_something(self) -> None:
        said = describe_failure(RuntimeError())
        assert "RuntimeError" in said
        assert "nothing recorded why" in said

    def test_the_class_is_not_repeated_when_the_message_already_names_it(self) -> None:
        """`StartupTimeout: ...` should not become `StartupTimeout: ... (StartupTimeout)`."""

        class StartupTimeout(RuntimeError):
            pass

        assert describe_failure(StartupTimeout("StartupTimeout while waiting")) == (
            "StartupTimeout while waiting"
        )


class TestTheReporterCannotBecomeTheFailure:
    """The walk is over a graph, not a tree, and the first version assumed a tree.

    `anyio` re-raises across task boundaries, which produces groups holding
    exceptions whose `__context__` is the group. Walking that without a guard
    recursed until the interpreter gave up — in the error handler, so the real
    failure was replaced by a `RecursionError` traceback and lost.
    """

    def cyclic(self) -> BaseException:
        """A group whose member points back at it, as the live failure did."""
        leaf = RuntimeError()
        group = ExceptionGroup("", [leaf])
        leaf.__context__ = group
        return group

    def test_a_cycle_terminates(self) -> None:
        assert "RuntimeError" in describe_failure(self.cyclic())

    def test_a_cycle_terminates_through_the_safe_wrapper_too(self) -> None:
        assert safely_describe(self.cyclic())

    def test_a_long_chain_stops_before_it_becomes_noise(self) -> None:
        """Depth is bounded even when every link is distinct, so no cycle exists."""
        deepest = ValueError("the bottom")
        current: BaseException = deepest
        for _ in range(MAX_DEPTH * 3):
            nxt = RuntimeError()
            nxt.__cause__ = current
            current = nxt
        said = describe_failure(current)
        assert "the bottom" not in said, "walked further than the depth bound"

    def test_the_same_leaf_twice_is_said_once(self) -> None:
        """A group often carries one failure duplicated per task. Repeating it is noise."""
        one = ConnectionError("nothing is listening behind the tunnel")
        said = describe_failure(ExceptionGroup("", [one, ConnectionError(str(one))]))
        assert said.count("nothing is listening") == 1

    def test_a_reporter_that_explodes_still_reports(self) -> None:
        """The property that was missing: diagnostics may not take the run down."""

        class Hostile(Exception):
            def __str__(self) -> str:
                raise RecursionError("boom")

        said = safely_describe(Hostile())
        assert "the failure description itself failed" in said
        assert "Hostile" in said


class TestRehearsalIsExemptFromTheTunnelRequirement:
    def test_rehearsing_announces_to_nobody_so_the_refusal_does_not_apply(self) -> None:
        """Keyed on the flag, not the address, so the league path cannot reach it."""
        require_playable(argparse.Namespace(game_id="uoh26-x", rehearse=True), NO_TUNNEL, NO_NGROK)

    def test_rehearsing_does_not_excuse_a_missing_game_id(self) -> None:
        """Both sides' files are still named from it, and still have to match."""
        with pytest.raises(StartupError, match="game-id"):
            require_playable(argparse.Namespace(game_id="", rehearse=True), NO_TUNNEL, NO_NGROK)

    def test_without_the_flag_a_tunnel_is_still_required(self) -> None:
        with pytest.raises(StartupError, match="Start a tunnel"):
            require_playable(argparse.Namespace(game_id="uoh26-x", rehearse=False), {}, NO_NGROK)


class TestARehearsalMayAdvertiseAPrivateAddress:
    """Two machines on one LAN, which the banner used to make impossible.

    ``require_playable`` already exempted a rehearsal, but the banner is
    printed before any command dispatch and refused the address first — so the
    exemption below it was unreachable and a LAN rehearsal could not start.
    """

    LAN = {"PUBLIC_URL": "http://192.168.1.192:8802"}

    def test_a_lan_address_is_announced_rather_than_refused(self) -> None:
        assert where_we_are(self.LAN, NO_NGROK, rehearsal=True) == "http://192.168.1.192:8802/mcp"

    def test_the_league_path_still_refuses_the_same_address(self) -> None:
        """The exemption is keyed on the flag, never on the address."""
        with pytest.raises(StartupError, match="not reachable from another machine"):
            where_we_are(self.LAN, NO_NGROK, rehearsal=False)

    def test_a_rehearsal_falls_back_to_loopback_on_its_own_port(self) -> None:
        assert where_we_are({}, NO_NGROK, rehearsal=True, port=8801) == "http://127.0.0.1:8801/mcp"

    def test_being_a_rehearsal_still_does_not_excuse_a_typo(self) -> None:
        with pytest.raises(StartupError, match="unusable"):
            where_we_are({"PUBLIC_URL": "not a url"}, NO_NGROK, rehearsal=True)

    def test_describe_advertises_the_port_it_is_about_to_bind(self) -> None:
        """Not a default that could disagree with the server settings."""
        network = {"my_port": 8801, "opponent_url": "http://127.0.0.1:8802/mcp"}
        lines = describe({"network": network}, {}, True)
        assert "  reachable at   http://127.0.0.1:8801/mcp" in lines
