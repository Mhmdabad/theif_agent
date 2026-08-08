"""Which code played, established from git rather than asserted.

Split out of :mod:`step_zero`, which re-exports every name here. See that
module for why the commit hash alone is not enough to be reproducible.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which code played, for which team, in which sub-game.

    The rulebook's reason for the commit hash is reconstruction: teams may
    change their code between matches, so every match declares the exact commit
    it ran, and the examiner can check out that commit and replay. A hash that
    does not describe what actually ran defeats the whole clause.

    Which is why :attr:`dirty` exists. ``git rev-parse HEAD`` answers happily
    while the working tree has uncommitted changes, and the answer is then a
    commit that is **not** the code being executed. That is not a small
    inaccuracy in a signed document — it is a declaration nobody can verify,
    and it is the easy mistake to make five minutes before a match.
    """

    code_version: str
    group_name: str
    sub_game: int
    github_commit: str | None
    dirty: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_version": self.code_version,
            "group_name": self.group_name,
            "sub_game": self.sub_game,
            "github_commit": self.github_commit,
            "working_tree_dirty": self.dirty,
        }

    @property
    def reproducible(self) -> bool:
        """Whether the examiner could check this commit out and get this code."""
        return self.github_commit is not None and not self.dirty

    def __str__(self) -> str:
        if self.reproducible and self.github_commit:
            return f"{self.group_name} sub-game {self.sub_game} at {self.github_commit[:12]}"
        reason = "uncommitted changes" if self.dirty else "no commit hash available"
        return (
            f"{self.group_name} sub-game {self.sub_game}: NOT REPRODUCIBLE ({reason}); "
            "the declared commit does not describe the code that ran"
        )


def _git(*args: str, repo: Path | None = None) -> str | None:
    """Run a git command, or ``None`` if git or the repository is absent.

    Absent is a real state: a submitted tarball has no ``.git``, and an agent
    that refused to start there would be unrunnable exactly where the examiner
    runs it.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def provenance(
    code_version: str,
    group_name: str,
    sub_game: int,
    repo: Path | None = None,
) -> Provenance:
    """Establish which code is running, and whether that can be proven.

    ``dirty`` is determined by ``git status --porcelain`` rather than inferred.
    An empty result means the tree matches the commit; anything else means the
    hash describes something other than what is executing.
    """
    commit = _git("rev-parse", "HEAD", repo=repo)
    status = _git("status", "--porcelain", repo=repo)
    return Provenance(
        code_version=code_version,
        group_name=group_name,
        sub_game=sub_game,
        github_commit=commit,
        dirty=bool(status),
    )
