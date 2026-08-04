"""The exchange that happens before two strangers can play each other."""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.handshake import (
    ADDRESS_KEY,
    AddressBook,
    Greeting,
    HandshakeError,
    Peering,
    check,
    check_rotation,
    record,
)
from thief_agent.runtime.orchestrator import PROTOCOL_VERSION

PUBLIC_COP = "https://cop-a1b2.ngrok-free.app"
PUBLIC_THIEF = "https://thief-c3d4.ngrok-free.app"
LOCAL_COP = "http://127.0.0.1:8801"
LOCAL_THIEF = "http://127.0.0.1:8802"


def greet(
    role: str, url: str, group: str = "s82kma9e", version: str = PROTOCOL_VERSION
) -> Greeting:
    return Greeting(role=role, group_id=group, public_url=url, protocol_version=version)


class TestTheGreetingItself:
    def test_it_normalises_the_url_so_both_sides_record_one_string(self) -> None:
        assert greet("police", f"{PUBLIC_COP}/").public_url == f"{PUBLIC_COP}/mcp"

    def test_it_reports_whether_the_address_routes(self) -> None:
        assert greet("police", PUBLIC_COP).reachable
        assert not greet("police", LOCAL_COP).reachable

    @pytest.mark.parametrize("role", ["cop", "COP", "referee", ""])
    def test_it_refuses_a_role_the_wire_does_not_name(self, role: str) -> None:
        """The reference says ``police``, not ``cop``.

        Our package is named for the role; the wire is not, and a mismatch
        here fails at first contact with a real opponent.
        """
        with pytest.raises(HandshakeError, match="role must be one of"):
            greet(role, PUBLIC_COP)

    @pytest.mark.parametrize("group", ["", "   "])
    def test_it_refuses_an_anonymous_team(self, group: str) -> None:
        with pytest.raises(HandshakeError, match="group_id must be set"):
            greet("police", PUBLIC_COP, group=group)

    def test_it_refuses_a_url_it_cannot_parse(self) -> None:
        with pytest.raises(HandshakeError):
            greet("police", "not-a-url")

    def test_it_is_frozen_so_an_agreed_address_cannot_move_afterwards(self) -> None:
        greeting = greet("police", PUBLIC_COP)
        with pytest.raises(AttributeError):
            greeting.public_url = LOCAL_COP  # type: ignore[misc]


class TestParsingWhatArrives:
    def test_it_round_trips(self) -> None:
        original = greet("thief", PUBLIC_THIEF)
        assert Greeting.from_dict(original.to_dict()) == original

    def test_it_survives_json(self) -> None:
        original = greet("thief", PUBLIC_THIEF)
        assert Greeting.from_dict(json.loads(json.dumps(original.to_dict()))) == original

    @pytest.mark.parametrize(
        "payload",
        [
            "not a mapping",
            {},
            {"role": "police"},
            {"role": "police", "group_id": "g", "public_url": PUBLIC_COP},
            {"role": "police", "group_id": "g", "public_url": 42, "protocol_version": "1.0"},
            {"role": "police", "group_id": "g", "public_url": "ftp://x", "protocol_version": "1.0"},
        ],
    )
    def test_it_refuses_a_malformed_greeting_as_one_error_type(self, payload: object) -> None:
        """One exception type for the caller, whatever went wrong inside.

        A greeting is the opponent's first byte and is untrusted from there
        on; a caller that had to catch three unrelated exceptions would catch
        two of them.
        """
        with pytest.raises(HandshakeError):
            Greeting.from_dict(payload)


class TestWhoMayPlayWhom:
    def test_two_public_peers_agree(self) -> None:
        check(greet("police", PUBLIC_COP), greet("thief", PUBLIC_THIEF))

    def test_a_protocol_mismatch_is_refused_before_the_first_move(self) -> None:
        with pytest.raises(HandshakeError, match="wire contract must match"):
            check(greet("police", PUBLIC_COP), greet("thief", PUBLIC_THIEF, version="0.9"))

    def test_two_peers_claiming_one_role_is_refused(self) -> None:
        """A game with two thieves has no capture target and no way to end.

        It would otherwise surface mid-turn as an arbitrary rejection rather
        than as the setup error it is.
        """
        with pytest.raises(HandshakeError, match="no capture target"):
            check(greet("thief", PUBLIC_THIEF), greet("thief", PUBLIC_COP))

    def test_a_public_peer_refuses_a_loopback_opponent(self) -> None:
        """The failure this whole module exists to catch.

        Their ``127.0.0.1`` is *our* machine. Every call would land on
        ourselves, the deadline would expire, and the sub-game would end in a
        technical loss scoring zero for both sides — including theirs.
        """
        with pytest.raises(HandshakeError, match="routes nowhere from here"):
            check(greet("police", PUBLIC_COP), greet("thief", LOCAL_THIEF))

    def test_two_loopback_peers_agree_because_that_is_the_local_test_loop(self) -> None:
        """Localhost is explicitly permitted while coding.

        Demanding a public opponent while sitting on loopback ourselves would
        make every local run of the two agents against each other impossible,
        which is the loop the whole project is developed in.
        """
        check(greet("police", LOCAL_COP), greet("thief", LOCAL_THIEF))

    def test_a_loopback_peer_accepts_a_public_opponent(self) -> None:
        """We may not demand more reachability than we ourselves offer.

        They can be reached, so the match can proceed. Our own exposure is
        their complaint to make, not ours to pre-empt.
        """
        check(greet("police", LOCAL_COP), greet("thief", PUBLIC_THIEF))


class TestTheAddressBook:
    def test_it_keys_by_role_and_records_reachability(self) -> None:
        book = AddressBook.of(greet("police", PUBLIC_COP), greet("thief", LOCAL_THIEF))
        assert set(book.entries) == {"police", "thief"}
        assert book.entries["police"]["reachable"] is True
        assert book.entries["thief"]["reachable"] is False

    def test_a_pair_is_complete_and_a_single_peer_is_not(self) -> None:
        assert AddressBook.of(greet("police", PUBLIC_COP), greet("thief", PUBLIC_THIEF)).complete
        assert not AddressBook({"police": {}}).complete

    def test_the_fragment_is_sorted_so_two_peers_write_identical_bytes(self) -> None:
        book = AddressBook.of(greet("thief", PUBLIC_THIEF), greet("police", PUBLIC_COP))
        assert list(book.to_fragment()[ADDRESS_KEY]) == ["police", "thief"]

    def test_the_fragment_does_not_alias_the_book(self) -> None:
        book = AddressBook.of(greet("police", PUBLIC_COP), greet("thief", PUBLIC_THIEF))
        book.to_fragment()[ADDRESS_KEY]["police"]["public_url"] = "tampered"
        assert book.entries["police"]["public_url"] == f"{PUBLIC_COP}/mcp"


class TestRecordingTheDeclaration:
    def book(self) -> AddressBook:
        return AddressBook.of(greet("police", PUBLIC_COP), greet("thief", PUBLIC_THIEF))

    def test_it_writes_the_named_file(self, tmp_path: Path) -> None:
        path = record(tmp_path, "uoh26-s82kma9e", self.book())
        assert path.name == "declaration_uoh26-s82kma9e.json"
        assert json.loads(path.read_text())[ADDRESS_KEY]["thief"]["public_url"] == (
            f"{PUBLIC_THIEF}/mcp"
        )

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        assert record(tmp_path / "artefacts", "g1", self.book()).exists()

    def test_it_merges_rather_than_overwrites(self, tmp_path: Path) -> None:
        """The declaration accumulates across stages.

        Hardware statements, the model in use and the token ceiling arrive in
        later stages. A stage that rewrote the file wholesale would drop them
        with nothing to show it had happened.
        """
        path = tmp_path / "declaration_g1.json"
        path.write_text(json.dumps({"hardware": {"cpu": "M2"}, "token_ceiling": 200000}))
        merged: dict[str, Any] = json.loads(record(tmp_path, "g1", self.book()).read_text())
        assert merged["hardware"] == {"cpu": "M2"}
        assert merged["token_ceiling"] == 200000
        assert ADDRESS_KEY in merged

    def test_re_recording_replaces_only_the_addresses(self, tmp_path: Path) -> None:
        record(tmp_path, "g1", self.book())
        second = AddressBook.of(greet("police", LOCAL_COP), greet("thief", LOCAL_THIEF))
        merged = json.loads(record(tmp_path, "g1", second).read_text())
        assert merged[ADDRESS_KEY]["police"]["public_url"] == f"{LOCAL_COP}/mcp"

    def test_it_refuses_a_one_sided_record(self, tmp_path: Path) -> None:
        with pytest.raises(HandshakeError, match="proves nothing at audit"):
            record(tmp_path, "g1", AddressBook({"police": {}}))

    def test_it_refuses_a_declaration_that_is_not_an_object(self, tmp_path: Path) -> None:
        (tmp_path / "declaration_g1.json").write_text("[1, 2, 3]")
        with pytest.raises(Exception, match="declaration"):
            record(tmp_path, "g1", self.book())

    def test_it_refuses_a_game_id_that_would_escape_the_directory(self, tmp_path: Path) -> None:
        with pytest.raises(Exception, match="filename component"):
            record(tmp_path, "../../etc/passwd", self.book())


ROTATED_COP = "https://cop-9z8y.ngrok-free.app"
ROTATED_THIEF = "https://thief-e5f6.ngrok-free.app"


def opened(sub_game: int = 1) -> Peering:
    return Peering(greet("police", PUBLIC_COP), greet("thief", PUBLIC_THIEF), sub_game)


class TestWhatCountsAsARotatedTunnel:
    def test_the_same_peer_at_a_new_address_is_accepted(self) -> None:
        check_rotation(greet("thief", PUBLIC_THIEF), greet("thief", ROTATED_THIEF))

    @pytest.mark.parametrize(
        ("field", "fresh"),
        [
            ("role", ("police", ROTATED_THIEF, "s82kma9e", PROTOCOL_VERSION)),
            ("group_id", ("thief", ROTATED_THIEF, "another-team", PROTOCOL_VERSION)),
            ("protocol_version", ("thief", ROTATED_THIEF, "s82kma9e", "2.0")),
        ],
    )
    def test_anything_but_the_address_moving_is_a_different_peer(
        self, field: str, fresh: tuple[str, str, str, str]
    ) -> None:
        """A restarted tunnel changes one thing. Anything else is somebody else.

        Following it would mean finishing a series against a peer the
        declaration does not name.
        """
        role, url, group, version = fresh
        with pytest.raises(HandshakeError, match=field):
            check_rotation(greet("thief", PUBLIC_THIEF), greet(role, url, group, version))


class TestPeering:
    def test_it_carries_fresh_addresses_into_the_next_sub_game(self) -> None:
        later = opened().rotate(greet("police", PUBLIC_COP), greet("thief", ROTATED_THIEF), 2)
        assert later.sub_game == 2
        assert later.theirs.public_url == f"{ROTATED_THIEF}/mcp"

    def test_a_mid_sub_game_change_is_refused(self) -> None:
        """Indistinguishable from redirecting our traffic after seeing our commit.

        Between sub-games there is no live state to protect, which is exactly
        why the boundary is the condition rather than a matter of trust.
        """
        with pytest.raises(HandshakeError, match="only change between sub-games"):
            opened(2).rotate(greet("police", PUBLIC_COP), greet("thief", ROTATED_THIEF), 2)

    def test_going_backwards_is_refused(self) -> None:
        with pytest.raises(HandshakeError, match="does not follow"):
            opened(3).rotate(greet("police", PUBLIC_COP), greet("thief", ROTATED_THIEF), 2)

    def test_a_rotation_still_has_to_be_playable(self) -> None:
        """The reachability rule does not lapse because we already shook hands."""
        with pytest.raises(HandshakeError, match="routes nowhere"):
            opened().rotate(greet("police", PUBLIC_COP), greet("thief", LOCAL_THIEF), 2)

    def test_it_reports_only_the_addresses_that_actually_moved(self) -> None:
        """A re-handshake usually changes nothing; the tunnel outlived the game."""
        first = opened()
        assert first.relocations(first.rotate(*(first.ours, first.theirs), 2)) == {}

    def test_it_names_both_sides_when_both_rotate(self) -> None:
        first = opened()
        later = first.rotate(greet("police", ROTATED_COP), greet("thief", ROTATED_THIEF), 2)
        assert first.relocations(later) == {
            "police": (f"{PUBLIC_COP}/mcp", f"{ROTATED_COP}/mcp"),
            "thief": (f"{PUBLIC_THIEF}/mcp", f"{ROTATED_THIEF}/mcp"),
        }

    def test_it_is_frozen_so_the_agreed_pair_cannot_drift(self) -> None:
        with pytest.raises(AttributeError):
            opened().sub_game = 9  # type: ignore[misc]


class TestTheDeclarationRecordsWhenAnAddressTookEffect:
    def test_the_sub_game_travels_with_the_book(self) -> None:
        """Otherwise a rotated series looks like one that never moved."""
        book = AddressBook.peered(opened(4))
        assert {e["since_sub_game"] for e in book.entries.values()} == {4}

    def test_a_rotation_updates_the_file_in_place(self, tmp_path: Path) -> None:
        first = opened()
        record(tmp_path, "g1", AddressBook.peered(first))
        later = first.rotate(greet("police", PUBLIC_COP), greet("thief", ROTATED_THIEF), 2)
        written = json.loads(record(tmp_path, "g1", AddressBook.peered(later)).read_text())
        assert written[ADDRESS_KEY]["thief"]["public_url"] == f"{ROTATED_THIEF}/mcp"
        assert written[ADDRESS_KEY]["thief"]["since_sub_game"] == 2
