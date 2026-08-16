"""The configured brain must be the brain that actually plays.

Appendix F §5 gives a team one key — ``[strategy] thief_class`` — to swap the
decision engine for its own. :func:`~thief_agent.strategy.loader.load_brain`
honours it, and ``tests/test_strategy.py`` proves that thoroughly. What no test
covered is the *hand-off*: whether the driver gives the loader the ``[strategy]``
table or something else.

It gave it the whole private TOML dict, which has no ``thief_class`` key at the
top level, so the loader found nothing and fell back to the shipped heuristic —
**silently**, because falling back is the documented behaviour of an absent
section and the loader cannot tell an absent section from a mis-passed one. A
team pointing the key at its own brain would have played the stock policy for a
whole series and never been told. This is the failure mode with no symptom: no
exception, no warning, a green suite on both sides of the seam.

So the assertion here is deliberately about the argument, not only about the
result. Checking that a custom class comes back proves the wiring today;
checking that the loader was handed ``private["strategy"]`` is what keeps the
next refactor from re-introducing the same silence.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.axes import AxisConvention
from thief_agent.infra.handshake import Greeting, Peering
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.runtime import driver
from thief_agent.runtime.orchestrator import PROTOCOL_VERSION
from thief_agent.strategy.base import BrainBase
from thief_agent.strategy.loader import load_brains
from thief_agent.strategy.thief_brain import ThiefBrain


class SpyBrain(ThiefBrain):
    """A team's own brain, in the only shape the config can name: an import path.

    Subclassing the shipped policy rather than :class:`BrainBase` directly keeps
    the test about the wiring: this is a legal brain in every respect, so the
    only reason it would not play is that nobody loaded it.
    """


STRATEGY = {"thief_class": f"{__name__}:SpyBrain"}
"""What a team would write under ``[strategy]``, pointing at its own class."""


def private_config(strategy: dict[str, Any] | None = None) -> dict[str, Any]:
    """A private config in the shape ``config/thief/game.toml`` is read into."""
    config: dict[str, Any] = {
        "version": "1.0",
        "game": {
            "group_id": "z-team",
            "group_name": "z-team",
            "members": ["a"],
            "repos": {"cop": "https://example.invalid/cop", "thief": "https://example.invalid/th"},
        },
        "teams": {
            "them": {
                "group_name": "a-team",
                "members": ["b"],
                "repos": {
                    "cop": "https://example.invalid/their-cop",
                    "thief": "https://example.invalid/their-thief",
                },
            }
        },
        "network": {"my_port": 8802, "opponent_url": "http://127.0.0.1:8801/mcp"},
    }
    if strategy is not None:
        config["strategy"] = strategy
    return config


PARAMETERS: dict[str, Any] = {
    "board_and_agents": {"grid_size": 8, "cop_start": [0, 0], "thief_start": [6, 5]},
    "movement_and_barriers": {"max_moves": 35, "max_barriers": 14},
    "network_and_league": {"token_budget_per_series": 200_000, "num_games": 6},
    "pheromones": {
        "pheromone_grid_size": 5,
        "pheromone_decay": 0.1,
        "pheromone_center_intensity": 0.9,
    },
}
"""Stands in for ``config/game.json`` so the test does not depend on the cwd.

Complete enough to derive the fourteen negotiated terms, because the
declaration now hashes those for ``game_uid`` -- a partial config cannot open a
match, and a fixture that pretends otherwise tests a state that cannot occur."""


class StubTransport:
    """Closed in the driver's ``finally``; opens no socket."""

    def close(self) -> None:
        return None


class StubOrchestrator:
    """Answers the greeting. The handshake proper is stubbed out below."""

    def __init__(self, *, inboxes: PeerInboxes, client: object, role: str) -> None:
        self.role = role

    def greeting(self, address: str, group_id: str) -> Greeting:
        return Greeting(
            role=self.role,
            group_id=group_id,
            public_url="https://ours.example.com/mcp",
            protocol_version=PROTOCOL_VERSION,
        )


class RecordingRunner:
    """Records the arguments the driver assembles, then plays nothing."""

    built: list["RecordingRunner"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        RecordingRunner.built.append(self)

    opponent_played_fairly = True
    spent_tokens = 0

    def agree(self) -> None:
        return None

    def play_series(self) -> list[None]:
        return []

    def agree_result(self) -> bool:
        return True

    @property
    def directory(self) -> Path:
        """Where a real runner writes, and where the league ledger sits beside it."""
        value = self.kwargs["directory"]
        assert isinstance(value, Path)
        return value

    def failures(self) -> list[str]:
        """Empty on a clean series, as the real runner's is."""
        return []

    @property
    def brain(self) -> BrainBase:
        """The brain a real runner holds, and reads the token total off."""
        value = self.kwargs["brain"]
        assert isinstance(value, BrainBase)
        return value

    def result(self, **kwargs: object) -> None:
        return None

    def write(self, report: object) -> tuple[Path, ...]:
        return ()


Match = Callable[[dict[str, Any]], tuple[list[dict[str, Any] | None], RecordingRunner]]
"""What the fixture hands a test: run a match, get back what the driver did."""


@pytest.fixture
def match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Match:
    """Run ``open_match`` far enough to build the runner, off the network."""

    def run(private: dict[str, Any]) -> tuple[list[dict[str, Any] | None], RecordingRunner]:
        seen: list[dict[str, Any] | None] = []

        def spy(
            strategy: dict[str, Any] | None,
            axes: AxisConvention | None = None,
            seed: int = 0,
            trash_talk: dict[str, Any] | None = None,
        ) -> dict[str, BrainBase]:
            seen.append(strategy)
            return load_brains(strategy, axes, seed, trash_talk)

        RecordingRunner.built.clear()
        monkeypatch.setattr(driver, "load_brains", spy)
        monkeypatch.setattr(driver, "MatchRunner", RecordingRunner)
        monkeypatch.setattr(driver, "Orchestrator", StubOrchestrator)
        monkeypatch.setattr(driver, "FastMcpTransport", StubTransport)
        monkeypatch.setattr(driver, "load_shared", lambda path: PARAMETERS)
        monkeypatch.setattr(
            driver,
            "await_opponent",
            lambda orchestrator, ours, directory, game_id, **kw: Peering(
                ours=ours,
                theirs=Greeting(
                    "police", "a-team", "https://theirs.example.com/mcp", PROTOCOL_VERSION
                ),
                sub_game=1,
            ),
        )
        driver.open_match(
            inboxes=PeerInboxes(),
            private=private,
            environ={},
            game_id="a-team-vs-z-team",
            directory=tmp_path,
            rehearsal=True,
        )
        return seen, RecordingRunner.built[-1]

    return run


class TestTheStrategyTableReachesTheLoader:
    def test_the_loader_is_handed_the_strategy_table(self, match: Match) -> None:
        """Not the whole private dict, which has no ``thief_class`` in it."""
        seen, _ = match(private_config(STRATEGY))
        assert seen == [STRATEGY]

    def test_a_configured_brain_is_the_one_that_plays(self, match: Match) -> None:
        """The point of the key: our class, not the shipped heuristic."""
        _, runner = match(private_config(STRATEGY))
        assert isinstance(runner.kwargs["brains"]["thief"], SpyBrain)  # type: ignore[index]

    def test_an_absent_section_still_runs_the_shipped_brain(self, match: Match) -> None:
        """The documented default has to survive the fix."""
        _, runner = match(private_config())
        brain = runner.kwargs["brains"]["thief"]  # type: ignore[index]
        assert isinstance(brain, ThiefBrain) and not isinstance(brain, SpyBrain)

    def test_an_absent_section_hands_the_loader_nothing(self, match: Match) -> None:
        """``None``, so the loader's own fallback decides — not a stray dict."""
        seen, _ = match(private_config())
        assert seen == [None]
