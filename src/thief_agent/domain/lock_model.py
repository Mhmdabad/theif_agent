"""The locked scent model and what a matched lock settles.

The data half of the pre-series scent lock: the offer text that accompanies a
proposal, the proposed-or-agreed model together with the digest that pins it,
and the agreement that a peer matching it exactly produces. The negotiation
itself — restating, comparing, disputing — lives in :mod:`.lock`.
"""

from dataclasses import dataclass

from ..shared.config import canonical_bytes, config_sha256
from .fixture import BINDING, ScentFixture

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
