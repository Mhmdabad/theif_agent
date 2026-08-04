"""The pre-series scent lock.

Before the first sub-game, both teams exchange the emission and decay model
together with a worked numeric example, confirm they read the formula the same
way, and hash the agreement. Everything after that is checkable: a peer whose
behaviour drifts from the locked model is detected immediately rather than
discovered halfway through a disputed series.

The lock matters here more than anywhere else in the protocol because the
scent model is the one place where two correct-looking implementations can
disagree silently. Both sides can implement "radial falloff with decay rho"
faithfully and still produce different fields — this project has already found
two such divergences against the professor's own reference code, one in the
falloff shape and one in the decay rule. Neither would have raised an error.
Both would have produced two agents confidently reading different boards.

**What is hashed is the numbers, not the prose.** A description agreed in
words is a description two teams can implement differently, which is the exact
failure the lock exists to prevent. The digest covers the model parameters and
the worked example together, canonicalised the same way the config digest is,
so a hash match means the fields will match.

**Disagreement is reported, not resolved.** :func:`compare` says which terms
differ and stops. A module that quietly adopted the opponent's model on
mismatch would be conceding an agreement nobody made, and the rulebook's
remedy is negotiation between teams rather than silent accommodation.
"""

from dataclasses import dataclass

from ..shared.config import canonical_bytes, config_sha256
from .fixture import ScentFixture, build
from .scent import DEFAULT_FALLOFF, Falloff

SOURCE_OFFER = (
    "Our scent engine is offered in full: domain/scent.py (emission), "
    "domain/trail.py (merge and decay), domain/fixture.py (this example). "
    "The rulebook permits and recommends sharing it, and the physics are "
    "public and symmetric, so it costs nothing strategically and removes the "
    "last room for an interpretation difference."
)
"""Accompanies the proposal. The rulebook explicitly recommends this.

Offering the code is strictly stronger than agreeing a formula: a formula
still has to be read, and reading is where the two divergences already found
in this project came from.
"""


@dataclass(frozen=True, slots=True)
class ScentLock:
    """A proposed or agreed scent model, and the digest that pins it."""

    fixture: ScentFixture
    source_offer: str = SOURCE_OFFER

    def terms(self) -> dict[str, object]:
        """The payload that crosses the wire."""
        return {"scent_model": self.fixture.as_terms(), "source_offer": self.source_offer}

    def digest(self) -> str:
        """SHA-256 over the canonicalised model and example.

        The offer text is excluded deliberately: it is a courtesy, not an
        agreement term, and hashing it would make two teams that agree
        perfectly on the physics fail the lock over a difference in wording.
        """
        return config_sha256({"scent_model": self.fixture.as_terms()})

    def canonical(self) -> bytes:
        """Exactly the bytes the digest is taken over, for the audit log."""
        return canonical_bytes({"scent_model": self.fixture.as_terms()})


def propose(falloff: Falloff = DEFAULT_FALLOFF) -> ScentLock:
    """Our side of the exchange, built from the live engine."""
    return ScentLock(fixture=build(falloff))


def compare(ours: ScentLock, theirs: dict[str, object]) -> list[str]:
    """Name every term on which the two proposals disagree.

    Returns an empty list when the models match. Reports rather than resolves:
    adopting the opponent's model on mismatch would concede an agreement
    nobody made, and the remedy the rulebook gives is negotiation.
    """
    received = theirs.get("scent_model")
    if not isinstance(received, dict):
        return ["scent_model: missing or malformed"]
    mine = ours.fixture.as_terms()
    problems = []
    for key in sorted(set(mine) | set(received)):
        if key not in received:
            problems.append(f"{key}: absent from their proposal")
        elif key not in mine:
            problems.append(f"{key}: not a term we recognise")
        elif received[key] != mine[key]:
            problems.append(f"{key}: they have {received[key]!r}, we have {mine[key]!r}")
    return problems


def agreed(ours: ScentLock, theirs: dict[str, object]) -> bool:
    """Whether the series may open on this model."""
    return not compare(ours, theirs)
