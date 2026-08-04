"""The record a technical result is argued from."""

import re
from pathlib import Path

import pytest

from thief_agent.infra.mcp_client import ClientSettings, OpponentClient, OpponentUnreachableError
from thief_agent.infra.transport_log import (
    CONNECT,
    KINDS,
    RECONNECT,
    RETRY,
    SENT,
    TIMEOUT,
    UNREACHABLE,
    Event,
    TransportLog,
    now_utc,
)
from thief_agent.shared.naming import NamingError, transport_log_filename

URL = "https://opponent-c3d4.ngrok-free.app/mcp"
MOVED = "https://opponent-e5f6.ngrok-free.app/mcp"


class Ticking:
    """A clock that advances a millisecond per read, so order is visible."""

    def __init__(self) -> None:
        self.reads = 0

    def __call__(self) -> str:
        self.reads += 1
        return f"2026-08-04T09:00:00.{self.reads:03d}+00:00"


class Flaky:
    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)

    def call(
        self, url: str, tool: str, payload: dict[str, object], timeout: float
    ) -> dict[str, object]:
        outcome = self._outcomes.pop(0) if self._outcomes else {"ok": True}
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


def client(*outcomes: object, url: str = URL) -> OpponentClient:
    settings = ClientSettings(opponent_url=url, retry_backoff_sec=0.0)
    return OpponentClient(Flaky(*outcomes), settings, log=TransportLog(clock=Ticking()))


class TestTimestamps:
    def test_they_are_utc_because_two_peers_compare_logs(self) -> None:
        """ "09:41" means nothing without knowing whose morning it was."""
        assert now_utc().endswith("+00:00")

    def test_they_carry_milliseconds(self) -> None:
        """A retry burst inside one second is the shape this log explains.

        Second resolution would render it as several things happening at once.
        """
        assert re.search(r"\.\d{3}\+00:00$", now_utc())


class TestEvent:
    def test_it_renders_one_line(self) -> None:
        line = str(
            Event("2026-08-04T09:00:00.000+00:00", TIMEOUT, "receive_turn", URL, "no answer")
        )
        assert "\n" not in line
        assert all(part in line for part in (TIMEOUT, "receive_turn", URL, "no answer"))

    def test_a_toolless_event_still_lines_up(self) -> None:
        assert "-" in str(Event("2026-08-04T09:00:00.000+00:00", RECONNECT, "", URL))

    def test_an_unknown_kind_is_refused(self) -> None:
        """A kind nobody recognises is a line nobody can act on at audit."""
        with pytest.raises(ValueError, match="kind must be one of"):
            Event("2026-08-04T09:00:00.000+00:00", "vibes", "receive_turn", URL)

    def test_it_is_frozen(self) -> None:
        event = Event("2026-08-04T09:00:00.000+00:00", SENT, "receive_turn", URL)
        with pytest.raises(AttributeError):
            event.kind = TIMEOUT  # type: ignore[misc]

    def test_it_serialises_every_field(self) -> None:
        event = Event("2026-08-04T09:00:00.000+00:00", SENT, "receive_turn", URL, "abc")
        assert set(event.to_dict()) == {"at", "kind", "tool", "url", "detail"}


class TestTheLog:
    def test_it_keeps_events_in_order(self) -> None:
        log = TransportLog(clock=Ticking())
        log.record(CONNECT, "negotiate", URL)
        log.record(SENT, "receive_turn", URL, "abc")
        assert [event.kind for event in log.events] == [CONNECT, SENT]

    def test_it_filters_by_kind(self) -> None:
        log = TransportLog(clock=Ticking())
        log.record(TIMEOUT, "receive_turn", URL)
        log.record(SENT, "receive_turn", URL)
        log.record(TIMEOUT, "negotiate", URL)
        assert len(log.of_kind(TIMEOUT)) == 2

    def test_it_lists_addresses_in_the_order_they_were_adopted(self) -> None:
        log = TransportLog(clock=Ticking())
        log.record(CONNECT, "negotiate", URL)
        log.record(SENT, "receive_turn", URL)
        log.record(RECONNECT, "", MOVED, detail=URL)
        assert log.addresses == [URL, MOVED]

    def test_an_empty_log_says_so_rather_than_rendering_nothing(self) -> None:
        """A blank file and an unwritten file look identical in a dispute."""
        assert "no transport events" in TransportLog().render()
        assert "no transport events" in TransportLog().summary()

    def test_the_summary_counts_each_kind(self) -> None:
        log = TransportLog(clock=Ticking())
        for _ in range(3):
            log.record(TIMEOUT, "receive_turn", URL)
        log.record(SENT, "receive_turn", URL)
        assert "timeout 3" in log.summary()
        assert "sent 1" in log.summary()

    def test_the_render_ends_with_the_summary(self) -> None:
        """What a person wants before reading four hundred lines."""
        log = TransportLog(clock=Ticking())
        log.record(SENT, "receive_turn", URL, "abc")
        assert log.render().rstrip().endswith(log.summary())

    def test_to_dicts_is_the_machine_form(self) -> None:
        """So the human format never has to compromise for the JSON report."""
        log = TransportLog(clock=Ticking())
        log.record(SENT, "receive_turn", URL, "abc")
        assert log.to_dicts() == [
            {
                "at": "2026-08-04T09:00:00.001+00:00",
                "kind": SENT,
                "tool": "receive_turn",
                "url": URL,
                "detail": "abc",
            }
        ]


class TestWritingIt:
    def test_it_writes_the_rendered_log(self, tmp_path: Path) -> None:
        log = TransportLog(clock=Ticking())
        log.record(UNREACHABLE, "receive_turn", URL, "peer gone")
        path = log.write(tmp_path / "transport_g1_g01.log")
        assert "peer gone" in path.read_text()

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        assert TransportLog().write(tmp_path / "artefacts" / "t.log").exists()

    def test_it_replaces_rather_than_appends(self, tmp_path: Path) -> None:
        """A file that proves a dispute should not also have to be searched."""
        path = tmp_path / "t.log"
        path.write_text("a previous match\n")
        TransportLog().write(path)
        assert "a previous match" not in path.read_text()

    def test_the_filename_names_the_sub_game(self) -> None:
        """Evidence that cannot be matched to its sub-game is unusable."""
        assert transport_log_filename("uoh26-s82kma9e", 3) == "transport_uoh26-s82kma9e_g03.log"

    def test_the_filename_refuses_a_game_id_that_would_escape(self) -> None:
        with pytest.raises(NamingError):
            transport_log_filename("../etc/passwd", 1)


class TestWhatTheClientRecords:
    def test_a_first_success_records_a_connection(self) -> None:
        """Proof the tunnel was ever alive, which a later timeout does not give."""
        peer = client({"ok": True})
        peer.call("negotiate", {})
        assert [event.kind for event in peer.log.events] == [SENT, CONNECT]

    def test_it_connects_once_per_address_not_once_per_call(self) -> None:
        peer = client({"ok": True}, {"ok": True})
        peer.call("negotiate", {})
        peer.call("receive_turn", {})
        assert len(peer.log.of_kind(CONNECT)) == 1

    def test_a_failed_attempt_names_the_error(self) -> None:
        """ "timeout" alone is worth little; the other side cannot check it."""
        peer = client(ConnectionError("tunnel refused"), {"ok": True})
        peer.call("receive_turn", {})
        assert "ConnectionError: tunnel refused" in peer.log.of_kind(TIMEOUT)[0].detail

    def test_a_retry_says_which_attempt_of_how_many(self) -> None:
        peer = client(TimeoutError(), TimeoutError(), {"ok": True})
        peer.call("receive_turn", {})
        assert [event.detail for event in peer.log.of_kind(RETRY)] == [
            "attempt 2 of 4 after 0s",
            "attempt 3 of 4 after 0s",
        ]

    def test_the_last_attempt_is_not_followed_by_a_retry(self) -> None:
        peer = client(*[TimeoutError()] * 4)
        with pytest.raises(OpponentUnreachableError):
            peer.call("receive_turn", {})
        assert len(peer.log.of_kind(TIMEOUT)) == 4
        assert len(peer.log.of_kind(RETRY)) == 3

    def test_exhaustion_is_the_line_that_becomes_a_technical_loss(self) -> None:
        peer = client(*[TimeoutError("silent")] * 4)
        with pytest.raises(OpponentUnreachableError):
            peer.call("receive_turn", {})
        assert peer.log.of_kind(UNREACHABLE)[0].url == URL

    def test_a_relocation_records_where_traffic_used_to_go(self) -> None:
        peer = client()
        peer.repoint(MOVED)
        moved = peer.log.of_kind(RECONNECT)[0]
        assert (moved.detail, moved.url) == (URL, MOVED)

    def test_repointing_to_the_same_address_records_nothing(self) -> None:
        peer = client()
        peer.repoint(URL)
        assert peer.log.events == []

    def test_the_whole_sequence_reads_in_order(self) -> None:
        peer = client(TimeoutError("gone"), {"ok": True})
        peer.call("receive_turn", {"move": "N"})
        assert [event.kind for event in peer.log.events] == [SENT, TIMEOUT, RETRY, CONNECT]


class TestTheDerivedViews:
    def test_sent_digests_come_out_of_the_log(self) -> None:
        """One record, not two. Two records is one that can be wrong unnoticed."""
        peer = client({"ok": True}, {"ok": True})
        peer.call("receive_turn", {"move": "N"})
        peer.call("receive_turn", {"move": "N"})
        assert [tool for tool, _ in peer.sent] == ["receive_turn", "receive_turn"]
        assert peer.sent[0][1] == peer.sent[1][1]
        assert len(peer.log.of_kind(SENT)) == 2

    def test_relocations_come_out_of_the_log(self) -> None:
        peer = client()
        peer.repoint(MOVED)
        assert peer.relocations == [(URL, MOVED)]

    def test_a_shared_log_collects_from_both(self) -> None:
        """One file per match, however many clients wrote into it."""
        log = TransportLog(clock=Ticking())
        settings = ClientSettings(opponent_url=URL, retry_backoff_sec=0.0)
        OpponentClient(Flaky({"ok": True}), settings, log=log).call("negotiate", {})
        OpponentClient(Flaky({"ok": True}), settings, log=log).call("receive_turn", {})
        assert len(log.of_kind(SENT)) == 2

    def test_every_kind_the_client_emits_is_a_declared_kind(self) -> None:
        peer = client(TimeoutError(), *[TimeoutError()] * 4)
        with pytest.raises(OpponentUnreachableError):
            peer.call("receive_turn", {})
        peer.repoint(MOVED)
        assert {event.kind for event in peer.log.events} <= set(KINDS)
