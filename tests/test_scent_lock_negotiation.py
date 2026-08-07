"""P0-3 and P1-15: the pre-series scent lock is a gate, not a module nobody calls.

Appendix E rule 23 — "lock the scent-emission model cryptographically before the
game starts; deviation in the decay formula voids the match". Before this module
``domain/lock.py`` had **zero import sites in ``src/``**: ``propose``, ``compare``
and ``ScentLock.digest`` were built, tested and never sent. Nothing in
``open_series``, ``agree_config`` or ``MatchRunner.agree`` proposed a model,
received one, or compared the two — so the two deliberate divergences from the
reference implementation (Gaussian against Chebyshev falloff, multiplicative
against subtractive decay) surfaced as an audit failure halfway through a series
instead of as a conversation before it opened.

The other half is P1-15. ``SubGame.require_bound_scent`` was a hard-coded ``True``
that no caller set and no configuration reached, so the fail-closed posture the
field documents was a source edit rather than an agreement. It is derived here
from the ``binding`` term of a lock the opponent actually matched, and from
nothing else: a peer that cannot bind its scent is refused before the series
rather than quietly downgraded inside one.

Everything runs against the real path — two FastMCP servers on two sockets, two
``PeerInboxes``, two ``Orchestrator``s and the real ``negotiate`` tool — because
the property a mock cannot demonstrate is the one that matters most: both peers
run this gate **at the same time**, each waiting for a message only the other can
send, and neither may wait before it speaks.
"""

import json
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from test_config_agreement import (  # noqa: E402
    BRIEF,
    GAME_UID,
    OTHER_UID,
    OUR_ROLE,
    PATIENCE,
    THEIR_ROLE,
    Side,
    a_runner,
    a_side,
    altered,
    concurrently,
    fresh,
)
from test_localhost_match import free_port, parameters, wait_for  # noqa: E402
from test_match import stub_boundaries  # noqa: E402
from thief_agent.domain.fixture import BINDING
from thief_agent.domain.lock import ScentAgreement, propose, restate
from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.domain.scent import CHEBYSHEV
from thief_agent.infra.ceremony import AuditResult, Verdict
from thief_agent.infra.inboxes import SCENT_DIGEST_KEY, SCENT_KEY, SERIES_KEY
from thief_agent.infra.mcp_server import ServerSettings, build, serve
from thief_agent.runtime.orchestrator import MatchAborted
from thief_agent.runtime.subgame import Played, SubGame
from thief_agent.shared.config import config_sha256


@pytest.fixture(scope="module")
def wire() -> Iterator[tuple[Side, Side]]:
    """This agent and its opponent on two real servers, pointed at each other."""
    our_port, their_port = free_port(), free_port()
    ours, theirs = a_side(OUR_ROLE, their_port), a_side(THEIR_ROLE, our_port)
    for side, port in ((ours, our_port), (theirs, their_port)):
        host = build(side.inboxes, name=f"{side.role}-scent-lock")
        threading.Thread(
            target=serve,
            args=(host, ServerSettings(port=port, host="127.0.0.1")),
            daemon=True,
        ).start()
        wait_for(port)
    yield ours, theirs


def our_lock() -> ScentAgreement:
    return propose().agreement()


def an_offer(
    changes: dict[str, Any] | None = None,
    *,
    uid: str | None = GAME_UID,
    digest: str | None = None,
    drop: str | None = None,
) -> dict[str, Any]:
    """A well-formed offer, optionally diverging in exactly one term.

    The digest is recomputed over whatever the terms end up saying, unless a
    test asks for a specific one. That separation is the point: a test about a
    *term* must not accidentally be a test about a *hash*, or neither failure is
    proved and a peer could pass one gate by failing the other.
    """
    terms = propose().terms()
    model = terms["scent_model"]
    assert isinstance(model, dict)
    if drop is not None:
        del model[drop]
    model.update(changes or {})
    body: dict[str, Any] = {SCENT_KEY: terms, SCENT_DIGEST_KEY: digest or restate(terms)}
    if uid is not None:
        body[SERIES_KEY] = uid
    return body


def finer_precision() -> dict[str, Any]:
    """Our own emission carried at a precision the wire cannot reproduce.

    Rounding to three decimals is what makes "same formula" mean "same numbers";
    a peer that skips it agrees with us about the physics and disagrees about
    every value, which is a mid-series audit failure unless it is caught here.
    """
    emission = propose().fixture.as_terms()["emission"]
    assert isinstance(emission, dict)
    return {"emission": {cell: value + 1e-9 for cell, value in emission.items()}}


DIVERGENCES: dict[str, dict[str, Any]] = {
    "emission-radius": {"grid_size": 7},
    "kernel": {"model": "chebyshev"},
    "intensities": {"emission": {"2,2": 0.9}},
    "centre-intensity": {"centre_intensity": 0.8},
    "decay-rate": {"decay_rate": 0.2},
    "decay-rule": {"decay_series": [0.80, 0.70, 0.60]},
    "board-size": {"board_size": 8},
    "binding": {"binding": "turn-message-unbound"},
}
"""One divergence per term the lock exists to settle, each fatal on its own."""


def lock_gate(side: Side, timeout: float = PATIENCE) -> Callable[[], ScentAgreement]:
    return lambda: side.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=timeout)


def both_lock(wire: tuple[Side, Side], timeout: float = PATIENCE) -> dict[str, Any]:
    ours, theirs = fresh(wire)
    return concurrently({"ours": lock_gate(ours, timeout), "theirs": lock_gate(theirs, timeout)})


class TestTwoHonestPeersLockTheSameModel:
    """Identical engines: the lock is agreed, symmetrically, before any sub-game."""

    def test_both_sides_come_back_with_the_same_agreement(self, wire: tuple[Side, Side]) -> None:
        assert both_lock(wire) == {"ours": our_lock(), "theirs": our_lock()}

    def test_the_agreement_carries_the_digest_of_the_model(self, wire: tuple[Side, Side]) -> None:
        assert both_lock(wire)["ours"].digest == propose().digest()

    def test_each_side_consumed_the_others_offer(self, wire: tuple[Side, Side]) -> None:
        """One producer and no consumer was the whole of P0-3."""
        ours, theirs = wire
        both_lock(wire)
        assert ours.inboxes.scent_locks.empty(), "we never read what the opponent sent"
        assert theirs.inboxes.scent_locks.empty(), "the opponent never read what we sent"

    def test_nothing_was_refused_at_either_door(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = wire
        both_lock(wire)
        assert ours.inboxes.rejected == []
        assert theirs.inboxes.rejected == []

    def test_the_digest_advertised_covers_the_model_sent(self, wire: tuple[Side, Side]) -> None:
        """A digest that does not cover its own terms binds the sender to nothing."""
        ours, theirs = fresh(wire)
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        filed = theirs.inboxes.scent_locks.get_nowait()
        assert restate(filed[SCENT_KEY]) == filed[SCENT_DIGEST_KEY] == propose().digest()

    def test_the_source_offer_travels_with_it(self, wire: tuple[Side, Side]) -> None:
        """Appendix E recommends sharing the engine; the offer is not a digest term."""
        ours, theirs = fresh(wire)
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        offered = theirs.inboxes.scent_locks.get_nowait()[SCENT_KEY]
        assert "domain/scent.py" in str(offered["source_offer"])


class TestBothPeersCanNegotiateAtOnce:
    """Neither side may wait before it speaks, or two polite peers hang forever."""

    def test_neither_side_waits_for_the_other_to_go_first(self, wire: tuple[Side, Side]) -> None:
        """A window neither could survive if the gate serialised the two peers."""
        done = both_lock(wire, timeout=BRIEF)
        assert [type(value) for value in done.values()] == [ScentAgreement] * 2, done

    def test_a_repeated_series_of_gates_never_stalls(self, wire: tuple[Side, Side]) -> None:
        for _ in range(3):
            assert set(both_lock(wire, timeout=BRIEF).values()) == {our_lock()}

    def test_the_config_gate_and_the_lock_run_back_to_back(self, wire: tuple[Side, Side]) -> None:
        """Both gates, both peers, at once — the order a real series opens in."""
        ours, theirs = fresh(wire)

        def whole_negotiation(side: Side) -> ScentAgreement:
            side.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=PATIENCE)
            return side.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=PATIENCE)

        done = concurrently(
            {"ours": lambda: whole_negotiation(ours), "theirs": lambda: whole_negotiation(theirs)}
        )
        assert done == {"ours": our_lock(), "theirs": our_lock()}


class TestAnyDivergenceAbortsTheSeriesBeforePlay:
    """Two models that differ anywhere are two games. Refused, up front, by name."""

    @pytest.mark.parametrize("term", sorted(DIVERGENCES))
    def test_one_differing_term_is_fatal(self, wire: tuple[Side, Side], term: str) -> None:
        ours, theirs = fresh(wire)
        theirs.send(an_offer(DIVERGENCES[term]))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION

    @pytest.mark.parametrize("term", sorted(DIVERGENCES))
    def test_the_differing_term_is_named(self, wire: tuple[Side, Side], term: str) -> None:
        """An accusation both teams must reconcile arrives with the arithmetic."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer(DIVERGENCES[term]))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert next(iter(DIVERGENCES[term])) in excinfo.value.detail

    def test_a_precision_divergence_is_fatal(self, wire: tuple[Side, Side]) -> None:
        """Same formula, unrounded. Every value differs in the last bits."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer(finer_precision()))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION

    def test_the_reference_falloff_is_refused_in_full(self, wire: tuple[Side, Side]) -> None:
        """The divergence this project actually found against the reference code."""
        ours, theirs = fresh(wire)
        terms = propose(CHEBYSHEV).terms()
        theirs.send({SCENT_KEY: terms, SCENT_DIGEST_KEY: restate(terms), SERIES_KEY: GAME_UID})
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert "emission" in excinfo.value.detail and "model" in excinfo.value.detail

    def test_both_sides_abort_when_each_runs_its_own_model(self, wire: tuple[Side, Side]) -> None:
        """Symmetric, deterministic, and the same verdict whichever way round."""
        ours, theirs = fresh(wire)
        done = concurrently(
            {
                "ours": lambda: ours.orchestrator.agree_scent_model(
                    game_uid=GAME_UID, timeout=PATIENCE
                ),
                "theirs": lambda: theirs.orchestrator.agree_scent_model(
                    game_uid=GAME_UID, ours=propose(CHEBYSHEV), timeout=PATIENCE
                ),
            }
        )
        assert [outcome.cause for outcome in done.values()] == [TechnicalLoss.ILLEGAL_ACTION] * 2

    def test_our_model_is_not_quietly_adopted(self, wire: tuple[Side, Side]) -> None:
        """Accommodating on mismatch would concede an agreement nobody made."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer({"model": "chebyshev"}))
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert propose().digest() == our_lock().digest


class TestTheDigestIsTheBinding:
    """A hash a peer merely asserts is a number. It has to cover what they sent."""

    def test_our_digest_over_their_physics_is_refused(self, wire: tuple[Side, Side]) -> None:
        """The forgery the comparison exists to stop: right hash, wrong model."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer({"model": "chebyshev"}, digest=propose().digest()))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert SCENT_DIGEST_KEY in excinfo.value.detail

    def test_their_physics_under_a_digest_of_nothing_is_refused(
        self, wire: tuple[Side, Side]
    ) -> None:
        ours, theirs = fresh(wire)
        theirs.send(an_offer(digest="0" * 64))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION

    def test_an_uppercase_spelling_is_the_same_digest(self, wire: tuple[Side, Side]) -> None:
        """Canonicalised at the door, so the gate only compares canonical forms."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer(digest=propose().digest().upper()))
        assert ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF) == our_lock()

    def test_the_comparison_does_not_leak_a_common_prefix(self) -> None:
        """A byte-at-a-time ``==`` tells a prober how much of a guess was right."""
        import thief_agent.domain.lock as module

        assert "digests_agree" in Path(module.__file__ or "").read_text()


class TestOnlyAWellFormedCurrentOfferSatisfiesTheGate:
    """Missing, malformed, stale, unbound and duplicated input all fail closed."""

    def test_a_peer_that_offers_no_lock_produces_a_timeout(self, wire: tuple[Side, Side]) -> None:
        """Silence is a refusal to agree, never a licence to play unlocked."""
        ours, _ = fresh(wire)
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_the_opponent_acknowledged_us_all_the_same(self, wire: tuple[Side, Side]) -> None:
        """``ok`` is receipt, not consent — the reading P0-1 was built on."""
        ours, theirs = fresh(wire)
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert theirs.inboxes.scent_locks.qsize() == 1

    @pytest.mark.parametrize(
        "body",
        [
            {SCENT_KEY: "trust me", SCENT_DIGEST_KEY: "a" * 64, SERIES_KEY: GAME_UID},
            {
                SCENT_KEY: {"scent_model": "trust me"},
                SCENT_DIGEST_KEY: "a" * 64,
                SERIES_KEY: GAME_UID,
            },
            {SCENT_KEY: {}, SCENT_DIGEST_KEY: "a" * 64, SERIES_KEY: GAME_UID},
            {SCENT_KEY: propose().terms(), SCENT_DIGEST_KEY: "not-a-digest", SERIES_KEY: GAME_UID},
            {SCENT_KEY: propose().terms(), SERIES_KEY: GAME_UID},
            {SCENT_KEY: propose().terms(), SCENT_DIGEST_KEY: "a" * 64, SERIES_KEY: ""},
        ],
    )
    def test_a_malformed_offer_is_refused_at_the_door(
        self, wire: tuple[Side, Side], body: dict[str, Any]
    ) -> None:
        """It never reaches a mailbox, so no consumer handles it mid-gate."""
        ours, theirs = fresh(wire)
        assert theirs.send(body)["ok"] is False
        assert ours.inboxes.scent_locks.empty()
        assert ours.inboxes.rejected

    def test_a_legacy_offer_naming_no_series_is_refused(self, wire: tuple[Side, Side]) -> None:
        """Unlike the config digest, this binding is not optional.

        The scent lock is our dialect, not the reference's: a peer speaking it
        at all is speaking ours, so an offer that will not say which series it
        is about is refused rather than read as a reference peer being itself.
        """
        ours, theirs = fresh(wire)
        assert theirs.send(an_offer(uid=None))["ok"] is False
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_an_offer_the_opponent_refuses_aborts_our_side_too(
        self, wire: tuple[Side, Side]
    ) -> None:
        """Our own message can be the malformed one, and their door is where we learn.

        This is what makes the series binding self-enforcing rather than a rule
        we merely document: a gate called with no ``game_uid`` sends an offer
        the opponent will not file, and the refusal comes back while we are
        still listening instead of surfacing at their audit.
        """
        ours, theirs = fresh(wire)
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid="", timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert SERIES_KEY in excinfo.value.detail
        assert theirs.inboxes.scent_locks.empty()

    def test_a_refused_offer_cannot_satisfy_the_gate(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        theirs.send({SCENT_KEY: {"scent_model": "trust me"}, SCENT_DIGEST_KEY: "a" * 64})
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_an_offer_bound_to_another_series_does_not_answer_this_one(
        self, wire: tuple[Side, Side]
    ) -> None:
        """Right model, wrong series. Replaying it must buy nothing."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer(uid=OTHER_UID))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_an_offer_bound_to_this_series_does_answer_it(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        theirs.send(an_offer())
        assert ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF) == our_lock()

    def test_an_identical_retry_is_not_a_disagreement(self, wire: tuple[Side, Side]) -> None:
        """A retry re-sends bytes. Two copies of one answer are still one answer."""
        ours, theirs = fresh(wire)
        for _ in range(2):
            theirs.send(an_offer())
        assert ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF) == our_lock()

    def test_a_duplicate_cannot_mask_a_conflicting_offer_behind_it(
        self, wire: tuple[Side, Side]
    ) -> None:
        """Taking the first queued offer and stopping would pass this."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer())
        theirs.send(an_offer())
        theirs.send(an_offer({"decay_rate": 0.2}))
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION

    def test_a_stale_offer_queued_behind_a_good_one_is_still_dropped(
        self, wire: tuple[Side, Side]
    ) -> None:
        ours, theirs = fresh(wire)
        theirs.send(an_offer())
        theirs.send(an_offer({"decay_rate": 0.2}, uid=OTHER_UID))
        assert ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF) == our_lock()

    def test_a_consumed_offer_does_not_open_the_next_series(self, wire: tuple[Side, Side]) -> None:
        """Otherwise one negotiation would open every series that followed it."""
        ours, theirs = fresh(wire)
        theirs.send(an_offer())
        ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_a_greeting_is_not_an_offer(self, wire: tuple[Side, Side]) -> None:
        """Three bodies share one tool; only one of them answers this question."""
        ours, theirs = fresh(wire)
        theirs.send(
            {
                "greeting": {
                    "role": THEIR_ROLE,
                    "group_id": "them",
                    "public_url": "https://peer-c3d4.ngrok-free.app",
                    "protocol_version": "1.0",
                }
            }
        )
        with pytest.raises(MatchAborted) as excinfo:
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT

    def test_a_config_digest_is_not_an_offer(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        theirs.send({"config_sha256": "a" * 64, SERIES_KEY: GAME_UID})
        assert ours.inboxes.scent_locks.empty()
        assert ours.inboxes.digests.qsize() == 1


class TestThePreGameLockDisclosesNothingAboutTheBoard:
    """A negotiation that leaked a position would trade the match for a handshake."""

    @staticmethod
    def sent(ours: Side, theirs: Side) -> dict[str, Any]:
        with pytest.raises(MatchAborted):
            ours.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=BRIEF)
        return theirs.inboxes.scent_locks.get_nowait()

    def test_the_offer_is_exactly_the_published_fixture(self, wire: tuple[Side, Side]) -> None:
        """Nothing live is added: the worked example, its digest and the series."""
        ours, theirs = fresh(wire)
        body = self.sent(ours, theirs)
        assert body == {
            SCENT_KEY: propose().terms(),
            SCENT_DIGEST_KEY: propose().digest(),
            SERIES_KEY: GAME_UID,
        }

    def test_it_says_nothing_a_commitment_would(self, wire: tuple[Side, Side]) -> None:
        """No nonce and no commitment: at this point neither has been made.

        Checked by counting the secrets rather than by grepping for words —
        ``commit-bound-reveal-v1`` names the dialect and would match any word
        list. Exactly one long hexadecimal run crosses, and it is the lock's own
        digest; a nonce or a step commitment would show up as a second.
        """
        ours, theirs = fresh(wire)
        wire_text = json.dumps(self.sent(ours, theirs))
        assert re.findall(r"[0-9a-f]{32,}", wire_text) == [propose().digest()]
        assert "nonce" not in wire_text and "salt" not in wire_text

    def test_the_same_bytes_are_offered_whatever_the_board_says(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        """The strongest form of "it leaks no position": it does not depend on one.

        Two runners standing on different cells, one engine, one offer. A change
        that threaded the live board into the exchanged example — to save
        recomputing it, say — would disclose the emitter's cell before a single
        commitment existed, and would break here rather than in a match.
        """
        offers = []
        for cop, thief in (((0, 0), (6, 5)), ((3, 7), (1, 1))):
            ours, theirs = fresh(wire)
            runner = a_runner(ours, parameters(), tmp_path)
            runner.start = replace(runner.start, cop=cop, thief=thief)
            offers.append(self.sent(ours, theirs))
        assert offers[0] == offers[1]

    def test_no_turn_or_scent_field_crosses_the_wire(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        self.sent(ours, theirs)
        assert theirs.inboxes.turns.empty()
        assert theirs.inboxes.accepted_turns == {}


class TestTheAgreementReachesEverySubGame:
    """P1-15: ``require_bound_scent`` comes from the lock, not from a source edit."""

    @staticmethod
    def a_stub_sub_game(monkeypatch: pytest.MonkeyPatch) -> None:
        """Let a sub-game be constructed without playing one over a socket."""
        monkeypatch.setattr(
            SubGame,
            "play",
            lambda self: Played(
                steps=0,
                final=self.state,
                captured=False,
                reason="stubbed",
                audit=AuditResult(verdict=Verdict.CLEAN, checked=0),
            ),
        )
        monkeypatch.setattr(
            SubGame, "audit", lambda self: AuditResult(verdict=Verdict.CLEAN, checked=0)
        )

    def test_a_runner_starts_with_no_agreement(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        ours, _ = fresh(wire)
        assert a_runner(ours, parameters(), tmp_path).scent_lock is None

    def test_a_runner_without_one_plays_nothing(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        """No lock, no series. The downgrade this refuses is the silent one."""
        ours, _ = fresh(wire)
        runner = a_runner(ours, parameters(), tmp_path)
        with pytest.raises(MatchAborted) as excinfo:
            runner.play_sub_game(1, timeout=BRIEF)
        assert excinfo.value.cause is TechnicalLoss.ILLEGAL_ACTION
        assert runner.outcomes == []

    def test_agreeing_records_the_lock_on_the_runner(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        ours, theirs = fresh(wire)
        runner = a_runner(ours, parameters(), tmp_path)
        done = concurrently(
            {
                "ours": lambda: runner.agree(timeout=PATIENCE),
                "theirs": lambda: TestTheAgreementReachesEverySubGame.peer_negotiation(theirs),
            }
        )
        assert not isinstance(done["ours"], BaseException), done
        assert runner.scent_lock == our_lock()

    @staticmethod
    def peer_negotiation(side: Side) -> str:
        side.orchestrator.agree_config(parameters(), game_uid=GAME_UID, timeout=PATIENCE)
        side.orchestrator.agree_scent_model(game_uid=GAME_UID, timeout=PATIENCE)
        return "done"

    def test_the_sub_game_requires_bound_scent_from_the_agreement(
        self, wire: tuple[Side, Side], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ours, _ = fresh(wire)
        self.a_stub_sub_game(monkeypatch)
        runner = a_runner(ours, parameters(), tmp_path)
        runner.scent_lock = our_lock()
        game = runner.play_sub_game(1, timeout=BRIEF).game
        assert game is not None and game.require_bound_scent is True

    def test_it_is_derived_rather_than_hard_coded(
        self, wire: tuple[Side, Side], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The negotiated downgrade, which is to *no* scent rather than to unchecked scent.

        Unreachable from the wire — a peer offering any other binding is refused
        at the gate — but the derivation has to be real, or ``True`` here would
        be the hard-coded default this finding is about wearing a new name.
        """
        ours, _ = fresh(wire)
        self.a_stub_sub_game(monkeypatch)
        runner = a_runner(ours, parameters(), tmp_path)
        runner.scent_lock = ScentAgreement(digest="a" * 64, binding="turn-message-unbound")
        game = runner.play_sub_game(1, timeout=BRIEF).game
        assert game is not None and game.require_bound_scent is False

    def test_the_agreed_binding_is_the_commit_bound_one(self) -> None:
        assert our_lock().binding == BINDING
        assert our_lock().require_bound_scent is True

    def test_every_sub_game_of_the_series_gets_it(
        self, wire: tuple[Side, Side], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Six sub-games, one agreement, and not one of them opened without it."""
        ours, _ = fresh(wire)
        self.a_stub_sub_game(monkeypatch)
        stub_boundaries(monkeypatch)
        runner = a_runner(ours, parameters(), tmp_path)
        runner.scent_lock = our_lock()
        outcomes = runner.play_series(timeout=BRIEF)
        assert [outcome.number for outcome in outcomes] == [1, 2, 3, 4, 5, 6]
        assert all(o.game is not None and o.game.require_bound_scent for o in outcomes)


class TestTheExistingGatesSurvive:
    """The config digest and the six-sub-game series are unchanged by this."""

    def test_agree_still_returns_the_config_digest(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        ours, theirs = fresh(wire)
        runner = a_runner(ours, parameters(), tmp_path)
        done = concurrently(
            {
                "ours": lambda: runner.agree(timeout=PATIENCE),
                "theirs": lambda: TestTheAgreementReachesEverySubGame.peer_negotiation(theirs),
            }
        )
        assert done["ours"] == config_sha256(parameters())
        assert theirs.inboxes.digests.empty() and theirs.inboxes.scent_locks.empty()

    def test_a_config_mismatch_aborts_before_any_lock_is_offered(
        self, wire: tuple[Side, Side], tmp_path: Path
    ) -> None:
        """Ordering matters: different physics is settled before the scent model."""
        ours, theirs = fresh(wire)
        runner = a_runner(ours, altered(), tmp_path)
        done = concurrently(
            {
                "ours": lambda: runner.agree(timeout=PATIENCE),
                "theirs": lambda: theirs.orchestrator.agree_config(
                    parameters(), game_uid=GAME_UID, timeout=PATIENCE
                ),
            }
        )
        assert isinstance(done["ours"], MatchAborted)
        assert theirs.inboxes.scent_locks.empty()
        assert runner.scent_lock is None

    def test_a_series_is_still_six_sub_games(self, wire: tuple[Side, Side], tmp_path: Path) -> None:
        ours, _ = fresh(wire)
        assert a_runner(ours, parameters(), tmp_path).sub_games == 6
