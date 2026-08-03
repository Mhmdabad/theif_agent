"""Tests for inbound payload validation."""

import pytest

from thief_agent.infra.tools import PROTOCOL_VERSION, PeerIdentity, ToolSurface
from thief_agent.infra.validation import (
    InvalidPayloadError,
    reject_unknown_fields,
    require_choice,
    require_int,
    require_mapping,
    require_str,
)

OURS = PeerIdentity(group_id="s82kma9e", role="thief")
DIGEST = "a" * 64


def surface() -> ToolSurface:
    return ToolSurface(OURS, DIGEST, lambda: "deadbeef")


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
        assert require_choice({"role": "cop"}, "role", frozenset({"cop", "thief"})) == "cop"


class TestRejectUnknownFields:
    def test_extras_are_refused(self) -> None:
        """Silently ignoring extras hides a wire-contract divergence."""
        with pytest.raises(InvalidPayloadError, match=r"unexpected fields: \['evil'\]"):
            reject_unknown_fields({"a": 1, "evil": 2}, frozenset({"a"}))

    def test_exact_fields_pass(self) -> None:
        reject_unknown_fields({"a": 1}, frozenset({"a"}))


class TestDispatchNeverRaises:
    @pytest.mark.parametrize(
        "payload",
        [None, [], "x", 1, {"role": 1}, {"role": True}, {1: "x"}, {"unexpected": "y"}],
    )
    def test_hostile_payloads_become_refusals(self, payload: object) -> None:
        """A crash mid-turn is a technical loss scoring zero for both sides."""
        result = surface().dispatch("handshake", payload)
        assert not result.ok
        assert result.detail

    def test_unknown_tool_is_refused_not_raised(self) -> None:
        result = surface().dispatch("drop_tables", {})
        assert not result.ok
        assert "unknown tool" in result.detail

    def test_a_valid_handshake_still_works(self) -> None:
        result = surface().dispatch(
            "handshake",
            {"group_id": "them", "role": "cop", "protocol_version": PROTOCOL_VERSION},
        )
        assert result.ok

    def test_a_valid_negotiate_still_works(self) -> None:
        assert surface().dispatch("negotiate_config", {"config_sha256": DIGEST}).ok

    def test_ping_and_state_digest_take_no_fields(self) -> None:
        assert surface().dispatch("ping", {}).ok
        assert surface().dispatch("get_state_digest", {}).ok
        assert not surface().dispatch("ping", {"extra": 1}).ok

    def test_a_bogus_role_is_refused(self) -> None:
        result = surface().dispatch(
            "handshake",
            {"group_id": "them", "role": "referee", "protocol_version": PROTOCOL_VERSION},
        )
        assert not result.ok
        assert "must be one of" in result.detail
