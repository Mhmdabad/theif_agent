"""Reading the opponent's sentence, and deciding what it is worth.

Split out of :mod:`.subgame_scent`, which owns the witness that cannot lie.
This is the other one. Keeping them apart is not only length: the two are
scored by different rules, and the scent path must stay readable as *physics
absorbed unconditionally* rather than as one branch of a function that also
weighs claims.

**It was parsed nowhere.** :attr:`~.subgame_state.SubGameState.received_hints`
kept every sentence an opponent ever sent, verbatim, and the belief was updated
from scent alone — so the hint channel was retained as evidence and never
weighed as any. :mod:`..domain.hints` could turn a sentence into a claim,
:mod:`..domain.credibility` could score that claim against the trail, and
:func:`..domain.inference.update` had taken ``claim`` and ``reliability``
arguments since it was written. No caller ever passed them.

The order matters and is the reason this is not simply "believe the hint". A
claim is checked against the trail **first**, and the resulting verdict moves
the running reliability, so a contradicted sentence reaches the belief already
discounted rather than believed and regretted. That is what makes *a hint may
lie, the scent may not* a property of the code and not a sentence in a report.
"""

from dataclasses import dataclass

from ..domain.board import Position
from ..domain.credibility import check
from ..domain.hints import CoordinateProtocolError, parse
from .subgame_moves import SubGameMoves


@dataclass
class SubGameHint(SubGameMoves):
    """The half of an observation that arrives as language."""

    def weigh_hint(self, text: str, field: dict[Position, float]) -> dict[Position, float]:
        """Score one sentence against the trail and return what it claims.

        The verdict is folded into :attr:`credibility` here rather than by the
        caller, because the two are one decision: a claim that is checked and
        not remembered would let an opponent tell the same lie every turn at no
        cost, and the reliability exists precisely to make the second lie
        cheaper to disbelieve than the first.

        Returns the claim so the caller can hand it to the belief update, or an
        empty mapping when the opponent said nothing readable.
        """
        claim = self.read_hint(text)
        if claim:
            self.credibility.observe(check(claim, field))
        return claim

    def read_hint(self, text: str) -> dict[Position, float]:
        """What the sentence asserts about where the opponent is, if anything.

        ``speaker`` is where we currently believe them to be, which is what a
        direction is relative to: "north" means north *of them*, not of the
        board. With no belief peak yet there is nothing to be north of, so the
        sentence is unreadable rather than wrong.

        Silence and an unreadable sentence give the same answer — an empty
        claim, which the Bayes update treats as absent information rather than
        as evidence against anything.

        A hint carrying coordinates is refused here as well as at the door.
        This is not that check repeated: it is the guarantee that parsing a
        hostile sentence cannot raise mid-turn, where the cost would be a
        technical loss scoring zero for *both* sides.
        """
        speaker = self.belief.most_likely()
        if not text or speaker is None:
            return {}
        try:
            return parse(text, self.state, speaker)
        except CoordinateProtocolError:
            return {}
