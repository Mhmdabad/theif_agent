"""The declaration record: what it holds, what it signs, and how it is written.

Split out of :mod:`.declaration`, whose module docstring explains why the
signature covers the content and never itself, and why ``ended_at`` is the one
field deliberately left open when the document is first signed.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..shared.naming import declaration_filename
from .declaration_parties import DeclarationError, Endpoints, Team
from .declaration_reference import declaration_document
from .step_zero import Hardware, Provenance, sign, statement


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
    num_sub_games: int = 6
    """Sub-games in this series. Appendix F fixes six and forbids lowering it."""

    games_already_played: int = 0
    """Appendix E rule 37: league games behind us when this one opened.

    Inside :meth:`content`, so the signature covers it — rule 38 makes a false
    count a breach, and a number nobody signed is one that can be revised after
    the fact. Counted from :class:`~.match_ledger.MatchLedger`, which sits beside
    the artefacts a reader can check it against.
    """

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
        if self.games_already_played < 0:
            raise DeclarationError(
                f"games_already_played cannot be negative, got {self.games_already_played}; "
                "Appendix E rule 37 wants the exact number of games behind us"
            )
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
            "games_already_played": self.games_already_played,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }

    def to_dict(self) -> dict[str, Any]:
        """The document as written and emailed, in the reference's shape.

        :meth:`content` stays as it is: it is what the signature covers, and
        changing the signed bytes to match a presentation format would mean the
        signature attested to the layout rather than to the facts.
        """
        return declaration_document(self)

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
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        return path


def declare_match(declaration: MatchDeclaration, key: str | None) -> MatchDeclaration:
    """Sign a declaration with the Step-0 key, or mark it unsigned.

    Uses :func:`~.step_zero.sign`, so there is one signing rule in the project
    rather than two that agree until they do not. A missing key produces
    ``"unsigned"`` — explicitly, because an empty signature is a value that
    *verifies* and would claim an authenticity nobody granted.
    """
    return replace(declaration, signature=sign(declaration.content(), key))
