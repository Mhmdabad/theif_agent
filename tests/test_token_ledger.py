"""Token consumption, sealed so the total cannot be revised afterwards."""

import pytest

from thief_agent.infra.token_ledger import TokenLedger, TokenLedgerError, verify_report


def ledger(*charges: tuple[int, int, str]) -> TokenLedger:
    book = TokenLedger(group_name="s82kma9e")
    for step, tokens, provider in charges:
        book.charge(step, tokens, provider)
    return book


class TestTheLedgerOnlyGoesUp:
    def test_charges_accumulate(self) -> None:
        assert ledger((1, 1250, "claude_api"), (4, 1100, "claude_api")).spent == 2350

    def test_a_negative_charge_is_refused(self) -> None:
        """A call that turned out useless still consumed the compute.

        A report that could go down has a subtraction in it that nobody can
        audit, and a refund is indistinguishable from an erasure once the
        match is over.
        """
        with pytest.raises(TokenLedgerError, match="only goes up"):
            ledger().charge(1, -50, "claude_api")

    def test_a_zero_charge_is_allowed(self) -> None:
        """The template provider really does cost nothing."""
        assert ledger((1, 0, "template")).spent == 0

    def test_the_breakdown_adds_up_to_the_total(self) -> None:
        book = ledger((1, 1250, "claude_api"), (2, 0, "template"), (3, 900, "claude_api"))
        report = book.report()
        assert report["by_provider"] == {"claude_api": 2150, "template": 0}
        assert sum(report["by_provider"].values()) == report["total_tokens"] == 2150
        assert report["calls"] == 3


class TestSealingBindsTheTotal:
    def test_sealing_produces_a_commitment(self) -> None:
        book = ledger((1, 1250, "claude_api"))
        assert book.commit is None
        assert len(book.seal()) == 64
        assert book.commit is not None

    def test_charging_after_the_seal_is_refused(self) -> None:
        """It would change a total the opponent already holds a commitment to."""
        book = ledger((1, 1250, "claude_api"))
        book.seal()
        with pytest.raises(TokenLedgerError, match="already sealed"):
            book.charge(2, 1250, "claude_api")

    def test_a_second_seal_is_refused(self) -> None:
        """Two commitments is a choice of which one to disclose."""
        book = ledger((1, 1250, "claude_api"))
        book.seal()
        with pytest.raises(TokenLedgerError, match="already sealed"):
            book.seal()

    def test_the_nonce_does_not_cross_the_wire_with_the_commitment(self) -> None:
        book = ledger((1, 1250, "claude_api"))
        commit = book.seal()
        assert book.disclose()["nonce"] not in commit

    def test_two_ledgers_with_the_same_total_seal_differently(self) -> None:
        """A fresh nonce, so an opponent cannot recognise our spend by its digest."""
        first, second = ledger((1, 1250, "claude_api")), ledger((1, 1250, "claude_api"))
        assert first.seal() != second.seal()


class TestDisclosure:
    def test_a_sealed_report_verifies(self) -> None:
        book = ledger((1, 1250, "claude_api"), (2, 800, "claude_api"))
        book.seal()
        assert verify_report(book.disclose())

    def test_disclosing_an_unsealed_report_is_refused(self) -> None:
        """A number with no commitment behind it proves only that we state it."""
        with pytest.raises(TokenLedgerError, match="nothing to disclose"):
            ledger((1, 1250, "claude_api")).disclose()

    def test_a_total_edited_after_sealing_does_not_verify(self) -> None:
        """The same offence as a rewritten move, detected the same way."""
        book = ledger((1, 1250, "claude_api"))
        book.seal()
        tampered = book.disclose()
        tampered["report"] = {**tampered["report"], "total_tokens": 10}
        assert not verify_report(tampered)

    @pytest.mark.parametrize(
        "disclosed",
        [
            {},
            {"report": {}, "nonce": "n"},
            {"report": "not a mapping", "nonce": "n", "commit": "c"},
            {"report": {}, "nonce": 42, "commit": "c"},
        ],
    )
    def test_a_malformed_disclosure_does_not_verify(self, disclosed: dict[str, object]) -> None:
        assert not verify_report(disclosed)


class TestMeteringIsSeparateFromThrottling:
    def test_the_ledger_never_decides_whether_a_call_may_happen(self) -> None:
        """Ration decides the next call; this records the ones that happened.

        Merging them would tie the honesty of the report to a policy decision:
        a throttle that skipped a call would also be what decided the call was
        never counted.
        """
        gates = [
            name
            for name in dir(TokenLedger)
            if not name.startswith("_")
            and any(word in name for word in ("allow", "may", "can", "budget", "remaining"))
        ]
        assert gates == []

    def test_charging_reports_the_total_rather_than_a_permission(self) -> None:
        """A bool here would be a throttle wearing a meter's name."""
        assert ledger().charge(1, 1250, "claude_api") == 1250
