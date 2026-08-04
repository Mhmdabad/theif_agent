"""Rationing the verbal layer: when to speak, and when to stop paying for it.

Two limits, and the first is the one that binds. At 35 turns a sub-game and
six sub-games a series, calling a model every turn costs roughly 260 000 input
tokens against a series budget of 200 000 — the budget runs out before the
money does. ``every_n_steps`` is not a tuning knob, it is what makes a paid
provider affordable at all; at every third turn the same series lands near
87 000.

**The deadline is the harder rule.** ``step_deadline_seconds`` is 30, and a
turn that goes unanswered is a technical loss worth **zero to both sides** —
strictly worse than the dullest hint. So the throttle also carries a wall
clock: a provider that has not answered in time is abandoned and the template
line is sent instead. Losing a rephrasing costs nothing; losing the turn costs
the match.

**The meter is a hard stop, not a warning.** When the series budget is spent
the provider is dropped to ``template`` permanently. That is not a degraded
mode — it is the mode the rulebook calls the recommended route, and a series
can never fail for want of tokens.
"""

import logging
import time
from dataclasses import dataclass, field

from ..shared.appendix_f import book_int
from .bluff import Bluff
from .providers import DEFAULT_PROVIDER, Bluffer

logger = logging.getLogger(__name__)

EVERY_N_STEPS = 3
"""Turns between model calls. A *negotiable* pacing choice, not an Appendix F
value: at every turn a six-sub-game series exceeds the token budget, and at
every third it fits with room to spare."""

DEADLINE_SECONDS: float = 30.0
"""Wall clock for one hint. Matches ``step_deadline_seconds``.

Enforced by us rather than trusted to the provider's own timeout, because a
provider that hangs below its timeout still costs the turn.
"""

TOKEN_BUDGET: int = book_int("network_and_league", "token_budget_per_series")
"""Appendix F series budget. *Negotiable*, so it is read rather than restated."""

ESTIMATED_TOKENS_PER_CALL = 1250
"""Charged per call when the provider reports no usage.

Deliberately an over-estimate. Under-counting spends a budget we have already
agreed, and being caught over the limit at audit is worse than sending a few
template lines we did not have to.
"""


@dataclass
class Ration:
    """Decides whether this turn gets a model call, and stops when spent."""

    bluffer: Bluffer
    every_n_steps: int = EVERY_N_STEPS
    deadline: float = DEADLINE_SECONDS
    budget: int = TOKEN_BUDGET
    spent: int = 0
    skipped: int = 0
    late: int = 0
    exhausted: bool = field(default=False)

    @property
    def remaining(self) -> int:
        """Tokens left in the series budget."""
        return max(0, self.budget - self.spent)

    def due(self, step: int) -> bool:
        """Whether ``step`` is a turn the throttle allows a call on."""
        if self.exhausted or self.bluffer.provider == DEFAULT_PROVIDER:
            return False
        if self.remaining < ESTIMATED_TOKENS_PER_CALL:
            return False
        return step % self.every_n_steps == 0

    def speak(self, bluff: Bluff, step: int) -> str:
        """Hint text for this turn, paying for a model call only when due.

        Never raises and never blocks past the deadline. A skipped, late or
        unaffordable turn returns the composed template line, which is a
        complete and legal hint rather than a degraded one.
        """
        if not self.due(step):
            self.skipped += 1
            return bluff.text

        started = time.monotonic()
        spoken = self.bluffer.dress(bluff)
        elapsed = time.monotonic() - started
        self.spent += ESTIMATED_TOKENS_PER_CALL

        if elapsed > self.deadline:
            self.late += 1
            logger.warning(
                "hint took %.1fs against a %.0fs deadline; sending the template line",
                elapsed,
                self.deadline,
            )
            spoken = bluff.text

        if self.remaining < ESTIMATED_TOKENS_PER_CALL:
            self.stop("series token budget spent")
        return spoken

    def stop(self, why: str) -> None:
        """Drop to ``template`` for the rest of the series, permanently.

        Not a degraded mode: it is the rulebook's recommended route, and it
        guarantees a series can never fail for want of tokens.
        """
        if not self.exhausted:
            self.exhausted = True
            self.bluffer.provider = DEFAULT_PROVIDER
            logger.info("%s; dropping to %s for the rest of the series", why, DEFAULT_PROVIDER)

    def __str__(self) -> str:
        return (
            f"{self.spent}/{self.budget} tokens, {self.skipped} throttled, "
            f"{self.late} late{' — EXHAUSTED' if self.exhausted else ''}"
        )
