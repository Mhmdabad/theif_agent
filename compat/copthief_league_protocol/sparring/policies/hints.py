"""The verbal hint — zero tokens, no LLM, no network.

The book requires free natural language on the wire and forbids a numeric-coordinate protocol
(App. E rules 26-27). It also ships ``template`` as its own default hint provider, costing zero
tokens, and notes that a whole series can be played that way. That is what this is.

Two things are load-bearing and easy to get backwards:

* **The hint may lie; the commit may not.** ``intent`` is sealed into the step record and revealed
  at the audit, so a bluff is *declared* — the book requires the agent to commit in advance to
  whether it is telling the truth. Bluffing is legal; a bluff recorded as truth is tampering.
* **The word cap comes from the negotiated terms**, not from a constant here. It is a term both
  sides signed, so reading it from anywhere else would let a config change slip past the
  signature.

``--hint-lang mixed`` (the default) puts **Hebrew in some sub-games and an astral-plane emoji in
another**. That is not decoration. SPEC section 2 calls ``ensure_ascii=False`` the single most
important fact in the kit, because a serializer that escapes non-ASCII produces hints the opponent
cannot re-hash — and the failure surfaces as a false ``tamper_forfeit`` that zeroes both teams.
A peer that only ever says ASCII would let you finish a whole rehearsal without discovering it.
"""

from __future__ import annotations

import random

from sparring.rules.board import Cell

TRUTH = "truth"
LIE = "lie"

_ROWS = ("northern", "central", "southern")
_COLS = ("western", "middle", "eastern")

_TEMPLATES_EN = (
    "I am somewhere in the {region} district",
    "Heading through the {region} quarter now",
    "The {region} streets are quiet tonight",
    "Passing the {region} market",
    "Still around the {region} side of town",
)
_TEMPLATES_HE = (
    "אני איפשהו ברובע ה{region}",
    "עובר עכשיו דרך הרובע ה{region}",
    "הרחובות ה{region} שקטים הלילה",
)
_REGIONS_HE = {
    "northern": "צפוני", "central": "מרכזי", "southern": "דרומי",
    "western": "מערבי", "middle": "אמצעי", "eastern": "מזרחי",
}


def region_of(cell: Cell, board_size: int) -> tuple[str, str]:
    third = max(1, board_size // 3)
    row = _ROWS[min(2, cell[0] // third)]
    col = _COLS[min(2, cell[1] // third)]
    return row, col


class TemplateHintProvider:
    """Zero-token hints. Deterministic under a seeded RNG."""

    def __init__(self, board_size: int, hint_max_words: int, lang: str = "mixed",
                 lie_rate: float = 0.25) -> None:
        self.board_size = board_size
        self.hint_max_words = hint_max_words
        self.lang = lang
        self.lie_rate = lie_rate

    def choose_intent(self, rng: random.Random) -> str:
        return LIE if rng.random() < self.lie_rate else TRUTH

    def hint(self, true_cell: Cell, intent: str, sub_game: int, rng: random.Random) -> str:
        cell = true_cell if intent == TRUTH else self._far_from(true_cell, rng)
        row, col = region_of(cell, self.board_size)
        region = f"{row} {col}"

        use_hebrew = self.lang == "he" or (self.lang == "mixed" and sub_game % 3 == 2)
        if use_hebrew:
            region = f"{_REGIONS_HE[row]} ה{_REGIONS_HE[col]}"
            text = rng.choice(_TEMPLATES_HE).format(region=region)
        else:
            text = rng.choice(_TEMPLATES_EN).format(region=region)

        # One sub-game per series carries an astral-plane character, for the same reason as the
        # Hebrew: a surrogate-escaping serializer must fail here, in a rehearsal, and not at an
        # opponent's audit.
        if self.lang == "mixed" and sub_game % 4 == 0:
            text = f"{text} 🗺️"

        return self._cap(text)

    def _far_from(self, cell: Cell, rng: random.Random) -> Cell:
        """A cell at least a third of the board away — a bluff that is actually misleading."""
        d_min = max(1, self.board_size // 3)
        candidates = [(r, c)
                      for r in range(self.board_size) for c in range(self.board_size)
                      if max(abs(r - cell[0]), abs(c - cell[1])) >= d_min]
        return rng.choice(sorted(candidates)) if candidates else cell

    def _cap(self, text: str) -> str:
        """Hard-enforce the negotiated word cap.

        Built inside the budget and then checked anyway: the cap is a signed term, and a hint that
        breaks it is a rules violation rather than a cosmetic problem.
        """
        words = text.split()
        if len(words) > self.hint_max_words:
            text = " ".join(words[: self.hint_max_words])
        assert len(text.split()) <= self.hint_max_words
        return text
