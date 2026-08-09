"""The verbal half of a turn: compose a sentence, and decide what it costs.

Everything below this module already existed and nothing called it.
:func:`~..domain.bluff.speak` composed a hint, :class:`~..domain.providers.Bluffer`
rephrased it through a provider, :class:`~..domain.budgeting.Ration` throttled
the spend and :class:`~..infra.token_ledger.TokenLedger` sealed the total — and
:meth:`~.base.BrainBase._hint` returned a constant string, so every one of them
sat unreachable. Both agents said *"I am watching the streets"* on all thirty-
five steps of all six sub-games, and the report's token total was a hardcoded
zero that happened to be true only because the model never ran.

**The turn counter lives here rather than in the runtime.** The ration throttles
to every Nth turn, which needs a step number, and the strategy boundary is
deliberately three fixed keys — ``threat``, ``concentration``, ``uncertainty`` —
guarded by :class:`~..runtime.subgame_commit.StrategyContextError`. Widening
that contract to pass a step would make every configured brain in the cohort
re-implement it. Counting calls here is the same number and costs nobody else
anything.

**The default intent is the truth, and that is a considered choice.** Lying is
implemented and cheap to switch on, but a lie is only safe once it has been
vetted against our own emitted trail — :func:`~..domain.bluff_vetting.contradicts_our_field`
is the same test the opponent runs on arrival, and a claim our own scent
refutes is a free credibility donation to the side we are lying to. The field
is not on the strategy boundary, so a brain that wants to lie passes one in
deliberately rather than getting it by default.
"""

import random
from dataclasses import dataclass, field

from ..domain.bluff import Bluff, speak
from ..domain.bluff_vetting import contradicts_our_field
from ..domain.board import Agent, BoardState, Position
from ..domain.budgeting import Ration
from ..domain.providers import Bluffer
from ..domain.rules import position_of

__all__ = ["Voice"]


@dataclass
class Voice:
    """One agent's speech: what it says, and what saying it costs."""

    ration: Ration = field(default_factory=lambda: Ration(bluffer=Bluffer()))
    seed: int = 0
    turns: int = 0
    rng: random.Random = field(init=False)
    """The voice's own stream, deliberately not the policy's.

    Phrasing draws randomly, and drawing from the brain's generator would make
    *what we said* change *where we go* — every hint would shift the move
    sequence, and a replay that re-derives moves would diverge. Seeded from the
    same configured seed, so hints stay reproducible without the policy's
    stream ever advancing. ``test_determinism`` asserts exactly this.
    """

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    @property
    def spent(self) -> int:
        """Tokens charged to the series so far. What rule 54's total reports."""
        return self.ration.spent

    def about(self, state: BoardState, role: Agent, after: BoardState) -> str:
        """This turn's hint, from the board before and after our own action.

        The two cells a sentence needs — where the action leaves us, and the
        vantage it is spoken from — are derived here rather than at each call
        site, because there are two call sites and they are the one file per
        repository that legitimately differs.
        """
        them: Agent = "cop" if role == "thief" else "thief"
        return self.say(position_of(after, role), state, position_of(state, them))

    def say(
        self,
        truth: Position,
        state: BoardState,
        seen_from: Position,
        intent: str = "truth",
        own_field: dict[Position, float] | None = None,
    ) -> str:
        """This turn's hint, paid for only when the throttle allows a call.

        Never raises. Every provider falls back to the composed template line,
        the ration abandons a late answer, and an exhausted budget drops to
        ``template`` permanently — because a hint is worth few marks and a turn
        that goes unanswered inside the deadline is a technical loss scoring
        zero for *both* sides.
        """
        self.turns += 1
        bluff = self._compose(truth, state, seen_from, intent, own_field)
        return self.ration.speak(bluff, self.turns)

    def _compose(
        self,
        truth: Position,
        state: BoardState,
        seen_from: Position,
        intent: str,
        own_field: dict[Position, float] | None,
    ) -> Bluff:
        """The sentence before a provider touches it, vetted if it is a lie.

        A lie our own trail refutes is downgraded to the truth rather than
        sent. The opponent runs this exact test when the field arrives, so
        sending it anyway would not deceive them — it would hand them a
        contradiction to convict us on, and cheapen every later hint.
        """
        composed = speak(truth, state, seen_from, intent, self.rng, own_field)
        if intent != "truth" and own_field and contradicts_our_field(composed, own_field, 0.81):
            return speak(truth, state, seen_from, "truth", self.rng, own_field)
        return composed
