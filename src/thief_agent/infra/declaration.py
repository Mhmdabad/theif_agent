"""``declaration_<game_id>.json`` — everything that does not change during a match.

The pre-game declaration is the fixed point the rest of the evidence hangs from.
It names who played, which four repositories the code came from, what hardware
and model ran it, and what token ceiling was agreed — all before a single move,
and all under one signature. Anything asserted afterwards that contradicts it is
contradicting a document both sides accepted before either knew the outcome.

**This module builds the file the two teams share.** :mod:`.step_zero` already
produces our own half — hardware, provenance, signature — which is a statement
about *this machine*. The declaration is a statement about *this match*, and it
carries both.

Three decisions worth stating:

**Everything mandatory is required at construction.** FR-7.28 names four
repository links; the rulebook adds teams and members, MCP addresses, the LLM
model, the token ceiling and the times. A declaration missing any of them is not
a weaker declaration, it is a different document — so it cannot be built. The
error then arrives while somebody is looking at the code that omitted the field,
rather than at the moment two agents try to agree.

**The signature covers the content and not itself.** :func:`content` and
:meth:`MatchDeclaration.to_dict` differ by exactly the signature. Keeping them
apart is what stops a document from being signed over a copy of its own
signature — which verifies, and means nothing.

**`ended_at` is deliberately mutable and unsigned at declaration time.** It is
not knowable before the match, and pretending otherwise would either mean
signing a placeholder or delaying the signature until the evidence it fixes has
already been produced. It is recorded by :meth:`MatchDeclaration.concluded`,
which re-signs — so the final file is signed, and the *pre-game* commitment is
still checkable from the fields that were fixed before play.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..shared.naming import declaration_filename
from .step_zero import Hardware, Provenance, sign, statement


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


@dataclass(frozen=True, slots=True)
class MatchDeclaration:
    """The pre-game declaration, ready to sign and write."""

    game_id: str
    game_uid: str
    role: str
    us: Team
    them: Team
    endpoints: Endpoints
    hardware: Hardware
    provenance: Provenance
    llm_model: str
    token_ceiling: int
    started_at: str
    ended_at: str = ""
    signature: str = ""

    def __post_init__(self) -> None:
        if not self.game_uid:
            raise DeclarationError("every artefact of a match shares a game_uid; this has none")
        if not self.llm_model:
            raise DeclarationError(
                "the declared LLM model is empty; it is one of the things the "
                "declaration exists to fix before anybody sees a result"
            )
        if self.token_ceiling <= 0:
            raise DeclarationError(
                f"the agreed token ceiling must be positive, got {self.token_ceiling}"
            )
        if not self.started_at:
            raise DeclarationError("a declaration with no start time fixes nothing in time")
        if self.us.name == self.them.name:
            raise DeclarationError(f"both teams are called {self.us.name!r}")

    @property
    def repositories(self) -> dict[str, str]:
        """All four links, flat, the way the result file wants them."""
        return {
            "cop_repo": self.us.cop_repo,
            "thief_repo": self.us.thief_repo,
            "opponent_cop_repo": self.them.cop_repo,
            "opponent_thief_repo": self.them.thief_repo,
        }

    def content(self) -> dict[str, Any]:
        """Everything the signature covers. Never includes the signature."""
        return {
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "declared_by": self.role,
            "teams": {"us": self.us.to_dict(), "them": self.them.to_dict()},
            "repositories": self.repositories,
            "mcp_addresses": self.endpoints.to_dict(),
            "machine": statement(self.hardware, self.provenance),
            "llm_model": self.llm_model,
            "token_ceiling": self.token_ceiling,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.content(), "signature": self.signature}

    @property
    def filename(self) -> str:
        return declaration_filename(self.game_id)

    def concluded(self, ended_at: str, key: str | None) -> "MatchDeclaration":
        """A copy with the end time filled in, re-signed.

        Returns a new declaration rather than mutating this one. The pre-game
        document and the concluded one are different statements signed at
        different moments, and keeping both means the end time cannot be
        mistaken for something that was fixed before play.
        """
        if not ended_at:
            raise DeclarationError("concluded() needs an end time")
        return declare_match(replace(self, ended_at=ended_at, signature=""), key)

    def write(self, directory: Path) -> Path:
        """Write ``declaration_<game_id>.json``, sorted, with a trailing newline."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.filename
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return path


def declare_match(declaration: MatchDeclaration, key: str | None) -> MatchDeclaration:
    """Sign a declaration with the Step-0 key, or mark it unsigned.

    Uses :func:`~.step_zero.sign`, so there is one signing rule in the project
    rather than two that agree until they do not. A missing key produces
    ``"unsigned"`` — explicitly, because an empty signature is a value that
    *verifies* and would claim an authenticity nobody granted.
    """
    return replace(declaration, signature=sign(declaration.content(), key))


def build(
    *,
    game_id: str,
    game_uid: str,
    role: str,
    us: Team,
    them: Team,
    endpoints: Endpoints,
    hardware: Hardware,
    provenance: Provenance,
    llm_model: str,
    token_ceiling: int,
    started_at: str,
    key: str | None = None,
) -> MatchDeclaration:
    """Assemble and sign a declaration in one call."""
    return declare_match(
        MatchDeclaration(
            game_id=game_id,
            game_uid=game_uid,
            role=role,
            us=us,
            them=them,
            endpoints=endpoints,
            hardware=hardware,
            provenance=provenance,
            llm_model=llm_model,
            token_ceiling=token_ceiling,
            started_at=started_at,
        ),
        key,
    )
