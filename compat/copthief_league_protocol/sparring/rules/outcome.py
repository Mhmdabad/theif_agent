"""How a sub-game ends, and what it is worth (book ch.3 table 2; App. F table 17).

Every value here is `קבוע` — permanent in the binding table, not negotiable in either direction.
They live in one place so that nothing else in the package can quietly hold a second copy.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    POLICE = "police"
    THIEF = "thief"

    @property
    def other(self) -> "Role":
        return Role.THIEF if self is Role.POLICE else Role.POLICE


class Outcome(str, Enum):
    CAPTURE = "capture"                  # the cop took the thief, by claim or by barrier or by trap
    SURVIVAL = "survival"                # the thief reached the survival threshold uncaught
    TIMEOUT = "timeout"                  # a side went silent past its budget — App. E, technical
    TECHNICAL_LOSS = "technical_loss"    # a crash, an illegal move, an illegal state transition
    TAMPER_FORFEIT = "tamper_forfeit"    # an audit re-hash missed: the iron rule, book ch.5


#: (police, thief) points. Technical loss and tamper forfeit deliberately zero BOTH sides — the
#: book's stated reason is to make protocol correctness worth more to each side than a win on
#: time. It also means an honest peer can be zeroed by its opponent's failure, which is why the
#: refusals elsewhere in this package are loud rather than forgiving.
SCORES: dict[Outcome, tuple[int, int]] = {
    Outcome.CAPTURE: (20, 5),
    Outcome.SURVIVAL: (5, 10),
    Outcome.TIMEOUT: (0, 0),
    Outcome.TECHNICAL_LOSS: (0, 0),
    Outcome.TAMPER_FORFEIT: (0, 0),
}

#: Outcomes that zero BOTH sides. Their 0–0 score is a sanction, not a tie: the published
#: technical-loss row shape (PAIRING-PLAYBOOK stage 7, agreed by the first league pairing) pins
#: `tie: false` with `winner_group: null` — two zeroes mean nobody won, not that both did equally
#: well. A row builder that computes `tie = (score_a == score_b)` silently violates it.
ZEROED = frozenset({Outcome.TIMEOUT, Outcome.TECHNICAL_LOSS, Outcome.TAMPER_FORFEIT})


def is_tie_row(outcome: Outcome, score_a: int, score_b: int) -> bool:
    """Whether a result row's `tie` flag is true — never for a zeroed (sanctioned) sub-game."""
    return outcome not in ZEROED and score_a == score_b


def settled_outcome(outcome: Outcome, audits_present: bool,
                    audits_passed: bool) -> tuple[Outcome, bool]:
    """(final outcome, settled?) — ONE settlement rule for both drivers.

    Before this function existed the two drivers disagreed (anrbj666's B4: selfplay kept a
    failed-audit capture settled; netplay refused any unverified sub-game) and — the sharper
    corollary — nothing anywhere ever ASSIGNED ``TAMPER_FORFEIT``: the outcome the book defines
    for a failed audit could not occur. The published model, now in one place:

    - audits exchanged and clean → the played outcome stands, settled;
    - audits exchanged and FAILED → **``TAMPER_FORFEIT``**, settled: the failed audit *is* the
      settlement, zeroing both sides (book ch.5 — the iron rule has no partial verdicts);
    - no audit on a **zeroed** outcome (timeout / technical loss) → settled: a classified dead
      sub-game owes no reveal, and the pair-agreed technical-loss row shape
      (PAIRING-PLAYBOOK stage 7) is exactly this case — reportable, `log_verified: false`,
      `tampered: false`;
    - no audit on a **played** outcome (capture / survival) → NOT settled: a game someone won
      but nobody can verify is the report WARNINGS §1 refuses to send.
    """
    if audits_present:
        return (outcome, True) if audits_passed else (Outcome.TAMPER_FORFEIT, True)
    return (outcome, outcome in ZEROED)


#: Points to each side when the CUMULATIVE score across a whole series ends level (App. F).
TIE_SCORE = 2

#: Sub-games in a series against one opponent (App. F table 18, permanent).
SUB_GAMES_PER_SERIES = 6


def score_for(outcome: Outcome, role: Role) -> int:
    police, thief = SCORES[outcome]
    return police if role is Role.POLICE else thief


def role_for(natural: Role, sub_game_number: int) -> Role:
    """Odd sub-games play your natural role; even ones play the opposite.

    Worth knowing where this comes from: **role alternation is not stated anywhere in the book's
    body.** It appears only in the reference implementation and in the sample artifacts' own
    schema text ("roles switch across the sub-games, so no role and no sub_game_number appear
    here"). It is followed because both sides of a real series followed it and because the
    reference defines it. *Who starts as what* is now a published default too:
    docs/PAIRING-PLAYBOOK.md stage 3 — the alphabetically-first group (the game_id sort) plays
    cop in the odd sub-games. State it with your opponent anyway; nothing in the binding table
    would settle an argument about it.
    """
    return natural if sub_game_number % 2 == 1 else natural.other
