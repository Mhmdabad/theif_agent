"""Tests for the wire protocol and the peer mailboxes.

Many of these pin a *format* rather than behaviour. That is the point: these
shapes have to match an opponent built independently from the same reference,
and a mismatch fails at first contact rather than in development.
"""

import pytest

from thief_agent.infra.inboxes import ACK, TOOL_NAMES, PeerInboxes, register
from thief_agent.infra.protocol import (
    CONTROL_KINDS,
    ROLES,
    AuditPayload,
    ControlMessage,
    TurnMessage,
)
from thief_agent.infra.validation import InvalidPayloadError

TURN = {
    "step": 3,
    "sender": "police",
    "hint": "closing in near Times Square",
    "smell_grid": {"2,3": 0.9, "2,4": 0.6},
    "commit": "a" * 64,
    "timestamp": "2026-08-03T09:00:00+00:00",
}


class TestWireVocabulary:
    def test_roles_use_the_reference_names(self) -> None:
        """The reference says 'police', not 'cop'."""
        assert {"police", "thief"} == ROLES

    def test_control_kinds_match_the_reference(self) -> None:
        assert {"enable", "status", "restart", "quit"} == CONTROL_KINDS

    def test_tool_names_match_the_reference(self) -> None:
        assert TOOL_NAMES == ("negotiate", "receive_turn", "submit_audit", "receive_control")


class TestTurnMessage:
    def test_round_trips(self) -> None:
        assert TurnMessage.from_dict(TURN).to_dict()["commit"] == TURN["commit"]

    def test_optional_fields_default_to_none(self) -> None:
        parsed = TurnMessage.from_dict(TURN)
        assert parsed.barrier_placed is None
        assert parsed.capture_claim is None
        assert parsed.win_claim is None

    def test_carries_a_whole_turn_in_one_message(self) -> None:
        """Hint, scent, commit, barrier and claim travel together."""
        rich = {**TURN, "barrier_placed": [2, 3], "capture_claim": [4, 4]}
        parsed = TurnMessage.from_dict(rich)
        assert parsed.barrier_placed == [2, 3]
        assert parsed.capture_claim == [4, 4]

    def test_the_true_position_is_not_on_the_wire(self) -> None:
        """Only the commitment travels; position is proven at audit."""
        assert "position" not in TurnMessage.from_dict(TURN).to_dict()

    @pytest.mark.parametrize("missing", ["step", "sender", "commit", "timestamp"])
    def test_required_fields_are_enforced(self, missing: str) -> None:
        body = {k: v for k, v in TURN.items() if k != missing}
        with pytest.raises(InvalidPayloadError):
            TurnMessage.from_dict(body)

    def test_an_unknown_sender_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="must be one of"):
            TurnMessage.from_dict({**TURN, "sender": "referee"})

    def test_cop_is_not_a_wire_role(self) -> None:
        """Our internal name differs from the wire's; catching that here."""
        with pytest.raises(InvalidPayloadError):
            TurnMessage.from_dict({**TURN, "sender": "cop"})

    def test_a_malformed_cell_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="pair"):
            TurnMessage.from_dict({**TURN, "barrier_placed": [1, 2, 3]})

    def test_a_boolean_coordinate_is_refused(self) -> None:
        """[true, 3] would otherwise index row 1."""
        with pytest.raises(InvalidPayloadError, match="integers"):
            TurnMessage.from_dict({**TURN, "capture_claim": [True, 3]})

    def test_a_non_object_smell_grid_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="smell_grid"):
            TurnMessage.from_dict({**TURN, "smell_grid": []})

    def test_smell_grid_keys_stay_strings(self) -> None:
        """The wire form is {'r,c': intensity}, not tuple keys."""
        parsed = TurnMessage.from_dict(TURN)
        assert all(isinstance(k, str) for k in parsed.smell_grid)


class TestAuditPayload:
    def test_round_trips(self) -> None:
        payload = {
            "sender": "thief",
            "records": [{"payload": {"step": 0}, "nonce": "n", "commit": "c"}],
            "result_claim": "survival",
        }
        assert AuditPayload.from_dict(payload).to_dict() == payload

    def test_records_must_be_a_list(self) -> None:
        with pytest.raises(InvalidPayloadError, match="records"):
            AuditPayload.from_dict({"sender": "thief", "records": {}, "result_claim": "x"})

    def test_each_record_must_be_an_object(self) -> None:
        with pytest.raises(InvalidPayloadError):
            AuditPayload.from_dict({"sender": "thief", "records": ["x"], "result_claim": "y"})

    def test_result_claim_is_required(self) -> None:
        with pytest.raises(InvalidPayloadError):
            AuditPayload.from_dict({"sender": "thief", "records": []})


class TestControlMessage:
    def test_round_trips(self) -> None:
        parsed = ControlMessage.from_dict({"kind": "status", "sender": "police"})
        assert parsed.kind == "status"
        assert parsed.sub_game_number == 1

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(InvalidPayloadError, match="must be one of"):
            ControlMessage.from_dict({"kind": "selfdestruct", "sender": "police"})

    def test_it_is_not_part_of_the_sealed_record(self) -> None:
        """Control traffic must never reach the audit trail."""
        assert (
            "commit" not in ControlMessage.from_dict({"kind": "quit", "sender": "thief"}).to_dict()
        )


class RecordingHost:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def tool(self, fn: object) -> object:
        self.registered.append(getattr(fn, "__name__", str(fn)))
        return fn


class TestInboxes:
    def test_a_valid_turn_is_queued_and_acked(self) -> None:
        boxes = PeerInboxes()
        assert boxes.receive_turn(TURN) == ACK
        assert boxes.turns.get_nowait().step == 3

    def test_a_malformed_turn_is_refused_not_queued(self) -> None:
        """A bad message must not reach a consumer that meets it mid-turn."""
        boxes = PeerInboxes()
        result = boxes.receive_turn({"sender": "police"})
        assert result["ok"] is False
        assert boxes.turns.empty()

    def test_a_refusal_is_recorded_for_the_dispute(self) -> None:
        boxes = PeerInboxes()
        boxes.receive_turn(None)
        assert boxes.rejected and "receive_turn" in boxes.rejected[0]

    def test_nothing_raises_across_the_wire(self) -> None:
        """A crash mid-turn would void a match we might be winning."""
        boxes = PeerInboxes()
        hostiles: tuple[object, ...] = (None, [], "x", 1, {"sender": "referee"})
        for hostile in hostiles:
            assert boxes.negotiate(hostile)["ok"] in (True, False)
            assert boxes.receive_turn(hostile)["ok"] is False
            assert boxes.submit_audit(hostile)["ok"] is False
            assert boxes.receive_control(hostile)["ok"] is False

    def test_agreements_audits_and_controls_queue_separately(self) -> None:
        boxes = PeerInboxes()
        boxes.negotiate({"terms": {}})
        boxes.submit_audit({"sender": "police", "records": [], "result_claim": "capture"})
        boxes.receive_control({"kind": "enable", "sender": "police"})
        assert boxes.agreements.qsize() == 1
        assert boxes.audits.qsize() == 1
        assert boxes.controls.qsize() == 1
        assert boxes.turns.empty()

    def test_accepting_a_message_does_not_block_on_our_runtime(self) -> None:
        """Fire-and-forget: a busy peer never times out its opponent's send."""
        boxes = PeerInboxes()
        for step in range(100):
            assert boxes.receive_turn({**TURN, "step": step}) == ACK
        assert boxes.turns.qsize() == 100


class TestRegistration:
    def test_all_four_tools_are_exposed(self) -> None:
        host = RecordingHost()
        assert register(host, PeerInboxes()) == TOOL_NAMES
        assert host.registered == list(TOOL_NAMES)

    def test_no_extra_tools_are_exposed(self) -> None:
        host = RecordingHost()
        register(host, PeerInboxes())
        assert len(host.registered) == 4
