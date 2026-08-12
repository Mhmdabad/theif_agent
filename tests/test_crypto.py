"""Tests for Commit-Reveal sealing.

Several of these pin the *wire format* rather than behaviour. That is
deliberate: the formula has to match the opponent's byte for byte, and a
formula difference does not degrade play — it voids a match both sides played
honestly, and the failure looks exactly like cheating.
"""

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import (
    NONCE_BYTES,
    CryptoError,
    audit,
    board_terms,
    canonical,
    commit_of,
    nonce,
    seal,
    step_record,
    verify,
)
from thief_agent.shared.config import canonical_bytes

SAMPLE = {"step": 3, "move": "N", "intent": "lie", "hint": "heading uptown"}
SRC = Path(__file__).parents[1] / "src" / "thief_agent"


class TestTheNonceGenerator:
    def test_it_is_the_agreed_length(self) -> None:
        assert len(nonce()) == NONCE_BYTES * 2

    def test_it_is_hexadecimal(self) -> None:
        """A shared alphabet, so neither side has to guess at an encoding."""
        assert set(nonce()) <= set("0123456789abcdef")

    def test_every_draw_is_different(self) -> None:
        """A repeated nonce repeats the digest, which is the one thing it exists
        to prevent — an opponent seeing the same commit twice learns the action
        repeated without ever opening it."""
        assert len({nonce() for _ in range(2000)}) == 2000

    def test_it_comes_from_the_csprng(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Named module, not merely random-looking output.

        Any test of *randomness* passes for a Mersenne Twister too, so the
        assertion is on the source rather than on the statistics.
        """
        called: list[int] = []

        def spy(size: int) -> str:
            called.append(size)
            return "ab" * size

        monkeypatch.setattr(secrets, "token_hex", spy)
        assert nonce() == "ab" * NONCE_BYTES
        assert called == [NONCE_BYTES]

    def test_the_crypto_module_never_imports_random(self) -> None:
        """The rulebook names ``secrets`` and calls ``random`` too predictable.

        ``random`` is a Mersenne Twister: its whole future follows from its
        state, and the state follows from enough observed output. A series
        hands the opponent hundreds of our nonces at the final reveal. This is
        an absence, and an absence is invisible until someone adds an import —
        by which point our commitments are pre-imageable.
        """
        source = (SRC / "domain" / "crypto.py").read_text()
        assert not re.search(r"^\s*(import random|from random import)", source, re.M)

    def test_randomness_elsewhere_is_seeded_rather_than_ambient(self) -> None:
        """Strategy randomness has the *opposite* requirement, and both are right.

        ``domain/bluff.py`` and ``strategy/base.py`` do import ``random``, and
        should: a decoy choice must be **reproducible**, or a replay of an
        honest match fails its own audit. What must never appear is a
        module-level call like ``random.choice(...)``, which is neither
        reproducible nor unpredictable — the worst of both.

        A nonce needs unpredictability; a tie-break needs reproducibility. The
        line between them is that a nonce comes from :mod:`secrets` and
        everything else comes from a seeded ``random.Random``.
        """
        ambient = [
            f"{path.relative_to(SRC)}: {hit}"
            for path in sorted(SRC.rglob("*.py"))
            for hit in re.findall(r"\brandom\.(?!Random\b)\w+\(", path.read_text())
        ]
        assert ambient == []


class TestCanonicalForm:
    def test_key_order_does_not_change_the_output(self) -> None:
        assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})

    def test_no_incidental_whitespace(self) -> None:
        rendered = canonical(SAMPLE)
        assert ", " not in rendered
        assert ": " not in rendered

    def test_non_ascii_stays_native_as_the_cohort_computes_it(self) -> None:
        """``ensure_ascii=False``, which the book's own ``commit()`` does not do.

        Its p. 37 code omits the flag, so Python's default escapes -- and this
        form used to match that. The digest exists so two independent
        implementations reproduce it, and the cohort's interop kit pins
        ``False``, as does the reference. A byte-exact rule only one team obeys
        is not a canonical form.

        The book's convention is not lost: :func:`book_commit_of` still computes
        it, so an opponent who implemented p. 37 literally still verifies.
        """
        assert canonical({"hint": "רחוב"}) == '{"hint":"רחוב"}'

    def test_utf8_survives_whatever_went_in(self) -> None:
        """Native throughout: Hebrew, accents and astral emoji alike."""
        rendered = canonical({"hint": "רחוב", "note": "café", "emoji": "🚓"})
        assert "רחוב" in rendered and "café" in rendered and "🚓" in rendered
        assert "\\u" not in rendered

    def test_there_is_only_one_canonical_form_for_our_own_artefacts(self) -> None:
        """Two that disagree is the same defect as none.

        The config digest, the scent lock and the transport freeze all hash
        through this one function. Step commitments are the deliberate
        exception — they are shared with the opponent, so ``commit_of``
        reproduces the reference implementation's serialisation instead, and
        ``TestCommitFormula`` pins that divergence rather than letting it
        look like an accident.
        """
        payload = {"b": "רחוב", "a": 1}
        assert canonical(payload).encode("utf-8") == canonical_bytes(payload)


class TestCommitFormula:
    def test_it_matches_the_reference_implementations_own_commit(self) -> None:
        """The cohort's code appends the nonce after a pipe, unescaped.

        This module used to fold the nonce into the record — the book's p. 37
        construction, perfectly sound, and the wrong one to send: the
        reference's auditor recomputes only its own form, so a cohort-derived
        opponent would fail every one of our steps and report a clean match
        as tampered.
        """
        secret = "abc123"
        text = json.dumps(SAMPLE, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        wire = hashlib.sha256(f"{text}|{secret}".encode()).hexdigest()
        assert commit_of(SAMPLE, secret) == wire

    def test_folding_the_nonce_into_the_record_gives_a_different_digest(self) -> None:
        """The book's construction, pinned as *not* what we send.

        ``verify`` still opens it — an opponent that implemented the book
        literally is honest — but what leaves this agent is the wire form.
        """
        secret = "abc123"
        folded = hashlib.sha256(canonical_bytes({**SAMPLE, "nonce": secret})).hexdigest()
        assert commit_of(SAMPLE, secret) != folded
        verify(SAMPLE, secret, folded)

    def test_a_payload_carrying_its_own_nonce_still_hashes(self) -> None:
        """Total over dicts, exactly like the reference.

        ``verify`` recomputes *opponents'* payloads through this function. A
        guard here would turn a record their sealer accepted into a tampering
        verdict; the guard against double-noncing our own records lives at
        ``seal``, the only door our records come through.
        """
        weird = {**SAMPLE, "nonce": "already-in-the-record"}
        assert commit_of(weird, "abc123") == commit_of(weird, "abc123")
        assert commit_of(weird, "abc123") != commit_of(weird, "different")

    def test_is_stable_across_calls(self) -> None:
        assert commit_of(SAMPLE, "n") == commit_of(SAMPLE, "n")

    def test_key_order_does_not_change_the_commit(self) -> None:
        reordered = dict(reversed(list(SAMPLE.items())))
        assert commit_of(SAMPLE, "n") == commit_of(reordered, "n")

    def test_any_payload_change_changes_the_commit(self) -> None:
        assert commit_of(SAMPLE, "n") != commit_of({**SAMPLE, "move": "S"}, "n")

    def test_any_nonce_change_changes_the_commit(self) -> None:
        assert commit_of(SAMPLE, "n1") != commit_of(SAMPLE, "n2")

    def test_a_known_fixture_pins_the_digest(self) -> None:
        """Exchange this with an opponent before the first counted match."""
        digest = commit_of({"move": "N", "step": 1}, "0" * 32)
        expected = hashlib.sha256(b'{"move":"N","step":1}|' + b"0" * 32).hexdigest()
        assert digest == expected
        assert len(digest) == 64


class TestSeal:
    def test_returns_a_nonce_and_a_commit(self) -> None:
        sealed = seal(SAMPLE)
        assert set(sealed) == {"nonce", "commit"}

    def test_the_nonce_is_the_agreed_length(self) -> None:
        assert len(seal(SAMPLE)["nonce"]) == NONCE_BYTES * 2

    def test_nonces_are_fresh_each_time(self) -> None:
        """Repeating an action must not repeat the digest."""
        assert seal(SAMPLE)["commit"] != seal(SAMPLE)["commit"]

    def test_the_sealed_commit_verifies(self) -> None:
        sealed = seal(SAMPLE)
        verify(SAMPLE, sealed["nonce"], sealed["commit"])

    def test_a_payload_carrying_its_own_nonce_is_refused_at_sealing(self) -> None:
        """Our records never legitimately arrive here with one.

        Sealing draws its own nonce; a caller passing a payload that already
        holds a ``nonce`` key has confused the record shape with this layer,
        and the confusion is better refused loudly than double-nonced.
        """
        with pytest.raises(CryptoError, match="draws its own"):
            seal({**SAMPLE, "nonce": "already"})


class TestVerify:
    def test_an_honest_reveal_passes(self) -> None:
        verify(SAMPLE, "n", commit_of(SAMPLE, "n"))

    def test_a_changed_move_is_caught(self) -> None:
        with pytest.raises(CryptoError, match="commit mismatch"):
            verify({**SAMPLE, "move": "S"}, "n", commit_of(SAMPLE, "n"))

    def test_a_changed_hint_is_caught(self) -> None:
        with pytest.raises(CryptoError):
            verify({**SAMPLE, "hint": "downtown"}, "n", commit_of(SAMPLE, "n"))

    def test_a_wrong_nonce_is_caught(self) -> None:
        with pytest.raises(CryptoError):
            verify(SAMPLE, "wrong", commit_of(SAMPLE, "n"))

    def test_the_error_shows_both_digests_truncated(self) -> None:
        with pytest.raises(CryptoError, match="declared .*recomputed"):
            verify(SAMPLE, "wrong", commit_of(SAMPLE, "n"))


class TestAudit:
    def _record(self, payload: dict[str, object]) -> dict[str, object]:
        return {"payload": payload, **seal(payload)}

    def test_an_honest_match_passes(self) -> None:
        audit([self._record({"step": n, "move": "N"}) for n in range(35)])

    def test_a_single_tampered_step_is_caught(self) -> None:
        records = [self._record({"step": n, "move": "N"}) for n in range(5)]
        records[3]["payload"] = {"step": 3, "move": "S"}
        with pytest.raises(CryptoError, match="tampering at step 3"):
            audit(records)

    def test_the_failing_step_is_named(self) -> None:
        """Both teams must agree the result; the step number is what they agree on."""
        records = [self._record({"step": n, "move": "N"}) for n in range(10)]
        records[7]["payload"] = {"step": 7, "move": "W"}
        with pytest.raises(CryptoError, match="step 7"):
            audit(records)

    def test_a_malformed_record_is_reported_not_crashed(self) -> None:
        with pytest.raises(CryptoError, match="missing 'nonce'"):
            audit([{"payload": {"step": 0}, "commit": "x"}])

    def test_an_empty_audit_passes(self) -> None:
        audit([])


BOARD = BoardState(
    grid_size=8, cop=(1, 2), thief=(6, 5), barriers=frozenset({(3, 3), (0, 1)}), step=4
)


class TestWhatABoardStateSeals:
    def test_it_seals_our_own_cell(self) -> None:
        assert board_terms(BOARD, "police")["self"] == [1, 2]
        assert board_terms(BOARD, "thief")["self"] == [6, 5]

    def test_it_never_seals_our_belief_about_the_opponent(self) -> None:
        """A sealed belief is a number we could have written afterwards.

        Neither peer can check the other's belief, so sealing it buys nothing
        while looking like it buys something — and the audit is then unable to
        say anything about the field at all.
        """
        terms = board_terms(BOARD, "police")
        assert "thief" not in terms
        assert [6, 5] not in terms.values()

    def test_every_sealed_field_is_checkable_by_the_opponent(self) -> None:
        """Grid size, step, our revealed cell and the declared barriers."""
        assert set(board_terms(BOARD, "police")) == {"grid_size", "step", "self", "barriers"}

    def test_barriers_are_sorted_so_set_order_cannot_reach_the_digest(self) -> None:
        shuffled = BoardState(
            grid_size=8, cop=(1, 2), thief=(6, 5), barriers=frozenset({(0, 1), (3, 3)}), step=4
        )
        assert board_terms(BOARD, "police") == board_terms(shuffled, "police")
        assert board_terms(BOARD, "police")["barriers"] == [[0, 1], [3, 3]]

    def test_positions_are_lists_because_that_is_what_survives_json(self) -> None:
        """A tuple goes out as a list and comes back as one.

        A peer re-hashing a parsed record would otherwise get a different
        digest from one hashing its own, which is tampering as far as the
        audit can tell.
        """
        terms = board_terms(BOARD, "police")
        assert json.loads(canonical(terms)) == terms

    def test_the_step_binds_the_commitment_to_one_turn(self) -> None:
        """Anti-replay: an old commitment cannot be reused in a new context."""
        later = BoardState(grid_size=8, cop=(1, 2), thief=(6, 5), barriers=BOARD.barriers, step=5)
        assert board_terms(BOARD, "police") != board_terms(later, "police")

    def test_a_role_the_wire_does_not_name_is_refused(self) -> None:
        with pytest.raises(CryptoError, match="role must be one of"):
            board_terms(BOARD, "cop")


class TestTheFullStepRecord:
    def record(self, **overrides: object) -> dict[str, object]:
        fields: dict[str, Any] = {
            "state": BOARD,
            "role": "police",
            "move": "N",
            "intent": "lie",
            "hint": "heading uptown",
        }
        return step_record(**{**fields, **overrides})

    def test_it_carries_the_four_named_fields_and_the_four_implied_ones(self) -> None:
        """The rulebook names State, Move, Intent, Nonce and then says the real
        record also holds the hint, the intent classification, the step and the
        role. The nonce joins at commit time, and the scent field joins because
        it is disclosed a phase later than the commitment that fixes it."""
        assert set(self.record()) == {
            "state",
            "role",
            "move",
            "intent",
            "hint",
            "barrier_placed",
            "scent",
            "game_uid",
            "sub_game",
        }
        assert self.record()["state"]["step"] == 4  # type: ignore[index]

    def test_a_barrier_placement_is_sealed(self) -> None:
        """The one move that changes the board permanently.

        A cop able to re-describe where it built afterwards would hold the most
        valuable rewrite available to either side.
        """
        assert self.record(barrier_placed=(2, 2))["barrier_placed"] == [2, 2]

    def test_a_turn_without_a_barrier_seals_null_rather_than_omitting_the_key(self) -> None:
        """Both sides serialise the same shape, so a thief's null is a fact
        about the turn rather than a difference in format."""
        assert self.record()["barrier_placed"] is None
        assert self.record(role="thief")["barrier_placed"] is None

    def test_changing_any_field_changes_the_commitment(self) -> None:
        base = commit_of(self.record(), "n")
        for changed in (
            self.record(move="S"),
            self.record(intent="truth"),
            self.record(hint="downtown"),
            self.record(barrier_placed=(2, 2)),
        ):
            assert commit_of(changed, "n") != base

    def test_it_round_trips_through_json_unchanged(self) -> None:
        """The audit re-hashes a record that has crossed the wire."""
        sealed = self.record(barrier_placed=(2, 2))
        assert commit_of(json.loads(canonical(sealed)), "n") == commit_of(sealed, "n")

    def test_a_sealed_record_verifies(self) -> None:
        sealed = self.record(barrier_placed=(2, 2))
        opened = seal(sealed)
        verify(sealed, opened["nonce"], opened["commit"])
