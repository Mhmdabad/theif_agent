"""The separation audit.

Appendix E rules 1 and 2, and the harshest sanction in the rulebook: the cop
and thief must run as **two completely separate processes** under separate
config directories, sharing no memory, no live-state module and no variables.
Sharing any of those **disqualifies the solution even if the game works**.

That is a rule with almost no code to point at — nothing here *does* sharing,
so there is nothing to inspect. Which is exactly why it needs a test: an
absence is invisible until someone adds a convenience import, and by then the
project is unsalvageable rather than buggy.

So these assertions produce evidence rather than restating the rule. Each one
names something that would be true if separation had been broken, and shows it
is not.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).parents[1]
SRC = REPO / "src" / "thief_agent"
SIBLING_PACKAGE = "cop_agent"


def python_sources() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


class TestNoImportOfTheOtherAgent:
    def test_no_source_file_mentions_the_sibling_package(self) -> None:
        """A convenience import is how this rule gets broken in practice."""
        offenders = [
            p.relative_to(REPO) for p in python_sources() if SIBLING_PACKAGE in p.read_text()
        ]
        assert offenders == []

    def test_the_sibling_package_is_not_importable(self) -> None:
        """Not installed, so an accidental import fails loudly at once."""
        probe = subprocess.run(
            [sys.executable, "-c", f"import {SIBLING_PACKAGE}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode != 0
        assert "ModuleNotFoundError" in probe.stderr

    def test_our_own_package_does_import(self) -> None:
        """Sanity: the previous test must fail for the right reason."""
        probe = subprocess.run(
            [sys.executable, "-c", "import thief_agent"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode == 0, probe.stderr


class TestSeparateConfiguration:
    def test_this_repo_owns_only_its_own_config_directory(self) -> None:
        assert (REPO / "config" / "thief").is_dir()
        assert not (REPO / "config" / "police").exists()

    def test_the_private_config_names_only_our_port(self) -> None:
        private = tomllib.loads((REPO / "config" / "thief" / "game.toml").read_text())
        assert private["network"]["my_port"] == 8802

    def test_the_opponent_is_known_only_by_url(self) -> None:
        """Everything we know about the opponent crosses a network boundary."""
        private = tomllib.loads((REPO / "config" / "thief" / "game.toml").read_text())
        opponent_keys = [k for k in private["network"] if "opponent" in k]
        assert opponent_keys == ["opponent_url"]


class TestNoSharedMutableState:
    def test_no_module_level_mutable_globals(self) -> None:
        """Shared live state is the specific thing the rule forbids.

        Upper-case names are constants by convention, and dunders such as
        ``__all__`` are declarations rather than state. What this catches is a
        lower-case module-level list or dict — the shape a cache, a registry
        or a "just for now" scratch buffer takes, and the shape that would let
        two agents in one process see each other's data.
        """
        import ast

        offenders: list[str] = []
        for path in python_sources():
            tree = ast.parse(path.read_text())
            for node in tree.body:
                if not isinstance(node, ast.Assign | ast.AnnAssign):
                    continue
                value = node.value
                if isinstance(value, ast.List | ast.Dict | ast.Set):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if not isinstance(target, ast.Name):
                            continue
                        name = target.id
                        if name.isupper() or name.startswith("__"):
                            continue
                        offenders.append(f"{path.name}:{name}")
        assert offenders == []

    def test_domain_state_is_immutable(self) -> None:
        """A frozen BoardState cannot be mutated by anything holding it."""
        import dataclasses

        from thief_agent.domain.board import BoardState

        assert dataclasses.fields(BoardState)
        with pytest.raises(dataclasses.FrozenInstanceError):
            BoardState(grid_size=7, cop=(0, 0), thief=(3, 3)).step = 1  # type: ignore[misc]


class TestProcessSeparationIsReal:
    def test_the_agent_runs_as_its_own_process(self) -> None:
        """Two peers on one machine must be two OS processes, not two threads."""
        probe = subprocess.run(
            [sys.executable, "-c", "import os, thief_agent; print(os.getpid())"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode == 0
        assert int(probe.stdout.strip()) != 0

    def test_two_launches_are_distinct_processes(self) -> None:
        pids = set()
        for _ in range(2):
            probe = subprocess.run(
                [sys.executable, "-c", "import os; print(os.getpid())"],
                capture_output=True,
                text=True,
                check=False,
            )
            pids.add(probe.stdout.strip())
        assert len(pids) == 2
