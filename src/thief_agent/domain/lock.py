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

**The agreement covers how the field travels, not only what it contains.**
:data:`~.fixture.BINDING` is one of the hashed terms, so a peer that ships its
field unbound in the phase-1 turn message — as the reference dialect does —
fails the lock at negotiation rather than surprising us mid-series. That is the
fail-closed half of the design: the runtime refuses to *absorb* scent it cannot
verify, and this refuses to *open a series* on a model that cannot produce
verifiable scent, so the two failures cannot be reached by accident.

**Disagreement is reported, not resolved.** :func:`compare` says which terms
differ and stops. A module that quietly adopted the opponent's model on
mismatch would be conceding an agreement nobody made, and the rulebook's
remedy is negotiation between teams rather than silent accommodation.
"""

from dataclasses import dataclass

from ..shared.config import canonical_bytes, config_sha256, digests_agree
from .fixture import BINDING, ScentFixture, build
from .scent import DEFAULT_FALLOFF, Falloff

SOURCE_OFFER = (
    "Our scent engine is offered in full: domain/scent.py (emission), "
    "domain/trail.py (merge and decay), domain/fixture.py (this example), "
    "domain/scent_audit.py (the reconstruction we will audit you with). "
    "The rulebook permits and recommends sharing it, and the physics are "
    "public and symmetric, so it costs nothing strategically and removes the "
    "last room for an interpretation difference. The auditor is included "
    "deliberately: a check the other side cannot run against itself first is "
    "a trap rather than an agreement."
)
"""Accompanies the proposal. The rulebook explicitly recommends this.

Offering the code is strictly stronger than agreeing a formula: a formula
still has to be read, and reading is where the two divergences already found
in this project came from.
"""


@dataclass(frozen=True, slots=True)
class ScentAgreement:
    """A lock the opponent matched exactly, and what the runtime may do about it.

    The output of the negotiation rather than an input to it, which is the whole
    of P1-15: ``SubGame.require_bound_scent`` used to be a ``True`` written in
    the source with no caller and no configuration behind it, so the fail-closed
    posture it documented was an edit rather than an agreement. Here it is
    *derived* from a term both peers hashed, and there is no other way to obtain
    one — a series that never reached an agreement has no object to ask.
    """

    digest: str
    binding: str

    @property
    def require_bound_scent(self) -> bool:
        """Whether the agreed dialect seals the field into the phase-1 commitment.

        True for :data:`~.fixture.BINDING` and nothing else. The alternative is
        not a laxer rule but a different game, and the downgrade it names is to
        **no scent at all** rather than to scent nobody can check — so this is
        the one question the answer to which decides whether the pheromone layer
        runs at all.
        """
        return self.binding == BINDING


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

    def agreement(self) -> ScentAgreement:
        """What has been settled once a peer has matched this lock exactly.

        Built from *our* terms rather than from theirs on purpose. After
        :func:`disputes` comes back empty the two are the same object of
        agreement, and taking ours means a peer cannot smuggle a term through
        the gate by spelling it in a way that compared equal but reads
        differently downstream.
        """
        return ScentAgreement(digest=self.digest(), binding=self.fixture.binding)


def propose(falloff: Falloff = DEFAULT_FALLOFF) -> ScentLock:
    """Our side of the exchange, built from the live engine."""
    return ScentLock(fixture=build(falloff))


def restate(theirs: dict[str, object]) -> str:
    """The digest their own terms produce, whatever digest they claimed.

    A hash a peer merely asserts is a number; it commits them to nothing unless
    it covers the model travelling with it. Without this, an opponent could
    quote *our* digest over somebody else's physics and pass a comparison of
    digests alone — which is exactly the check a lock is for.

    A malformed model restates over an empty one rather than raising: this is
    the opponent's payload, and a crash on an inbound message is a technical
    loss scoring zero for both sides. :func:`compare` names the malformation.
    """
    model = theirs.get("scent_model")
    return config_sha256({"scent_model": model if isinstance(model, dict) else {}})


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


def disputes(ours: ScentLock, theirs: dict[str, object], claimed: str) -> list[str]:
    """Every reason this offer cannot open a series: the terms, then the digest.

    Two questions, and a peer can fail either one independently.
    :func:`compare` asks whether their model is ours, term by term, which is
    what a team reads when the two sides have to reconcile. The digest asks the
    same question in one number, and asks a second one nothing else does:
    whether the hash they claim is the hash of the terms they sent.

    Both digest comparisons go through :func:`~..shared.config.digests_agree`
    and are therefore constant-time. Not because a lock digest is secret — both
    sides publish theirs — but because ``==`` stops at the first differing byte,
    and an opponent free to re-offer could walk our digest out of us one
    character at a time and then quote it back as its own model.

    Everything is listed at once rather than one failure per round trip, for
    the reason :func:`compare` already gives: a disagreement is negotiated
    between teams, and a negotiation conducted one term at a time is a series
    that never opens.
    """
    problems = compare(ours, theirs)
    restated = restate(theirs)
    if not digests_agree(restated, claimed):
        problems.append(
            f"scent_sha256: they claim {claimed} over terms that hash to {restated}, "
            "so their digest covers a model they did not send"
        )
    if not digests_agree(ours.digest(), claimed):
        problems.append(f"scent_sha256: they lock {claimed}, we lock {ours.digest()}")
    return problems
