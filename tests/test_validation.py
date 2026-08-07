"""Tests for inbound payload validation."""

import pytest

from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.validation import (
    InvalidPayloadError,
    reject_unknown_fields,
    require_choice,
    require_int,
    require_mapping,
    require_str,
)


class TestRequireMapping:
    @pytest.mark.parametrize("bad", [None, [], "x", 1, 1.5, True])
    def test_non_objects_are_refused(self, bad: object) -> None:
        with pytest.raises(InvalidPayloadError, match="must be an object"):
            require_mapping(bad)

    def test_non_string_keys_are_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="keys must be strings"):
            require_mapping({1: "x"})

    def test_an_object_passes(self) -> None:
        assert require_mapping({"a": 1}) == {"a": 1}


class TestRequireStr:
    def test_missing_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="missing required field"):
            require_str({}, "k")

    @pytest.mark.parametrize("bad", [1, None, [], {}, True])
    def test_wrong_type_is_refused(self, bad: object) -> None:
        with pytest.raises(InvalidPayloadError, match="must be a string"):
            require_str({"k": bad}, "k")

    def test_empty_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="must not be empty"):
            require_str({"k": ""}, "k")

    def test_overlong_is_refused(self) -> None:
        """Bounded so a peer cannot be exhausted by one field."""
        with pytest.raises(InvalidPayloadError, match="exceeds"):
            require_str({"k": "x" * 5000}, "k")

    def test_a_normal_string_passes(self) -> None:
        assert require_str({"k": "v"}, "k") == "v"


class TestRequireInt:
    def test_booleans_are_refused(self) -> None:
        """isinstance(True, int) is true, so {"row": true} would be row 1."""
        with pytest.raises(InvalidPayloadError, match="must be an integer"):
            require_int({"row": True}, "row", minimum=0, maximum=6)

    @pytest.mark.parametrize("bad", ["1", 1.5, None])
    def test_wrong_type_is_refused(self, bad: object) -> None:
        with pytest.raises(InvalidPayloadError, match="must be an integer"):
            require_int({"row": bad}, "row", minimum=0, maximum=6)

    def test_missing_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="missing required field"):
            require_int({}, "row", minimum=0, maximum=6)

    @pytest.mark.parametrize("value", [-1, 7])
    def test_out_of_range_is_refused(self, value: int) -> None:
        with pytest.raises(InvalidPayloadError, match="must be 0..6"):
            require_int({"row": value}, "row", minimum=0, maximum=6)

    @pytest.mark.parametrize("value", [0, 3, 6])
    def test_in_range_passes(self, value: int) -> None:
        assert require_int({"row": value}, "row", minimum=0, maximum=6) == value


class TestRequireChoice:
    def test_unknown_value_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="must be one of"):
            require_choice({"role": "referee"}, "role", frozenset({"cop", "thief"}))

    def test_known_value_passes(self) -> None:
        assert require_choice({"role": "thief"}, "role", frozenset({"cop", "thief"})) == "thief"


class TestRejectUnknownFields:
    def test_extras_are_refused(self) -> None:
        """Silently ignoring extras hides a wire-contract divergence."""
        with pytest.raises(InvalidPayloadError, match=r"unexpected fields: \['evil'\]"):
            reject_unknown_fields({"a": 1, "evil": 2}, frozenset({"a"}))

    def test_exact_fields_pass(self) -> None:
        reject_unknown_fields({"a": 1}, frozenset({"a"}))


class TestTheLiveInboundSurface:
    """The mailboxes are what an opponent reaches, so hostile input ends here.

    These moved off the retired ToolSurface. Keeping them matters: a crash
    mid-turn is a technical loss scoring zero for both sides, so a peer that
    can be crashed by a malformed payload hands its opponent a way to void any
    match it is losing.
    """

    @pytest.mark.parametrize(
        "payload",
        [None, [], "x", 1, {"sender": 1}, {"sender": True}, {1: "x"}, {"sender": "referee"}],
    )
    def test_hostile_payloads_become_refusals(self, payload: object) -> None:
        assert PeerInboxes().receive_turn(payload)["ok"] is False

    def test_a_boolean_coordinate_is_refused(self) -> None:
        """{"barrier_placed": [true, 3]} would otherwise index row 1."""
        boxes = PeerInboxes(game_uid="series-123", sub_game=1)
        turn = {
            "step": 1,
            "sender": "police",
            "smell_grid": {},
            "commit": "c",
            "timestamp": "t",
            "game_uid": "series-123",
            "sub_game": 1,
            "barrier_placed": [True, 3],
        }
        assert boxes.receive_turn(turn)["ok"] is False

    def test_a_valid_turn_is_accepted(self) -> None:
        boxes = PeerInboxes(game_uid="series-123", sub_game=1)
        turn = {
            "step": 1,
            "sender": "police",
            "smell_grid": {},
            "commit": "c",
            "timestamp": "t",
            "game_uid": "series-123",
            "sub_game": 1,
        }
        assert boxes.receive_turn(turn)["ok"] is True
