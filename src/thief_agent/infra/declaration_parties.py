"""The named parties of a declaration: the teams, and the MCP addresses.

Split out of :mod:`.declaration` to keep each module inside the line budget.
These are the value objects a declaration is assembled from, together with the
error they raise when the rulebook requires something that is not there.
"""

from dataclasses import dataclass
from typing import Any


class DeclarationError(ValueError):
    """Raised when a declaration is missing something the rulebook requires."""


@dataclass(frozen=True, slots=True)
class Team:
    """One side: who they are, and the two repositories their agents came from."""

    name: str
    members: tuple[str, ...]
    cop_repo: str
    thief_repo: str

    def __post_init__(self) -> None:
        if not self.name:
            raise DeclarationError("a team needs a name")
        if not self.members:
            raise DeclarationError(f"team {self.name!r} declares no members")
        for label, url in (("cop_repo", self.cop_repo), ("thief_repo", self.thief_repo)):
            if not url:
                raise DeclarationError(
                    f"team {self.name!r} has no {label}; FR-7.28 requires four repository "
                    "links in total, and a result that cannot be traced to code is not one"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "members": list(self.members),
            "cop_repo": self.cop_repo,
            "thief_repo": self.thief_repo,
        }


@dataclass(frozen=True, slots=True)
class Endpoints:
    """Where the two MCP servers were reachable when the match was declared."""

    ours: str
    theirs: str

    def __post_init__(self) -> None:
        for label, url in (("ours", self.ours), ("theirs", self.theirs)):
            if not url:
                raise DeclarationError(f"the {label} MCP address is empty")

    def to_dict(self) -> dict[str, str]:
        return {"ours": self.ours, "theirs": self.theirs}
