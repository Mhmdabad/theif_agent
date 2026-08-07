"""Tests for the pre-series scent lock (#55) and the code offer (#56)."""

import dataclasses
import json

from thief_agent.domain.fixture import BINDING, build
from thief_agent.domain.lock import SOURCE_OFFER, ScentLock, agreed, compare, propose
from thief_agent.domain.scent import CHEBYSHEV


class TestTheAgreementIsOverNumbers:
    def test_two_peers_running_the_same_model_agree(self) -> None:
        assert agreed(propose(), propose().terms())
        assert compare(propose(), propose().terms()) == []

    def test_the_digest_is_stable(self) -> None:
        assert propose().digest() == propose().digest()

    def test_a_different_falloff_changes_the_digest(self) -> None:
        """The whole point. Both sides can implement 'radial falloff with
        decay rho' faithfully and still produce different fields — this
        project found two such divergences against the reference code, and
        neither raised an error."""
        assert propose().digest() != propose(CHEBYSHEV).digest()

    def test_it_covers_the_worked_example_not_only_the_parameters(self) -> None:
        """A model agreed in prose is one two teams implement differently."""
        canonical = propose().canonical().decode()
        assert "0.81" in canonical
        assert "decay_series" in canonical and "emission" in canonical

    def test_the_offer_text_is_outside_the_digest(self) -> None:
        """A courtesy, not an agreement term. Hashing it would fail the lock
        for two teams who agree perfectly on the physics but not on wording."""
        reworded = ScentLock(fixture=propose().fixture, source_offer="different words")
        assert reworded.digest() == propose().digest()


class TestDisagreementIsReportedNotResolved:
    def test_a_chebyshev_peer_is_named_term_by_term(self) -> None:
        problems = compare(propose(), propose(CHEBYSHEV).terms())
        assert problems
        assert any(problem.startswith("emission:") for problem in problems)
        assert any(problem.startswith("model:") for problem in problems)

    def test_our_model_is_not_quietly_adopted(self) -> None:
        """Accommodating on mismatch would concede an agreement nobody made.
        The rulebook's remedy is negotiation between teams."""
        ours = propose()
        before = ours.digest()
        compare(ours, propose(CHEBYSHEV).terms())
        assert ours.digest() == before
        assert not agreed(ours, propose(CHEBYSHEV).terms())

    def test_a_decay_disagreement_is_caught_even_when_emission_matches(self) -> None:
        """The divergence found against the reference: identical field shape,
        different forgetting."""
        theirs = propose().terms()
        model = theirs["scent_model"]
        assert isinstance(model, dict)
        model["decay_series"] = [0.80, 0.70, 0.60]
        problems = compare(propose(), theirs)
        assert len(problems) == 1
        assert problems[0].startswith("decay_series:")

    def test_a_missing_term_is_reported(self) -> None:
        theirs = propose().terms()
        model = theirs["scent_model"]
        assert isinstance(model, dict)
        del model["decay_rate"]
        assert compare(propose(), theirs) == ["decay_rate: absent from their proposal"]

    def test_an_unrecognised_term_is_reported(self) -> None:
        theirs = propose().terms()
        model = theirs["scent_model"]
        assert isinstance(model, dict)
        model["wind_direction"] = "north"
        assert compare(propose(), theirs) == ["wind_direction: not a term we recognise"]

    def test_a_malformed_proposal_is_refused_rather_than_crashing(self) -> None:
        assert compare(propose(), {}) == ["scent_model: missing or malformed"]
        assert compare(propose(), {"scent_model": "trust me"}) == [
            "scent_model: missing or malformed"
        ]

    def test_every_disagreement_is_listed_at_once(self) -> None:
        """One message rather than one round trip per differing term."""
        assert len(compare(propose(), propose(CHEBYSHEV).terms())) >= 2


class TestTheBindingIsPartOfTheAgreement:
    """How the field travels is an agreement term, not an implementation choice.

    Two peers can compute byte-identical fields and still be playing different
    games: one sealing the field into its phase-1 commitment, the other
    shipping it unbound alongside the commitment as the reference dialect does.
    The second is not a weaker version of the first — it discloses the emitter's
    exact cell a phase early *and* leaves the field free to be chosen after
    hearing the opponent. So it is settled before the series, in the same
    digest as the physics, rather than discovered inside one.
    """

    def test_the_proposal_names_how_the_field_is_bound(self) -> None:
        model = propose().terms()["scent_model"]
        assert isinstance(model, dict)
        assert model["binding"] == BINDING

    def test_the_binding_names_the_phase_and_the_commitment(self) -> None:
        """A term nobody can read is a term nobody can disagree with."""
        assert "commit" in BINDING and "reveal" in BINDING

    def test_it_is_covered_by_the_digest(self) -> None:
        """Outside the digest it would be a courtesy rather than a lock."""
        theirs = dataclasses.replace(build(), binding="turn-message-unbound")
        assert ScentLock(fixture=theirs).digest() != propose().digest()

    def test_a_peer_that_cannot_bind_its_scent_is_named(self) -> None:
        theirs = propose().terms()
        model = theirs["scent_model"]
        assert isinstance(model, dict)
        model["binding"] = "turn-message-unbound"
        problems = compare(propose(), theirs)
        assert len(problems) == 1
        assert problems[0].startswith("binding:")
        assert not agreed(propose(), theirs)

    def test_a_peer_that_omits_it_entirely_is_named(self) -> None:
        """Silence about the binding is refused, not read as consent."""
        theirs = propose().terms()
        model = theirs["scent_model"]
        assert isinstance(model, dict)
        del model["binding"]
        assert compare(propose(), theirs) == ["binding: absent from their proposal"]


class TestTheCodeOffer:
    def test_it_accompanies_the_proposal(self) -> None:
        """#56: the rulebook explicitly permits and recommends sharing it."""
        assert propose().terms()["source_offer"] == SOURCE_OFFER

    def test_it_names_the_modules(self) -> None:
        for module in ("domain/scent.py", "domain/trail.py", "domain/fixture.py"):
            assert module in SOURCE_OFFER

    def test_it_says_why_it_costs_nothing(self) -> None:
        """Offering the code is strictly stronger than agreeing a formula: a
        formula still has to be read, and reading is where both divergences
        found in this project came from."""
        assert "public and symmetric" in SOURCE_OFFER


class TestItCrossesTheWire:
    def test_the_payload_is_json_safe(self) -> None:
        assert json.loads(json.dumps(propose().terms()))["source_offer"] == SOURCE_OFFER

    def test_a_round_trip_still_agrees(self) -> None:
        """Serialisation must not perturb the values the digest covers."""
        wire = json.loads(json.dumps(propose().terms()))
        assert agreed(propose(), wire)

    def test_the_canonical_bytes_are_what_is_hashed(self) -> None:
        assert propose().canonical() == propose().canonical()
        assert b'"scent_model"' in propose().canonical()
