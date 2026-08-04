"""Phase 1 of the Commit-Reveal ceremony: the hash, and nothing else."""

import json
from pathlib import Path

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.infra.ceremony import (
    ACK_FIELDS,
    COMMIT_FIELDS,
    REVEAL_FIELDS,
    Acknowledgement,
    CeremonyError,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
    StepCeremony,
    Verdict,
    audit_opponent,
    verify_step,
)

SRC = Path(__file__).parents[1] / "src" / "thief_agent"
DIGEST = "a" * 64
WHEN = "2026-08-04T09:00:00+00:00"
OUR_NONCE = "0" * 32
THEIR_NONCE = "1" * 32
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


THEIR_DIGEST = "b" * 64


def their_commitment(**overrides: object) -> Commitment:
    fields: dict[str, object] = {
        "step": 4,
        "sender": "police",
        "commit": THEIR_DIGEST,
        "timestamp": WHEN,
    }
    return Commitment(**{**fields, **overrides})  # type: ignore[arg-type]


def opened() -> StepCeremony:
    """Both sides committed, nothing acknowledged yet."""
    ceremony = StepCeremony(step=4, role="thief")
    ceremony.commit(commitment(), OUR_NONCE)
    ceremony.receive(their_commitment())
    return ceremony


def both_locked() -> StepCeremony:
    ceremony = opened()
    ceremony.acknowledge(WHEN)
    ceremony.receive_ack(
        Acknowledgement(step=4, sender="police", acknowledges=DIGEST, timestamp=WHEN)
    )
    return ceremony


class TestTheAcknowledgementMessage:
    def test_it_names_the_digest_rather_than_saying_yes(self) -> None:
        """A bare yes is unfalsifiable.

        A peer that later claims it acknowledged a *different* commitment
        cannot be contradicted by one, and the whole phase turns on being able
        to say precisely what was locked.
        """
        ack = opened().acknowledge(WHEN)
        assert ack.acknowledges == THEIR_DIGEST
        assert tuple(ack.to_dict()) == ACK_FIELDS

    def test_it_round_trips_through_json(self) -> None:
        ack = opened().acknowledge(WHEN)
        assert Acknowledgement.from_dict(json.loads(json.dumps(ack.to_dict()))) == ack

    @pytest.mark.parametrize("digest", ["a" * 63, "A" * 64, "", "zz"])
    def test_it_refuses_a_digest_that_is_not_one(self, digest: str) -> None:
        with pytest.raises(CeremonyError, match="64 lowercase hex"):
            Acknowledgement(step=4, sender="thief", acknowledges=digest, timestamp=WHEN)

    @pytest.mark.parametrize("sender", ["cop", "referee", ""])
    def test_it_refuses_a_role_the_wire_does_not_name(self, sender: str) -> None:
        with pytest.raises(CeremonyError, match="sender must be one of"):
            Acknowledgement(step=4, sender=sender, acknowledges=DIGEST, timestamp=WHEN)

    def test_it_refuses_a_negative_step(self) -> None:
        with pytest.raises(CeremonyError, match="step must be >= 0"):
            Acknowledgement(step=-1, sender="thief", acknowledges=DIGEST, timestamp=WHEN)

    @pytest.mark.parametrize(
        "payload",
        ["not a mapping", {}, {"step": 4, "sender": "thief", "acknowledges": DIGEST}],
    )
    def test_a_malformed_acknowledgement_is_one_error_type(self, payload: object) -> None:
        with pytest.raises(CeremonyError):
            Acknowledgement.from_dict(payload)


class TestCommittingOnce:
    def test_a_second_commitment_of_ours_is_refused(self) -> None:
        """Re-committing is the move this ceremony exists to prevent.

        It is not less serious for happening locally: the commitment has
        already gone out, so a second one is a rewrite whether or not anyone
        else has seen it yet.
        """
        ceremony = StepCeremony(step=4, role="thief")
        ceremony.commit(commitment(), OUR_NONCE)
        with pytest.raises(CeremonyError, match="not revisable"):
            ceremony.commit(commitment(commit="c" * 64), OUR_NONCE)

    def test_a_second_commitment_of_theirs_is_refused(self) -> None:
        """Either a bug on their side or an attempt to replace a move.

        We cannot tell which, and both end the same way.
        """
        ceremony = opened()
        with pytest.raises(CeremonyError, match="already locked"):
            ceremony.receive(their_commitment(commit="c" * 64))

    def test_a_commitment_for_another_step_is_refused(self) -> None:
        ceremony = StepCeremony(step=4, role="thief")
        with pytest.raises(CeremonyError, match="is for step 9"):
            ceremony.commit(commitment(step=9), OUR_NONCE)

    def test_our_own_role_is_expected_on_our_commitment(self) -> None:
        ceremony = StepCeremony(step=4, role="thief")
        with pytest.raises(CeremonyError, match="expected 'thief'"):
            ceremony.commit(their_commitment(), OUR_NONCE)

    def test_the_opponents_role_is_expected_on_theirs(self) -> None:
        ceremony = StepCeremony(step=4, role="thief")
        with pytest.raises(CeremonyError, match="expected 'police'"):
            ceremony.receive(commitment())


class TestAcknowledging:
    def test_acknowledging_nothing_is_refused(self) -> None:
        """Worse than not acknowledging.

        It tells them they may reveal, against a step we have no record of and
        therefore cannot check afterwards.
        """
        ceremony = StepCeremony(step=4, role="thief")
        ceremony.commit(commitment(), OUR_NONCE)
        with pytest.raises(CeremonyError, match="has not committed"):
            ceremony.acknowledge(WHEN)

    def test_an_acknowledgement_before_we_commit_is_refused(self) -> None:
        ceremony = StepCeremony(step=4, role="thief")
        with pytest.raises(CeremonyError, match="before we committed"):
            ceremony.receive_ack(
                Acknowledgement(step=4, sender="police", acknowledges=DIGEST, timestamp=WHEN)
            )

    def test_an_acknowledgement_of_some_other_digest_is_refused(self) -> None:
        """Not a weaker lock — a lock on a commitment we never made."""
        ceremony = opened()
        with pytest.raises(CeremonyError, match="never made"):
            ceremony.receive_ack(
                Acknowledgement(step=4, sender="police", acknowledges="c" * 64, timestamp=WHEN)
            )

    def test_an_acknowledgement_from_the_wrong_role_is_refused(self) -> None:
        ceremony = opened()
        with pytest.raises(CeremonyError, match="expected 'police'"):
            ceremony.receive_ack(
                Acknowledgement(step=4, sender="thief", acknowledges=DIGEST, timestamp=WHEN)
            )


class TestTheLockGate:
    def test_nothing_is_locked_before_anything_happens(self) -> None:
        assert not StepCeremony(step=4, role="thief").locked

    def test_two_commitments_alone_are_not_a_lock(self) -> None:
        """Both have chosen; neither has said so, so either can still deny it."""
        assert not opened().locked

    def test_our_acknowledgement_alone_is_not_a_lock(self) -> None:
        ceremony = opened()
        ceremony.acknowledge(WHEN)
        assert not ceremony.locked

    def test_theirs_alone_is_not_a_lock(self) -> None:
        ceremony = opened()
        ceremony.receive_ack(
            Acknowledgement(step=4, sender="police", acknowledges=DIGEST, timestamp=WHEN)
        )
        assert not ceremony.locked

    def test_all_four_parts_are_a_lock(self) -> None:
        """The gate the rulebook puts between Commit and Reveal.

        Three out of four is a peer that can still change its mind.
        """
        assert both_locked().locked

    def test_the_opponent_is_whichever_role_is_not_ours(self) -> None:
        assert StepCeremony(step=4, role="thief").opponent == "police"
        assert StepCeremony(step=4, role="police").opponent == "thief"

    def test_a_ceremony_needs_a_real_role(self) -> None:
        with pytest.raises(CeremonyError, match="role must be one of"):
            StepCeremony(step=4, role="cop")


def reveal(**overrides: object) -> Reveal:
    fields: dict[str, object] = {
        "step": 4,
        "sender": "thief",
        "move": "N",
        "intent": "lie",
        "hint": "heading uptown",
        "timestamp": WHEN,
    }
    return Reveal(**{**fields, **overrides})  # type: ignore[arg-type]


class TestTheNonceStaysHidden:
    def test_the_wire_form_has_no_nonce(self) -> None:
        """One exposed nonce weakens every *other* commitment in the match.

        They all use the same construction, so an opponent holding one turns
        the rest into hashes whose only unknown is a five-way move — with
        steps still left to play against them.
        """
        assert tuple(reveal().to_dict()) == REVEAL_FIELDS
        assert "nonce" not in json.dumps(reveal().to_dict())

    def test_an_inbound_nonce_is_refused_rather_than_ignored(self) -> None:
        """The one stray field this module will not quietly drop.

        Reading less is normally safe. A nonce is different: its early arrival
        means the opponent has misunderstood the ceremony, and continuing
        leaves us holding a secret we are not supposed to have yet.
        """
        with pytest.raises(CeremonyError, match="carries a nonce"):
            Reveal.from_dict({**reveal().to_dict(), "nonce": "0" * 32})

    def test_it_round_trips_through_json(self) -> None:
        opened = reveal(barrier_placed=[2, 2])
        assert Reveal.from_dict(json.loads(json.dumps(opened.to_dict()))) == opened

    @pytest.mark.parametrize("intent", ["maybe", "TRUTH", ""])
    def test_an_intent_outside_the_two_is_refused(self, intent: str) -> None:
        with pytest.raises(CeremonyError, match="intent must be one of"):
            reveal(intent=intent)

    @pytest.mark.parametrize("sender", ["cop", "referee", ""])
    def test_a_role_the_wire_does_not_name_is_refused(self, sender: str) -> None:
        with pytest.raises(CeremonyError, match="sender must be one of"):
            reveal(sender=sender)

    def test_a_negative_step_is_refused(self) -> None:
        with pytest.raises(CeremonyError, match="step must be >= 0"):
            reveal(step=-1)

    @pytest.mark.parametrize(
        "payload", ["not a mapping", {}, {"step": 4, "sender": "thief", "move": "N"}]
    )
    def test_a_malformed_reveal_is_one_error_type(self, payload: object) -> None:
        with pytest.raises(CeremonyError):
            Reveal.from_dict(payload)


class TestRevealingIsGatedOnTheLock:
    def test_a_locked_pair_may_reveal(self) -> None:
        ceremony = both_locked()
        assert ceremony.reveal(reveal()) is ceremony.revealed_ours

    @pytest.mark.parametrize("build", [StepCeremony, lambda **k: opened()])
    def test_revealing_before_the_lock_is_refused(self, build: object) -> None:
        """Not an efficiency — it hands over our move while theirs can change.

        Which is the one thing the acknowledgement was for.
        """
        ceremony = build(step=4, role="thief")  # type: ignore[operator]
        with pytest.raises(CeremonyError, match="before both sides are locked"):
            ceremony.reveal(reveal())

    def test_the_error_names_what_is_still_missing(self) -> None:
        """A ceremony stalled at three of four is a question, not a mystery."""
        ceremony = opened()
        ceremony.acknowledge(WHEN)
        with pytest.raises(CeremonyError, match="missing their acknowledgement"):
            ceremony.reveal(reveal())

    def test_a_second_reveal_is_refused(self) -> None:
        ceremony = both_locked()
        ceremony.reveal(reveal())
        with pytest.raises(CeremonyError, match="not revisable"):
            ceremony.reveal(reveal(move="S"))

    def test_a_reveal_from_the_wrong_role_is_refused(self) -> None:
        with pytest.raises(CeremonyError, match="expected 'thief'"):
            both_locked().reveal(reveal(sender="police"))


class TestReceivingTheirReveal:
    def test_a_locked_pair_may_be_believed(self) -> None:
        ceremony = both_locked()
        theirs = reveal(sender="police", move="S")
        assert ceremony.receive_reveal(theirs) is ceremony.revealed_theirs

    def test_it_cannot_be_verified_when_it_is_acted_upon(self) -> None:
        """The gap is the design, not a weakness in it.

        The digest cannot be recomputed without their nonce, so the reveal is
        believed on the strength of the lock and checked only at the audit —
        which is why an audit failure is unappealable rather than negotiable.
        """
        ceremony = both_locked()
        theirs = reveal(sender="police", move="S")
        ceremony.receive_reveal(theirs)
        assert ceremony.theirs is not None
        assert "nonce" not in json.dumps(theirs.to_dict())

    def test_storing_it_is_the_whole_job(self) -> None:
        """A reveal we did not keep is a step the audit cannot re-derive."""
        ceremony = both_locked()
        ceremony.receive_reveal(reveal(sender="police", move="S", barrier_placed=None))
        assert ceremony.revealed_theirs is not None
        assert ceremony.revealed_theirs.move == "S"

    def test_a_reveal_before_the_lock_is_refused(self) -> None:
        """Accepting it would reward revealing early."""
        with pytest.raises(CeremonyError, match="before both sides were locked"):
            opened().receive_reveal(reveal(sender="police"))

    def test_a_second_reveal_from_them_is_refused(self) -> None:
        """It would replace an action we have already acted on."""
        ceremony = both_locked()
        ceremony.receive_reveal(reveal(sender="police"))
        with pytest.raises(CeremonyError, match="already revealed"):
            ceremony.receive_reveal(reveal(sender="police", move="W"))

    def test_their_reveal_must_come_from_them(self) -> None:
        with pytest.raises(CeremonyError, match="expected 'police'"):
            both_locked().receive_reveal(reveal())

    def test_pending_reads_as_locked_once_it_is(self) -> None:
        assert both_locked().pending() == "locked"


def played(steps: int = 3, role: str = "thief") -> MatchCeremony:
    """A match whose steps all committed, from our side."""
    match = MatchCeremony(role=role)
    for step in range(1, steps + 1):
        match.at(step).commit(commitment(step=step), OUR_NONCE)
    return match


class TestTheFinalRevealMessage:
    def test_it_carries_every_nonce_keyed_by_step(self) -> None:
        match = played()
        match.finish()
        assert match.final_reveal(WHEN).nonces == {1: OUR_NONCE, 2: OUR_NONCE, 3: OUR_NONCE}

    def test_step_keys_become_strings_on_the_wire(self) -> None:
        """JSON has no integer keys, so the conversion is explicit."""
        match = played(steps=1)
        match.finish()
        assert match.final_reveal(WHEN).to_dict()["nonces"] == {"1": OUR_NONCE}

    def test_it_round_trips_through_json(self) -> None:
        match = played()
        match.finish()
        disclosed = match.final_reveal(WHEN)
        assert FinalReveal.from_dict(json.loads(json.dumps(disclosed.to_dict()))) == disclosed

    @pytest.mark.parametrize("bad", ["0" * 31, "0" * 33, "Z" * 32, ""])
    def test_a_nonce_that_is_not_one_is_refused(self, bad: str) -> None:
        with pytest.raises(CeremonyError, match="hex characters"):
            FinalReveal(sender="thief", nonces={1: bad}, timestamp=WHEN)

    @pytest.mark.parametrize("sender", ["cop", "referee", ""])
    def test_a_role_the_wire_does_not_name_is_refused(self, sender: str) -> None:
        with pytest.raises(CeremonyError, match="sender must be one of"):
            FinalReveal(sender=sender, nonces={1: OUR_NONCE}, timestamp=WHEN)

    def test_a_negative_step_is_refused(self) -> None:
        with pytest.raises(CeremonyError, match="step must be >= 0"):
            FinalReveal(sender="thief", nonces={-1: OUR_NONCE}, timestamp=WHEN)

    def test_a_step_key_that_is_not_an_integer_is_refused(self) -> None:
        """Refused rather than skipped.

        A nonce we cannot file against a step verifies nothing, and dropping
        it silently would turn their formatting error into our unverifiable
        step.
        """
        with pytest.raises(CeremonyError, match="not an integer"):
            FinalReveal.from_dict(
                {"sender": "thief", "nonces": {"one": OUR_NONCE}, "timestamp": WHEN}
            )

    @pytest.mark.parametrize(
        "payload",
        [
            "not a mapping",
            {"sender": "thief", "timestamp": WHEN},
            {"sender": "thief", "nonces": [], "timestamp": WHEN},
            {"sender": "thief", "nonces": {"1": 42}, "timestamp": WHEN},
        ],
    )
    def test_a_malformed_final_reveal_is_one_error_type(self, payload: object) -> None:
        with pytest.raises(CeremonyError):
            FinalReveal.from_dict(payload)


class TestNoncesAreDisclosedOnlyAtTheEnd:
    def test_disclosing_mid_match_is_refused(self) -> None:
        """Every step uses the same construction.

        One nonce released early reopens its own commitment and narrows every
        other one, with steps still left to play against them.
        """
        with pytest.raises(CeremonyError, match="while the match is running"):
            played().final_reveal(WHEN)

    def test_the_nonce_never_leaves_by_any_other_path(self) -> None:
        """Commitment cannot carry it and Reveal refuses it.

        Holding it on the ceremony rather than in the caller is what makes the
        final reveal the only route to the wire.
        """
        ceremony = both_locked()
        assert ceremony.our_nonce == OUR_NONCE
        assert OUR_NONCE not in json.dumps(commitment().to_dict())
        assert OUR_NONCE not in json.dumps(reveal().to_dict())

    def test_a_malformed_nonce_is_refused_at_commit_time(self) -> None:
        ceremony = StepCeremony(step=4, role="thief")
        with pytest.raises(CeremonyError, match="hex characters"):
            ceremony.commit(commitment(), "not-a-nonce")


class TestAPartialRevealIsRefused:
    def test_a_step_with_no_recorded_nonce_stops_the_reveal(self) -> None:
        """The step a cheat would omit.

        A step nobody can re-derive proves nothing at audit, which makes a
        partial reveal worse than a late one.
        """
        match = played(steps=2)
        match.at(7)  # opened but never committed
        match.finish()
        with pytest.raises(CeremonyError, match=r"no nonce recorded for step\(s\) \[7\]"):
            match.final_reveal(WHEN)

    def test_their_reveal_must_cover_every_step_they_committed_to(self) -> None:
        """An unopenable commitment is indistinguishable from a hidden move."""
        match = MatchCeremony(role="thief")
        for step in (1, 2):
            match.at(step).receive(their_commitment(step=step))
        with pytest.raises(CeremonyError, match=r"omits step\(s\) \[2\]"):
            match.receive_final_reveal(
                FinalReveal(sender="police", nonces={1: THEIR_NONCE}, timestamp=WHEN)
            )

    def test_extra_steps_in_their_reveal_are_tolerated(self) -> None:
        """A nonce for a step we have no record of verifies nothing and harms nothing."""
        match = MatchCeremony(role="thief")
        match.at(1).receive(their_commitment(step=1))
        disclosed = FinalReveal(
            sender="police", nonces={1: THEIR_NONCE, 9: THEIR_NONCE}, timestamp=WHEN
        )
        assert match.receive_final_reveal(disclosed) is disclosed

    def test_a_final_reveal_from_the_wrong_role_is_refused(self) -> None:
        match = MatchCeremony(role="thief")
        with pytest.raises(CeremonyError, match="expected 'police'"):
            match.receive_final_reveal(FinalReveal(sender="thief", nonces={}, timestamp=WHEN))


class TestTheMatchCeremony:
    def test_it_opens_a_step_on_first_reference_and_reuses_it(self) -> None:
        match = MatchCeremony(role="thief")
        assert match.at(3) is match.at(3)
        assert match.at(3).role == "thief"

    def test_it_needs_a_real_role(self) -> None:
        with pytest.raises(CeremonyError, match="role must be one of"):
            MatchCeremony(role="cop")

    def test_the_opponent_is_whichever_role_is_not_ours(self) -> None:
        assert MatchCeremony(role="thief").opponent == "police"
        assert MatchCeremony(role="police").opponent == "thief"


def sealed_state(step: int) -> BoardState:
    return BoardState(grid_size=8, cop=(1, 2), thief=(6, 5), barriers=frozenset(), step=step)


def honest_match(steps: int = 3) -> tuple[MatchCeremony, FinalReveal, dict[int, BoardState]]:
    """A match the opponent played straight, from our side of the wire."""
    match = MatchCeremony(role="thief")
    states = {step: sealed_state(step) for step in range(1, steps + 1)}
    nonces: dict[int, str] = {}
    for step in range(1, steps + 1):
        record = step_record(states[step], "police", "S", "truth", f"hint {step}")
        their_nonce = f"{step:032x}"
        nonces[step] = their_nonce
        ceremony = match.at(step)
        ceremony.commit(commitment(step=step), OUR_NONCE)
        ceremony.receive(their_commitment(step=step, commit=commit_of(record, their_nonce)))
        ceremony.acknowledge(WHEN)
        ceremony.receive_ack(
            Acknowledgement(step=step, sender="police", acknowledges=DIGEST, timestamp=WHEN)
        )
        ceremony.receive_reveal(
            reveal(step=step, sender="police", move="S", intent="truth", hint=f"hint {step}")
        )
    return match, FinalReveal(sender="police", nonces=nonces, timestamp=WHEN), states


class TestAnHonestMatchAuditsClean:
    def test_every_step_is_re_derived_and_matches(self) -> None:
        match, disclosed, states = honest_match()
        result = audit_opponent(match, disclosed, states)
        assert result.clean
        assert result.checked == 3
        assert "3 steps re-derived, all matching" in str(result)

    def test_a_step_they_never_committed_to_is_not_audited(self) -> None:
        """We open a ceremony on our own first message.

        A step where only *we* committed is a step they owe nothing for, and
        counting it would manufacture a failure out of our own bookkeeping.
        """
        match, disclosed, states = honest_match()
        match.at(9).commit(commitment(step=9), OUR_NONCE)
        result = audit_opponent(match, disclosed, states)
        assert result.clean
        assert result.checked == 3

    def test_a_match_with_nothing_committed_is_vacuously_clean(self) -> None:
        result = audit_opponent(MatchCeremony(role="thief"), FinalReveal("police", {}, WHEN), {})
        assert result.clean
        assert result.checked == 0


class TestForgeryIsCaught:
    def test_a_move_changed_after_the_commitment_fails(self) -> None:
        """The whole point: they committed to one move and revealed another."""
        match, disclosed, states = honest_match()
        match.steps[2].revealed_theirs = reveal(
            step=2, sender="police", move="W", intent="truth", hint="hint 2"
        )
        result = audit_opponent(match, disclosed, states)
        assert result.verdict is Verdict.FORGED
        assert len(result.failures) == 1
        assert "step 2" in result.failures[0]

    def test_a_changed_hint_fails_too(self) -> None:
        """The sentence is inside the commitment, so it cannot be revised either."""
        match, disclosed, states = honest_match()
        match.steps[1].revealed_theirs = reveal(
            step=1, sender="police", move="S", intent="truth", hint="a different story"
        )
        assert audit_opponent(match, disclosed, states).verdict is Verdict.FORGED

    def test_a_flipped_intent_fails(self) -> None:
        """No claiming afterwards that a lie was meant honestly."""
        match, disclosed, states = honest_match()
        match.steps[1].revealed_theirs = reveal(
            step=1, sender="police", move="S", intent="lie", hint="hint 1"
        )
        assert audit_opponent(match, disclosed, states).verdict is Verdict.FORGED

    def test_a_substituted_nonce_fails(self) -> None:
        match, disclosed, states = honest_match()
        swapped = FinalReveal("police", {**disclosed.nonces, 3: "f" * 32}, WHEN)
        assert audit_opponent(match, swapped, states).verdict is Verdict.FORGED

    def test_the_failure_states_arithmetic_both_sides_can_run(self) -> None:
        """ "You cheated" is not a claim anyone concedes.

        Both teams must agree a result before either may report it, so the
        failure names the digest committed and the digest their own revealed
        move produces — they can run the same arithmetic and get the same
        answer.
        """
        match, disclosed, states = honest_match()
        match.steps[1].revealed_theirs = reveal(
            step=1, sender="police", move="W", intent="truth", hint="hint 1"
        )
        failure = audit_opponent(match, disclosed, states).failures[0]
        assert "committed" in failure and "produces" in failure and "'W'" in failure

    def test_every_step_is_checked_rather_than_stopping_at_the_first(self) -> None:
        """A dispute settled on one step tends to be reopened on the next."""
        match, disclosed, states = honest_match()
        for step in (1, 3):
            match.steps[step].revealed_theirs = reveal(
                step=step, sender="police", move="W", intent="truth", hint=f"hint {step}"
            )
        result = audit_opponent(match, disclosed, states)
        assert len(result.failures) == 2
        assert result.checked == 3


class TestUnprovableIsReportedSeparatelyFromProven:
    def test_a_commitment_never_revealed(self) -> None:
        """Not the same accusation as a wrong digest, and not provable tampering."""
        match, disclosed, states = honest_match()
        match.steps[2].revealed_theirs = None
        result = audit_opponent(match, disclosed, states)
        assert "never revealed" in result.failures[0]

    def test_a_commitment_with_no_nonce_disclosed(self) -> None:
        match, disclosed, states = honest_match()
        thin = FinalReveal("police", {k: v for k, v in disclosed.nonces.items() if k != 2}, WHEN)
        assert "no nonce disclosed" in audit_opponent(match, thin, states).failures[0]

    def test_a_step_we_cannot_rebuild_the_board_for(self) -> None:
        match, disclosed, states = honest_match()
        del states[3]
        assert "no board state" in audit_opponent(match, disclosed, states).failures[0]


class TestVerifyStep:
    def test_an_honest_record_verifies(self) -> None:
        record = step_record(sealed_state(1), "police", "S", "truth", "hint")
        assert verify_step(record, THEIR_NONCE, commit_of(record, THEIR_NONCE))

    def test_a_changed_record_does_not(self) -> None:
        record = step_record(sealed_state(1), "police", "S", "truth", "hint")
        commit = commit_of(record, THEIR_NONCE)
        changed = step_record(sealed_state(1), "police", "N", "truth", "hint")
        assert not verify_step(changed, THEIR_NONCE, commit)

    def test_it_uses_a_constant_time_comparison(self) -> None:
        """The rulebook names ``compare_digest``.

        Being honest about why: by audit time both digests are public, so the
        timing channel leaks nothing. The reason to use it anyway is that
        ``==`` on a digest is a habit, and the habit is what eventually reaches
        a comparison where timing does matter.
        """
        source = (SRC / "infra" / "ceremony.py").read_text()
        assert "secrets.compare_digest(" in source
