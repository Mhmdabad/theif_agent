"""One `game_uid` across all four files, and every name derived from `game_id`.

With up to ten counted matches of six sub-games each, a repository ends up
holding sixty logs, sixty configs, ten declarations and ten results. The naming
discipline is not tidiness — it is what keeps the evidence trail able to answer
"which files belong to which match" without anybody's memory being involved.

Two identifiers, doing different jobs:

* **``game_id``** is the *filename* component. It is constrained to characters
  that are safe in a path (:mod:`..shared.naming`), and it is what a person
  reads off a directory listing.
* **``game_uid``** is the *content* identifier. It appears inside all four
  files and is what ties a log to the declaration that fixed the match. It has
  no filename constraints because it never becomes one.

Keeping them separate matters because they fail differently. Two matches with
the same ``game_id`` overwrite each other's files — loud, immediate, obvious.
Two matches with the same ``game_uid`` produce files that all look valid and
cross-reference the wrong match — silent, and discovered at an audit if at all.

**This module does not generate identifiers; it checks a set of artefacts
agrees on one.** Minting a uid is a job for whoever starts a match, and a
function that both minted and verified would be reduced, on the first awkward
bug, to minting a fresh one to make the check pass.
"""

from dataclasses import dataclass
from pathlib import Path

from ..shared.naming import (
    config_filename,
    declaration_filename,
    log_filename,
    result_filename,
)
from .config_file import LockedConfig
from .declaration import MatchDeclaration
from .match_log import MatchLog
from .report import Report


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


@dataclass(frozen=True, slots=True)
class ArtefactSet:
    """The four mandatory files for one match, as one object.

    ``configs`` and ``logs`` are per sub-game; the declaration and the result
    are per match. The shapes differ because the rulebook's files do.
    """

    declaration: MatchDeclaration
    configs: tuple[LockedConfig, ...]
    logs: tuple[MatchLog, ...]
    result: Report

    @property
    def game_id(self) -> str:
        return self.declaration.game_id

    @property
    def game_uid(self) -> str:
        """The declaration's uid is the one the others must match.

        Somebody has to be authoritative or "they disagree" has no direction,
        and the declaration is the document written first and signed. It is
        also the only one of the four that *cannot* be built without a uid, so
        this is never empty and :meth:`check` does not test for it.
        """
        return self.declaration.game_uid

    def filenames(self) -> tuple[str, ...]:
        """Every filename this set produces, derived mechanically."""
        return (
            declaration_filename(self.game_id),
            *(config_filename(self.game_id, config.sub_game) for config in self.configs),
            *(log_filename(self.game_id, log.sub_game) for log in self.logs),
            result_filename(self.game_id),
        )

    def check(self) -> Coherence:
        """Every disagreement about identity, collected at once.

        Reported rather than raised, and reported *whole*. An examiner fixing
        one mismatch only to be told about the next is being made to do a
        search this function has already done.
        """
        problems: list[str] = []
        for config in self.configs:
            if config.game_id != self.game_id:
                problems.append(
                    f"config g{config.sub_game:02d} is for game {config.game_id!r}, "
                    f"not {self.game_id!r}"
                )
            if config.game_uid != self.game_uid:
                problems.append(f"config g{config.sub_game:02d} has a different game_uid")

        for log in self.logs:
            if log.game_id != self.game_id:
                problems.append(
                    f"log g{log.sub_game:02d} is for game {log.game_id!r}, not {self.game_id!r}"
                )
            if log.game_uid != self.game_uid:
                problems.append(f"log g{log.sub_game:02d} has a different game_uid")

        if self.result.game_id != self.game_id:
            problems.append(f"the result is for game {self.result.game_id!r}")
        if self.result.game_uid != self.game_uid:
            problems.append("the result has a different game_uid")

        problems.extend(self._structural())
        return Coherence(tuple(problems))

    def _structural(self) -> list[str]:
        """Disagreements about *how many* sub-games there were.

        A config with no log means a sub-game was agreed and never played; a log
        with no config means one was played under parameters nobody recorded.
        Both are holes in the evidence rather than mismatched strings, and an
        identity check that ignored them would pass a set nobody can audit.
        """
        problems: list[str] = []
        configs = {config.sub_game for config in self.configs}
        logs = {log.sub_game for log in self.logs}
        reported = {entry.sub_game for entry in self.result.sub_games}

        if len(configs) != len(self.configs):
            problems.append("two configs claim the same sub-game")
        if len(logs) != len(self.logs):
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

    def write(self, directory: Path) -> tuple[Path, ...]:
        """Write all four kinds of file, refusing an incoherent set.

        Raises:
            ArtefactError: if :meth:`check` finds anything. Writing a set that
                cross-references the wrong match produces files that each look
                valid on their own, which is the failure mode worth refusing at
                the only moment it is cheap to catch.
        """
        coherence = self.check()
        if not coherence.coherent:
            raise ArtefactError(f"refusing to write an incoherent artefact set — {coherence}")
        written = [self.declaration.write(directory)]
        written.extend(config.write(directory) for config in self.configs)
        written.extend(log.write(directory) for log in self.logs)
        written.append(self.result.write(directory))
        return tuple(written)
