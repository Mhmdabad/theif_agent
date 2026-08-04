"""Phase 1 of the Commit-Reveal ceremony: the hash, and nothing else."""

import json

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.infra.ceremony import COMMIT_FIELDS, CeremonyError, Commitment

DIGEST = "a" * 64
WHEN = "2026-08-04T09:00:00+00:00"
BOARD = BoardState(grid_size=8, cop=(1, 2), thief=(6, 5), barriers=frozenset({(3, 3)}), step=4)


def commitment(**overrides: object) -> Commitment:
    fields: dict[str, object] = {
        "step": 4,
        "sender": "thief",
        "commit": DIGEST,
        "timestamp": WHEN,
    }
    return Commitment(**{**fields, **overrides})  # type: ignore[arg-type]


class TestOnlyTheHashCrossesTheWire:
    def test_the_wire_form_is_exactly_the_declared_fields(self) -> None:
        """The tuple is the specification, not a hint."""
        assert tuple(commitment().to_dict()) == COMMIT_FIELDS

    def test_it_carries_nothing_that_narrows_the_search_space(self) -> None:
        """The move space is five moves and a handful of barrier cells.

        An opponent who learns which cells were even candidates hashes the
        remainder in microseconds, so leaking *any* structure is fatal rather
        than merely untidy.
        """
        wire = json.dumps(commitment().to_dict())
        for leak in ("move", "hint", "intent", "barrier", "nonce", "cop", "police", "state"):
            assert leak not in wire

    def test_a_real_commitment_reveals_nothing_about_its_record(self) -> None:
        record = step_record(BOARD, "thief", "N", "lie", "heading uptown", barrier_placed=(2, 2))
        wire = json.dumps(commitment(commit=commit_of(record, "0" * 32)).to_dict())
        assert "heading uptown" not in wire
        assert "N" not in wire.replace("2026", "")  # the timestamp is allowed its digits

    def test_two_different_records_are_indistinguishable_on_the_wire(self) -> None:
        """Same shape, same length, no structure to compare."""
        north = commit_of(step_record(BOARD, "thief", "N", "truth", "north"), "0" * 32)
        south = commit_of(step_record(BOARD, "thief", "S", "lie", "somewhere else"), "0" * 32)
        assert len(north) == len(south)
        assert set(commitment(commit=north).to_dict()) == set(commitment(commit=south).to_dict())


class TestWhatItRefuses:
    @pytest.mark.parametrize("sender", ["cop", "referee", "POLICE", ""])
    def test_a_role_the_wire_does_not_name(self, sender: str) -> None:
        with pytest.raises(CeremonyError, match="sender must be one of"):
            commitment(sender=sender)

    def test_a_negative_step(self) -> None:
        with pytest.raises(CeremonyError, match="step must be >= 0"):
            commitment(step=-1)

    @pytest.mark.parametrize(
        "digest",
        ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "", "0x" + "a" * 62, "a" * 32],
    )
    def test_a_digest_that_is_not_a_sha256_hexdigest(self, digest: str) -> None:
        """An uppercase or truncated digest compares unequal to ours.

        It would surface later as a forgery verdict against an opponent whose
        only mistake was formatting — and a forgery verdict is unappealable.
        """
        with pytest.raises(CeremonyError, match="64 lowercase hex"):
            commitment(commit=digest)

    def test_it_is_frozen_because_an_editable_commitment_is_not_one(self) -> None:
        """The whole value of the phase is being fixed before theirs is known."""
        with pytest.raises(AttributeError):
            commitment().commit = "b" * 64  # type: ignore[misc]


class TestParsingWhatArrives:
    def test_it_round_trips(self) -> None:
        assert Commitment.from_dict(commitment().to_dict()) == commitment()

    def test_it_survives_json(self) -> None:
        assert Commitment.from_dict(json.loads(json.dumps(commitment().to_dict()))) == commitment()

    def test_extra_fields_are_dropped_rather_than_refused(self) -> None:
        """We cannot stop an opponent putting their move in the message.

        Refusing would let them end our match by sending one. Declining to
        *read* it means nothing downstream can act on information phase 1 was
        never supposed to carry.
        """
        smuggled = {**commitment().to_dict(), "move": "N", "hint": "uptown"}
        parsed = Commitment.from_dict(smuggled)
        assert parsed == commitment()
        assert not hasattr(parsed, "move")

    @pytest.mark.parametrize(
        "payload",
        [
            "not a mapping",
            {},
            {"step": 4, "sender": "thief", "commit": DIGEST},
            {"step": "four", "sender": "thief", "commit": DIGEST, "timestamp": WHEN},
            {"step": 4, "sender": "thief", "commit": 42, "timestamp": WHEN},
        ],
    )
    def test_a_malformed_commitment_is_one_error_type(self, payload: object) -> None:
        with pytest.raises(CeremonyError):
            Commitment.from_dict(payload)
