"""Tests for Commit-Reveal sealing.

Several of these pin the *wire format* rather than behaviour. That is
deliberate: the formula has to match the opponent's byte for byte, and a
formula difference does not degrade play — it voids a match both sides played
honestly, and the failure looks exactly like cheating.
"""

import hashlib
import json

import pytest

from thief_agent.domain.crypto import (
    NONCE_BYTES,
    CryptoError,
    audit,
    canonical,
    commit_of,
    seal,
    verify,
)

SAMPLE = {"step": 3, "move": "N", "intent": "lie", "hint": "heading uptown"}


class TestCanonicalForm:
    def test_key_order_does_not_change_the_output(self) -> None:
        assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})

    def test_no_incidental_whitespace(self) -> None:
        rendered = canonical(SAMPLE)
        assert ", " not in rendered
        assert ": " not in rendered

    def test_non_ascii_is_not_escaped(self) -> None:
        """ensure_ascii defaults to True and would change the bytes."""
        assert canonical({"hint": "רחוב"}) == '{"hint":"רחוב"}'

    def test_ascii_escaping_would_have_differed(self) -> None:
        """Shows the mismatch this setting prevents, rather than asserting a flag."""
        ours = canonical({"hint": "רחוב"})
        escaped = json.dumps({"hint": "רחוב"}, sort_keys=True, separators=(",", ":"))
        assert ours != escaped


class TestCommitFormula:
    def test_matches_the_reference_construction(self) -> None:
        """SHA256(canonical | "|" | nonce) — nonce appended, not embedded."""
        nonce = "abc123"
        expected = hashlib.sha256(f"{canonical(SAMPLE)}|{nonce}".encode()).hexdigest()
        assert commit_of(SAMPLE, nonce) == expected

    def test_embedding_the_nonce_would_give_a_different_digest(self) -> None:
        """Pins the placement, since either construction looks reasonable."""
        nonce = "abc123"
        embedded = hashlib.sha256(canonical({**SAMPLE, "nonce": nonce}).encode()).hexdigest()
        assert commit_of(SAMPLE, nonce) != embedded

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
        assert digest == hashlib.sha256(b'{"move":"N","step":1}|' + b"0" * 32).hexdigest()
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
