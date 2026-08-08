"""What the audit concluded, and the evidence it has to hand over with it."""

from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    """What the audit concluded about one peer's play."""

    CLEAN = "clean"
    FORGED = "forged"


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Every step re-derived, and what that showed.

    Carries the failures rather than only the verdict. Both teams must **agree**
    a result before either may report it, and "you cheated" is not a claim
    anyone concedes — "step 12 committed to a digest that your own revealed
    move and nonce do not produce" is, because they can run the same
    arithmetic and get the same answer.
    """

    verdict: Verdict
    checked: int
    failures: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return self.verdict is Verdict.CLEAN

    def __str__(self) -> str:
        if self.clean:
            return f"{self.checked} steps re-derived, all matching"
        return f"{self.checked} steps re-derived, {len(self.failures)} failed: " + "; ".join(
            self.failures
        )
