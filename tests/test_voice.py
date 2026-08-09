"""The hint generator runs in a match, and what it costs is measured.

Appendix F table 21 gives four providers for the deception text and says the
move is *always* algorithmic Python. The providers were all implemented and
:meth:`~thief_agent.strategy.base.BrainBase._hint` returned a constant string,
so none of them ever ran: both agents said *"I am watching the streets"* on
every one of the thirty-five steps of all six sub-games, ``Intent``,
``Bluffer``, ``Ration`` and ``TokenLedger`` never executed, and the report's
``total_tokens`` was a hardcoded zero that was true only by accident.

Two properties are load-bearing and easy to get wrong:

**The voice must not touch the policy's randomness.** Phrasing draws from an
RNG; drawing from the *brain's* generator would make what we said change where
we went, and a replay that re-derives moves from the same seed would diverge.
``test_determinism`` asserts the policy's stream is untouched — this module
asserts the other half, that hints are still reproducible from a seed.

**Nothing here may cost a turn.** A hint is worth few marks; a turn unanswered
inside the thirty-second deadline is a technical loss scoring zero for *both*
sides. So every provider failure returns the composed template line, and no
path through the voice raises.
"""

import re
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.infra.validation import require_hint
from thief_agent.strategy.thief_brain import ThiefBrain
from thief_agent.strategy.voice_config import build_voice

BOARD = BoardState(grid_size=8, cop=(0, 0), thief=(6, 5), barriers=frozenset(), step=0)
CONTEXT: dict[str, Any] = {"threat": 0.5, "concentration": 0.5, "uncertainty": 0.5}


def hints(brain: ThiefBrain, turns: int = 6) -> list[str]:
    return [brain.decide(BOARD, **CONTEXT).hint for _ in range(turns)]


class TestTheHintIsComposedNotConstant:
    def test_the_agent_no_longer_repeats_one_sentence(self) -> None:
        """The exact defect: one string, every step, every sub-game."""
        spoken = hints(ThiefBrain())
        assert len(set(spoken)) > 1
        assert "I am watching the streets" not in spoken

    def test_every_hint_is_one_the_door_would_accept(self) -> None:
        """Within the Appendix F word cap and naming no coordinates (rule 27)."""
        for hint in hints(ThiefBrain()):
            require_hint({"hint": hint}, max_words=15)

    def test_hints_are_natural_language_about_places(self) -> None:
        assert any(hint.strip() for hint in hints(ThiefBrain()))


class TestReproducibility:
    def test_the_same_seed_says_the_same_things(self) -> None:
        """A match that cannot be replayed cannot be audited."""
        assert hints(ThiefBrain(seed=7)) == hints(ThiefBrain(seed=7))

    def test_different_seeds_say_different_things(self) -> None:
        assert hints(ThiefBrain(seed=1)) != hints(ThiefBrain(seed=2))

    def test_speaking_never_advances_the_policys_stream(self) -> None:
        """The whole reason the voice carries its own generator.

        ``test_determinism`` owns this guarantee for the policy; it is asserted
        here too because *this* is the change that would break it.
        """
        brain = ThiefBrain(seed=3)
        before = brain.rng.getstate()
        hints(brain)
        assert brain.rng.getstate() == before


class TestChoosingAProvider:
    def test_the_default_is_the_zero_token_template(self) -> None:
        voice = build_voice(None)
        assert voice.ration.bluffer.provider == "template"
        assert voice.spent == 0

    def test_the_documented_key_is_the_one_that_is_read(self) -> None:
        """The config documents ``provider``; the old caller read ``model``."""
        assert build_voice({"provider": "claude_api"}).ration.bluffer.provider == "claude_api"

    def test_the_cloud_model_defaults_to_a_small_one(self) -> None:
        """Appendix F table 21 asks for a small cloud model."""
        assert build_voice({"provider": "claude_api"}).ration.bluffer.model == "claude-haiku-4-5"

    def test_an_unknown_provider_is_refused_at_load(self) -> None:
        """A typo discovered at move one is a forfeited series."""
        with pytest.raises(ValueError, match="provider must be one of"):
            build_voice({"provider": "gpt-4"})

    def test_the_series_budget_comes_from_the_book(self) -> None:
        assert build_voice({}).ration.budget == 200_000


class TestWhatSpeakingCosts:
    def test_the_template_provider_is_free(self) -> None:
        brain = ThiefBrain()
        hints(brain, turns=10)
        assert brain.voice.spent == 0

    def test_measured_usage_is_charged_when_the_provider_reports_it(self) -> None:
        """Rule 54's total must be a measurement, not arithmetic."""
        voice = build_voice({"provider": "claude_api", "every_n_steps": 1})

        def measured(text: str) -> str:
            voice.ration.bluffer.last_tokens = 37
            return "heading north past the park"

        voice.ration.bluffer._claude_api = measured  # type: ignore[method-assign]
        for _ in range(3):
            voice.say((6, 5), BOARD, (0, 0))
        assert voice.spent == 111

    def test_a_provider_that_reports_nothing_falls_back_to_the_estimate(self) -> None:
        """Erring high: being caught over an agreed budget is the worse failure."""
        voice = build_voice({"provider": "ollama", "every_n_steps": 1})
        voice.ration.bluffer._ollama = lambda text: "somewhere south"  # type: ignore[method-assign]
        voice.say((6, 5), BOARD, (0, 0))
        assert voice.spent == 1250

    def test_a_failing_provider_costs_a_template_line_not_the_turn(self) -> None:
        """No hint is worth a technical loss scoring zero for both sides."""
        voice = build_voice({"provider": "claude_api", "every_n_steps": 1})

        def broken(text: str) -> str:
            raise RuntimeError("no network")

        voice.ration.bluffer._claude_api = broken  # type: ignore[method-assign]
        spoken = voice.say((6, 5), BOARD, (0, 0))
        require_hint({"hint": spoken}, max_words=15)
        assert voice.ration.bluffer.failures == 1


class TestTheKeyIsNeverCommitted:
    def test_no_api_key_appears_in_the_shipped_config(self) -> None:
        """Appendix C makes a leaked key a submission gate.

        Naming the environment variable in a comment is the *instruction* not
        to commit one, so this looks for a key value rather than the variable
        name: an assigned secret, not a mention of where the real one lives.
        """
        config = (Path(__file__).resolve().parent.parent / "config/thief/game.toml").read_text()
        assert "sk-ant" not in config
        assert not re.search(r"""(?i)(api_?key|token|secret)\s*=\s*['"]\S""", config)

    def test_the_provider_reads_the_key_from_the_environment(self) -> None:
        """The SDK resolves it; nothing here accepts one as configuration."""
        source = (
            Path(__file__).resolve().parent.parent / "src/thief_agent/domain/providers_backends.py"
        ).read_text()
        assert "api_key" not in source
