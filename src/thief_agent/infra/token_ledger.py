"""What the language model actually cost, sealed so it cannot be denied.

The rulebook puts token consumption under the same lock as everything else:
it is *"monitored and cryptographically locked, to prevent denial of the
compute resources actually consumed"*. The reason is the same normalisation
that drives the hardware declaration — the score rewards good results on few
resources, so an unlocked token count is a number every team has a reason to
round down.

**Metering and throttling are different jobs and live in different places.**
:class:`~..domain.budgeting.Ration` decides whether the *next* call may happen;
this records what the calls that did happen cost. Merging them would tie the
honesty of the report to a policy decision — a throttle that skipped a call
would also, silently, be the thing that decided the call was never counted.

The ledger is **monotonic**. Tokens are spent, never unspent: a call that
turned out useless still consumed the compute, and a report that could go down
is a report with a subtraction in it that nobody can audit. A refund is
indistinguishable from an erasure once the match is over.

Sealing reuses the step commitment machinery rather than inventing a second
scheme. One nonce, one digest, disclosed with the rest at the final reveal —
so a team that produces a token report at the end has already been committed to
it since the start, and the opponent holds the commitment.
"""

from dataclasses import dataclass, field
from typing import Any

from ..domain.crypto import commit_of, nonce


class TokenLedgerError(ValueError):
    """Raised on an entry that would make the report unauditable."""


@dataclass
class TokenLedger:
    """Tokens consumed in one series, accumulating only upward."""

    group_name: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    spent: int = 0
    _nonce: str | None = None
    _commit: str | None = None

    def charge(self, step: int, tokens: int, provider: str) -> int:
        """Record the cost of one call.

        Raises:
            TokenLedgerError: on a negative charge, or after the report has
                been sealed. Both are the same offence in different clothes —
                one lowers the total, the other changes it after committing to
                it.
        """
        if tokens < 0:
            raise TokenLedgerError(
                f"cannot charge {tokens} tokens at step {step}; the ledger only goes up, "
                "and a refund is indistinguishable from an erasure once the match ends"
            )
        if self._commit is not None:
            raise TokenLedgerError(
                f"the token report is already sealed; charging {tokens} at step {step} "
                "would change a total the opponent already holds a commitment to"
            )
        self.entries.append({"step": step, "tokens": tokens, "provider": provider})
        self.spent += tokens
        return self.spent

    def report(self) -> dict[str, Any]:
        """The attested total, and enough breakdown to check it adds up."""
        return {
            "group_name": self.group_name,
            "total_tokens": self.spent,
            "calls": len(self.entries),
            "by_provider": {
                provider: sum(e["tokens"] for e in self.entries if e["provider"] == provider)
                for provider in sorted({str(e["provider"]) for e in self.entries})
            },
        }

    def seal(self) -> str:
        """Commit to the report, keeping the nonce back until the final reveal.

        Called at the *start* of the disclosure, before the total is stated, so
        that a team producing a number at the end has been bound to it since
        the moment it stopped counting.

        Raises:
            TokenLedgerError: on a second seal. Re-sealing produces a second
                commitment for one report, and two commitments is a choice of
                which to disclose.
        """
        if self._commit is not None:
            raise TokenLedgerError(
                "the token report is already sealed; a second commitment would be a "
                "choice of which one to disclose"
            )
        self._nonce = nonce()
        self._commit = commit_of(self.report(), self._nonce)
        return self._commit

    @property
    def commit(self) -> str | None:
        """The commitment, once sealed. Crosses the wire; the nonce does not."""
        return self._commit

    def disclose(self) -> dict[str, Any]:
        """The report and its nonce, for the final reveal.

        Raises:
            TokenLedgerError: if nothing was sealed. Disclosing an unsealed
                report is a number with no commitment behind it, which proves
                only that we are willing to state it.
        """
        if self._commit is None or self._nonce is None:
            raise TokenLedgerError(
                "nothing to disclose; an unsealed report is a number with no commitment "
                "behind it and proves only that we are willing to state it"
            )
        return {"report": self.report(), "nonce": self._nonce, "commit": self._commit}


def verify_report(disclosed: dict[str, Any]) -> bool:
    """Whether a disclosed token report opens to the commitment it claims.

    Run against the **opponent's** disclosure. A report whose digest does not
    match is a total that was edited after it was committed to, which is the
    same offence as a rewritten move and detected the same way.
    """
    try:
        report, given, claimed = disclosed["report"], disclosed["nonce"], disclosed["commit"]
    except KeyError:
        return False
    if not isinstance(report, dict) or not isinstance(given, str):
        return False
    return commit_of(report, given) == str(claimed)
