"""Appendix E rule 35: the result is agreed before either side reports it.

The rule says both peers agree the outcome and then each sends its own report.
Before this module the report carried a ``result_agreed_with_opponent`` field
that **no code path could ever set to true**: the driver passed a literal
``False``, and no message on the wire conveyed an opponent's assent. Every
report this project produced therefore stated, truthfully but uselessly, that
the result had not been agreed — the field was a placeholder wearing the
costume of a finding.

What is agreed is deliberately narrower than a report. Two honest peers differ
on timestamps, token counts, role and repository URLs, so hashing a whole
report would make them disagree forever. :mod:`thief_agent.shared.result_claim`
is the intersection: which series, and what each sub-game scored for each side.

Three outcomes have to be distinguishable, and only the first is agreement:

* both sides scored the series the same way — agreed;
* the opponent scored it differently — not agreed, and no exception, because
  Appendix E gives neither agent authority to pronounce on a disagreement
  between two teams;
* the opponent never answers — not agreed, for the stronger reason that silence
  is not assent and a report claiming otherwise would be a false statement.

Everything runs against the real path — two FastMCP servers on two sockets, two
``PeerInboxes``, two ``Orchestrator``s and the real ``negotiate`` tool — because
both peers run this gate at the same time, each waiting for a message only the
other can send, and neither may wait before it speaks.
"""

from collections.abc import Callable
from typing import Any

from test_config_agreement import (  # noqa: E402
    BRIEF,
    GAME_UID,
    OTHER_UID,
    PATIENCE,
    Side,
    concurrently,
    fresh,
    wire,
)
from thief_agent.infra.inboxes import RESULT_DIGEST_KEY, RESULT_KEY, SERIES_KEY
from thief_agent.shared.result_claim import claim_sha256, result_claim

__all__ = ["wire"]
"""Re-exported so the module-scoped server fixture is visible to pytest here."""

OURS: list[tuple[int, int]] = [(20, 5), (5, 10), (20, 5), (5, 10), (20, 5), (5, 10)]
"""A whole six-sub-game series, scored from the Appendix F table."""

DISPUTED: list[tuple[int, int]] = [(20, 5), (5, 10), (20, 5), (5, 10), (20, 5), (20, 5)]
"""The same series with the last sub-game scored a capture instead of a survival.

One sub-game, because the disagreement this gate exists to catch is exactly the
one nobody notices: five boards the two teams read identically and a sixth they
did not.
"""


def rows_for(scores: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Trimmed consensus rows for a list of ``(cop, thief)`` scores.

    The scope keys by group, so a test that wants two sides to agree has to
    speak in groups too -- which is the point of the change these tests now
    describe: role-keyed scores were exactly what could never match a
    stranger's digest.
    """
    return [
        {
            "sub_game_number": number,
            "roles": {"a": "police", "b": "thief"},
            "result": "capture" if cop > thief else "survival",
            "winner_group": None if cop == thief else ("a" if cop > thief else "b"),
            "score": {"a": cop, "b": thief},
        }
        for number, (cop, thief) in enumerate(scores, start=1)
    ]


def settle(
    side: Side, scores: list[tuple[int, int]], uid: str = GAME_UID, timeout: float = PATIENCE
) -> Callable[[], bool]:
    """One side's half of the exchange, ready to run beside the other's."""
    claim = result_claim(uid, rows_for(scores))
    return lambda: side.orchestrator.agree_result(claim, claim_sha256(claim), uid, timeout)


class TestTwoPeersWhoPlayedTheSameMatch:
    def test_identical_scores_agree(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        done = concurrently({"ours": settle(ours, OURS), "theirs": settle(theirs, OURS)})
        assert done == {"ours": True, "theirs": True}

    def test_the_claim_does_not_depend_on_which_side_builds_it(self) -> None:
        """``(cop, thief)`` in both repositories, never "ours" and "theirs".

        A claim phrased from the sender's point of view would be two different
        claims, and two honest peers could never match.
        """
        assert claim_sha256(result_claim(GAME_UID, rows_for(OURS))) == claim_sha256(
            result_claim(GAME_UID, rows_for(list(OURS)))
        )

    def test_it_carries_the_scope_every_conformant_team_hashes(self) -> None:
        """Three keys, and rows trimmed to five.

        Anything a peer may legitimately differ on -- its timestamps, its token
        counts, its own commit -- is out, because a scope containing them is
        per-side by construction and could never equal a stranger's.
        """
        claim = result_claim(GAME_UID, rows_for(OURS))
        assert sorted(claim) == ["aggregate", "game_id", "sub_games"]
        assert sorted(claim["sub_games"][0]) == [
            "result",
            "roles",
            "score",
            "sub_game_number",
            "winner_group",
        ]
        assert [entry["sub_game_number"] for entry in claim["sub_games"]] == [1, 2, 3, 4, 5, 6]


class TestTwoPeersWhoDisagree:
    def test_one_differing_sub_game_is_not_agreement(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        done = concurrently({"ours": settle(ours, OURS), "theirs": settle(theirs, DISPUTED)})
        assert done == {"ours": False, "theirs": False}

    def test_disagreement_raises_nothing(self, wire: tuple[Side, Side]) -> None:
        """The match is over; there is no series left to abort.

        Every other gate in this neighbourhood aborts, and this one must not:
        a disagreement between two teams is settled by the two teams.
        """
        ours, theirs = fresh(wire)
        done = concurrently({"ours": settle(ours, OURS), "theirs": settle(theirs, DISPUTED)})
        assert not [value for value in done.values() if isinstance(value, BaseException)]


class TestAnOpponentWhoNeverAnswers:
    def test_silence_is_not_assent(self, wire: tuple[Side, Side]) -> None:
        """A peer that publishes nothing has agreed to nothing."""
        ours, _ = fresh(wire)
        assert settle(ours, OURS, timeout=BRIEF)() is False

    def test_a_claim_about_another_series_does_not_settle_this_one(
        self, wire: tuple[Side, Side]
    ) -> None:
        """A result agreed for one series cannot be replayed to close another."""
        ours, theirs = fresh(wire)
        stale = result_claim(OTHER_UID, rows_for(OURS))
        theirs.orchestrator.call_opponent(
            "negotiate",
            {
                "message": {
                    RESULT_KEY: stale,
                    RESULT_DIGEST_KEY: claim_sha256(stale),
                    SERIES_KEY: OTHER_UID,
                }
            },
        )
        assert settle(ours, OURS, timeout=BRIEF)() is False


class TestWhatArrivesAtTheDoor:
    def test_a_claim_is_filed_apart_from_greetings_and_digests(
        self, wire: tuple[Side, Side]
    ) -> None:
        """A fourth mailbox: the other three are drained on a different schedule."""
        ours, theirs = fresh(wire)
        claim = result_claim(GAME_UID, rows_for(OURS))
        body: dict[str, Any] = {
            RESULT_KEY: claim,
            RESULT_DIGEST_KEY: claim_sha256(claim),
            SERIES_KEY: GAME_UID,
        }
        assert theirs.send(body) == {"ok": True}
        assert ours.inboxes.results.qsize() == 1
        assert ours.inboxes.agreements.empty() and ours.inboxes.digests.empty()

    def test_a_claim_without_a_series_is_refused_at_the_door(self, wire: tuple[Side, Side]) -> None:
        """This body is our dialect, so a claim that will not say which series is unreadable."""
        ours, theirs = fresh(wire)
        claim = result_claim(GAME_UID, rows_for(OURS))
        reply = theirs.send({RESULT_KEY: claim, RESULT_DIGEST_KEY: claim_sha256(claim)})
        assert reply["ok"] is False
        assert ours.inboxes.results.empty()

    def test_a_claim_with_a_malformed_digest_is_refused(self, wire: tuple[Side, Side]) -> None:
        ours, theirs = fresh(wire)
        claim = result_claim(GAME_UID, rows_for(OURS))
        reply = theirs.send(
            {RESULT_KEY: claim, RESULT_DIGEST_KEY: "not-a-digest", SERIES_KEY: GAME_UID}
        )
        assert reply["ok"] is False
        assert ours.inboxes.results.empty()
