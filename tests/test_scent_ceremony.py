"""Where the scent field may travel, and where it may not.

The rulebook's four phases exist to stop one thing: choosing what to say after
hearing what the opponent said. The scent field is the newest thing this agent
says, so it has to be placed in that sequence deliberately rather than
wherever it is convenient.

* **Phase 1 carries a digest and nothing else.** A fresh emission peaks on the
  emitter's own cell, so a field sent alongside the commitment would hand over
  the exact position the commitment exists to hide. The reference dialect does
  exactly that — ``TurnMessage.smell_grid`` travels with the commit — and this
  is where the two protocols part company.
* **Phase 3 may carry it**, next to the move, the hint and the barrier
  declaration, because by then both sides are locked and neither can revise.
* **Phase 4 still carries only nonces.** The field was sealed in phase 1, so
  the audit needs no new material to check it.

The last property is what makes the field evidence rather than assertion, and
it is tested here against the ceremony rather than trusted to the caller.
"""

import json

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.domain.scent import emission
from thief_agent.domain.trail import Trail
from thief_agent.infra.ceremony import (
    REVEAL_FIELDS,
    Acknowledgement,
    CeremonyError,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
    audit_opponent,
)
from thief_agent.infra.protocol import TurnMessage

WHEN = "2026-08-05T12:00:00+00:00"
NONCE = "9f86d081884c7d659a2feaa0c55ad015"

# --- role block -------------------------------------------------------------
# The only part of this file that differs between the two agents.
OUR_ROLE = "thief"
THEIR_ROLE = "police"
THEIR_CELL = (3, 4)
# --- end role block ---------------------------------------------------------

BOARD = BoardState(
    grid_size=8,
    cop=THEIR_CELL if THEIR_ROLE == "police" else (1, 2),
    thief=THEIR_CELL if THEIR_ROLE == "thief" else (1, 2),
    barriers=frozenset(),
    step=4,
)
"""The board the opponent sealed against, with them standing on ``THEIR_CELL``.

Which coordinate that is depends on which role the opponent plays, and it has
to be *their* one: :func:`~..domain.crypto.board_terms` seals the sender's own
cell, so putting them on the wrong side would seal ours under their name.
"""


def field_at(cell: tuple[int, int]) -> dict[str, float]:
    trail = Trail()
    trail.deposit(emission(cell, 8))
    return trail.snapshot()


def reveal(**overrides: object) -> Reveal:
    body: dict[str, object] = {
        "step": 1,
        "sender": THEIR_ROLE,
        "move": "N",
        "intent": "truth",
        "hint": "near the docks",
        "timestamp": WHEN,
        "scent": field_at(THEIR_CELL),
    }
    return Reveal(**{**body, **overrides})  # type: ignore[arg-type]


class TestPhaseOneStillCarriesOnlyADigest:
    def test_a_commitment_has_no_scent_field(self) -> None:
        """A fresh emission peaks on the emitter's own cell."""
        commitment = Commitment(step=1, sender=THEIR_ROLE, commit="a" * 64, timestamp=WHEN)
        assert "scent" not in commitment.to_dict()
        assert "smell" not in json.dumps(commitment.to_dict())

    def test_a_smuggled_scent_field_is_not_read(self) -> None:
        """We cannot stop them sending it; we can decline to act on it."""
        smuggled = {
            **Commitment(step=1, sender=THEIR_ROLE, commit="a" * 64, timestamp=WHEN).to_dict(),
            "smell_grid": field_at(THEIR_CELL),
        }
        parsed = Commitment.from_dict(smuggled)
        assert not hasattr(parsed, "smell_grid")
        assert "smell_grid" not in parsed.to_dict()

    def test_the_reference_dialect_turn_still_goes_out_empty(self) -> None:
        """``TurnMessage`` can carry a field; the commit phase never fills it."""
        turn = TurnMessage(
            step=1, sender=THEIR_ROLE, hint="", smell_grid={}, commit="a" * 64, timestamp=WHEN
        )
        assert turn.smell_grid == {}


class TestPhaseThreeCarriesTheField:
    def test_the_wire_form_lists_it(self) -> None:
        assert tuple(reveal().to_dict()) == REVEAL_FIELDS
        assert "scent" in REVEAL_FIELDS

    def test_it_survives_a_json_round_trip_unchanged(self) -> None:
        """The field is hashed, so a float perturbed by the wire is a forgery."""
        opened = reveal()
        assert Reveal.from_dict(json.loads(json.dumps(opened.to_dict()))) == opened

    def test_a_reveal_without_a_field_is_still_parseable(self) -> None:
        """A peer that cannot bind scent is refused at the audit, not at the door.

        Refusing here would let any opponent end our match by omitting a key.
        """
        body = reveal().to_dict()
        del body["scent"]
        assert Reveal.from_dict(body).scent is None

    def test_the_nonce_is_still_refused(self) -> None:
        with pytest.raises(CeremonyError, match="nonce"):
            Reveal.from_dict({**reveal().to_dict(), "nonce": NONCE})

    def test_no_nonce_leaks_alongside_the_field(self) -> None:
        assert NONCE not in json.dumps(reveal().to_dict())


class TestAnInboundFieldIsValidatedAtTheDoor:
    @pytest.mark.parametrize(
        "bad",
        [
            [],
            "0.9",
            {f"{THEIR_CELL[0]},{THEIR_CELL[1]}": "0.9"},
            {f"{THEIR_CELL[0]},{THEIR_CELL[1]}": True},
            {f"{THEIR_CELL[0]},{THEIR_CELL[1]}": float("nan")},
            {f"{THEIR_CELL[0]},{THEIR_CELL[1]}": float("inf")},
            {f"{THEIR_CELL[0]},{THEIR_CELL[1]}": -0.1},
        ],
        ids=["list", "string", "text-value", "boolean", "nan", "infinity", "negative"],
    )
    def test_a_field_we_could_not_use_is_refused(self, bad: object) -> None:
        """A crash mid-match is a technical loss scoring zero for both sides."""
        with pytest.raises(CeremonyError):
            Reveal.from_dict({**reveal().to_dict(), "scent": bad})

    def test_an_unbounded_field_is_refused(self) -> None:
        """Bounded so a peer cannot be exhausted by one message."""
        huge = {f"{n},0": 0.1 for n in range(10_001)}
        with pytest.raises(CeremonyError):
            Reveal.from_dict({**reveal().to_dict(), "scent": huge})


class TestTheFieldIsBoundByThePhaseOneCommitment:
    """Sealed a phase before it is spoken, so it cannot answer the opponent."""

    def sealed(self, field: dict[str, float] | None) -> dict[str, object]:
        return step_record(BOARD, THEIR_ROLE, "N", "truth", "near the docks", scent=field)

    def audited(self, revealed: dict[str, float] | None, sealed: dict[str, float] | None) -> object:
        match = MatchCeremony(role=OUR_ROLE)
        step = match.at(1)
        step.commit(Commitment(step=1, sender=OUR_ROLE, commit="b" * 64, timestamp=WHEN), "0" * 32)
        step.receive(
            Commitment(
                step=1,
                sender=THEIR_ROLE,
                commit=commit_of(self.sealed(sealed), NONCE),
                timestamp=WHEN,
            )
        )
        step.acknowledge(WHEN)
        step.receive_ack(
            Acknowledgement(step=1, sender=THEIR_ROLE, acknowledges="b" * 64, timestamp=WHEN)
        )
        step.reveal(reveal(sender=OUR_ROLE))
        step.receive_reveal(reveal(scent=revealed))
        match.finish()
        disclosed = FinalReveal(sender=THEIR_ROLE, nonces={1: NONCE}, timestamp=WHEN)
        return audit_opponent(match, disclosed, {1: BOARD})

    def test_an_honest_field_audits_clean(self) -> None:
        field = field_at(THEIR_CELL)
        result = self.audited(field, field)
        assert result.clean, str(result)  # type: ignore[attr-defined]

    def test_a_field_changed_after_the_commit_fails_verification(self) -> None:
        """One cell edited between phase 1 and phase 3."""
        sealed = field_at(THEIR_CELL)
        cell = f"{THEIR_CELL[0]},{THEIR_CELL[1]}"
        result = self.audited({**sealed, cell: 0.899}, sealed)
        assert not result.clean  # type: ignore[attr-defined]

    def test_a_field_swapped_wholesale_fails_verification(self) -> None:
        result = self.audited(field_at((0, 0)), field_at(THEIR_CELL))
        assert not result.clean  # type: ignore[attr-defined]

    def test_dropping_the_field_at_reveal_fails_verification(self) -> None:
        """Sealing a field then claiming none is still a rewrite."""
        result = self.audited(None, field_at(THEIR_CELL))
        assert not result.clean  # type: ignore[attr-defined]
