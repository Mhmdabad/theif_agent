"""The opponent's sentence reaches the belief, weighted by what it has earned.

Chapter 4's claim is that this agent has **two** witnesses of unequal honesty:
a trail that cannot lie and a sentence that can. Only the first one was wired.
``received_hints`` kept every sentence an opponent ever sent, verbatim, and
``_observe`` updated the belief from scent alone — so the hint channel was
retained as evidence and never weighed as any.

Everything needed already existed and nothing called it:
:func:`~thief_agent.domain.hints.parse` turns a sentence into a claim,
:func:`~thief_agent.domain.credibility.check` scores that claim against the
trail, and :func:`~thief_agent.domain.inference.update` had accepted ``claim``
and ``reliability`` since it was written. This is the failure mode the modules
in this project keep documenting about each other, found once more.

The tests below are about the *order*, which is the part that is easy to get
backwards: a claim is checked against the trail before it reaches the belief,
so a contradicted sentence is discounted rather than believed and regretted.
"""

from pathlib import Path

from test_subgame import a_subgame as _build  # noqa: E402
from thief_agent.domain.credibility import MIN_RELIABILITY, START_RELIABILITY
from thief_agent.runtime.subgame import SubGame


def a_subgame(tmp_path: Path) -> SubGame:
    """A sub-game, which is where an observation is actually assembled."""
    game, _, _ = _build(tmp_path)
    return game


class TestASentenceBecomesAClaim:
    def test_a_direction_is_read_relative_to_where_we_believe_they_are(
        self, tmp_path: Path
    ) -> None:
        """ "North" means north *of them*, not of the board."""
        game = a_subgame(tmp_path)
        game.belief.update({(4, 4): 1.0})
        claim = game.read_hint("I moved north")
        assert claim, "a readable direction produced no claim"
        assert max(claim, key=lambda cell: claim[cell])[0] < 4

    def test_silence_claims_nothing(self, tmp_path: Path) -> None:
        assert a_subgame(tmp_path).read_hint("") == {}

    def test_an_unrecognised_sentence_claims_nothing(self, tmp_path: Path) -> None:
        """Absent information, not evidence against anything."""
        assert a_subgame(tmp_path).read_hint("good luck out there") == {}

    def test_a_hint_carrying_coordinates_cannot_raise_mid_turn(self, tmp_path: Path) -> None:
        """Refused at the door too; a crash here would be a technical loss for both."""
        assert a_subgame(tmp_path).read_hint("I am at 3,3") == {}


class TestTheClaimIsCheckedBeforeItIsBelieved:
    def test_a_claim_the_trail_contradicts_costs_the_opponent_reliability(
        self, tmp_path: Path
    ) -> None:
        game = a_subgame(tmp_path)
        game.belief.update({(4, 4): 1.0})
        trail = {(7, 7): 0.9}
        game.weigh_hint("I moved north", trail)
        assert game.credibility.reliability < START_RELIABILITY
        assert game.credibility.discredited

    def test_a_claim_the_trail_supports_does_not(self, tmp_path: Path) -> None:
        game = a_subgame(tmp_path)
        game.belief.update({(4, 4): 1.0})
        claim = game.read_hint("I moved north")
        supported = dict.fromkeys(claim, 0.9)
        game.weigh_hint("I moved north", supported)
        assert not game.credibility.discredited
        assert game.credibility.reliability >= START_RELIABILITY

    def test_silence_costs_the_opponent_nothing(self, tmp_path: Path) -> None:
        """A peer that says nothing has not lied."""
        game = a_subgame(tmp_path)
        game.weigh_hint("", {(7, 7): 0.9})
        assert game.credibility.reliability == START_RELIABILITY

    def test_reliability_is_remembered_across_turns(self, tmp_path: Path) -> None:
        """A peer caught once must be cheaper to disbelieve on its next sentence.

        Held on the sub-game rather than rebuilt per turn — a reliability that
        reset every step could not remember a lie at all.
        """
        game = a_subgame(tmp_path)
        game.belief.update({(4, 4): 1.0})
        game.weigh_hint("I moved north", {(7, 7): 0.9})
        after_one_lie = game.credibility.reliability
        game.weigh_hint("I moved north", {(7, 7): 0.9})
        assert game.credibility.reliability < after_one_lie
        assert game.credibility.lies == 2

    def test_reliability_never_reaches_zero(self, tmp_path: Path) -> None:
        """A discredited opponent that starts telling the truth is still worth hearing."""
        game = a_subgame(tmp_path)
        game.belief.update({(4, 4): 1.0})
        for _ in range(40):
            game.weigh_hint("I moved north", {(7, 7): 0.9})
        assert game.credibility.reliability >= MIN_RELIABILITY
        assert game.credibility.reliability > 0.0


class TestTheHintActuallyMovesTheBelief:
    def test_a_supported_claim_raises_the_cells_it_names(self, tmp_path: Path) -> None:
        """The whole point: the sentence is weighed, not merely stored."""
        from thief_agent.domain.inference import update as absorb

        game = a_subgame(tmp_path)
        game.belief.update({(4, 4): 1.0})
        claim = game.read_hint("I moved north")
        named = max(claim, key=lambda cell: claim[cell])
        before = game.belief.at(named)
        absorb(game.belief, dict.fromkeys(claim, 0.9), claim=claim, reliability=0.9)
        assert game.belief.at(named) > before

    def test_a_less_credible_speaker_moves_it_less(self, tmp_path: Path) -> None:
        """Reliability is a weight, not a switch.

        The same sentence, from a trusted speaker and from a discredited one,
        must not land on the belief with the same force — otherwise catching a
        lie would cost the liar nothing.
        """
        from thief_agent.domain.inference import update as absorb

        moved: dict[float, float] = {}
        for reliability in (0.9, 0.1):
            game = a_subgame(tmp_path)
            game.belief.update({(4, 4): 1.0})
            claim = game.read_hint("I moved north")
            named = max(claim, key=lambda cell: claim[cell])
            before = game.belief.at(named)
            absorb(game.belief, dict.fromkeys(claim, 0.9), claim=claim, reliability=reliability)
            moved[reliability] = game.belief.at(named) - before
        assert moved[0.9] > moved[0.1]
