"""The rules by which four artefacts are judged to describe one match.

They live beside :class:`~.artefacts.ArtefactSet` rather than inside it because
they are what a reader checks against the rulebook, and a rulebook is easier to
check when every disagreement it can report is written in one file. The set
asks the questions; this module knows what counts as an answer.

Nothing here writes anything, and nothing here raises: the checks return what
they found and leave the decision to refuse to the caller that holds the files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .artefacts import ArtefactSet


class ArtefactError(ValueError):
    """Raised when a match's files do not agree about which match they describe."""


@dataclass(frozen=True, slots=True)
class Coherence:
    """Whether a set of artefacts describes one match, and what disagrees if not."""

    problems: tuple[str, ...] = ()

    @property
    def coherent(self) -> bool:
        return not self.problems

    def __str__(self) -> str:
        if self.coherent:
            return "all four artefacts agree on one match"
        return "the artefacts disagree: " + "; ".join(self.problems)


def identity_problems(artefacts: ArtefactSet) -> list[str]:
    """Disagreements about *which match* the four files name.

    Every file carries both identifiers, so every file can contradict the
    declaration in two independent ways, and each contradiction is reported on
    its own terms rather than collapsed into one "these do not match".
    """
    problems: list[str] = []
    for config in artefacts.configs:
        if config.game_id != artefacts.game_id:
            problems.append(
                f"config g{config.sub_game:02d} is for game {config.game_id!r}, "
                f"not {artefacts.game_id!r}"
            )
        if config.game_uid != artefacts.game_uid:
            problems.append(f"config g{config.sub_game:02d} has a different game_uid")

    for log in artefacts.logs:
        if log.game_id != artefacts.game_id:
            problems.append(
                f"log g{log.sub_game:02d} is for game {log.game_id!r}, not {artefacts.game_id!r}"
            )
        if log.game_uid != artefacts.game_uid:
            problems.append(f"log g{log.sub_game:02d} has a different game_uid")

    if artefacts.result.game_id != artefacts.game_id:
        problems.append(f"the result is for game {artefacts.result.game_id!r}")
    if artefacts.result.game_uid != artefacts.game_uid:
        problems.append("the result has a different game_uid")
    return problems


def structural_problems(artefacts: ArtefactSet) -> list[str]:
    """Disagreements about *how many* sub-games there were.

    A config with no log means a sub-game was agreed and never played; a log
    with no config means one was played under parameters nobody recorded.
    Both are holes in the evidence rather than mismatched strings, and an
    identity check that ignored them would pass a set nobody can audit.
    """
    problems: list[str] = []
    configs = {config.sub_game for config in artefacts.configs}
    logs = {log.sub_game for log in artefacts.logs}
    reported = {entry.sub_game for entry in artefacts.result.sub_games}

    if len(configs) != len(artefacts.configs):
        problems.append("two configs claim the same sub-game")
    if len(logs) != len(artefacts.logs):
        problems.append("two logs claim the same sub-game")
    for missing in sorted(configs - logs):
        problems.append(f"sub-game {missing} has a config but no log")
    for missing in sorted(logs - configs):
        problems.append(f"sub-game {missing} has a log but no config")
    for missing in sorted(reported - logs):
        problems.append(f"the result reports sub-game {missing}, which has no log")
    for missing in sorted(logs - reported):
        problems.append(f"sub-game {missing} was played but is not in the result")
    return problems
