"""The report itself: the one structure a parser will read, and its file.

Serialisation lives here, next to the fields it serialises, so the committed
``result_<game_id>.json`` and the attached bytes come from one method. Split
out of :mod:`.report`, which re-exports everything defined here.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..shared.naming import result_filename
from .report_parts import ReportError, Repositories, SubGameResult

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class Report:
    """A finished match, ready to be serialised and attached."""

    game_id: str
    role: str
    team: str
    opponent_team: str
    repositories: Repositories
    sub_games: tuple[SubGameResult, ...]
    total_tokens: int
    agreed: bool
    game_uid: str = ""
    started_at: str = ""
    ended_at: str = ""
    starting_role: str = ""
    """The role played in sub-game 1; the alternation schedule follows from it."""

    series_result: dict[str, Any] | None = None
    """The group-keyed standing — the book scores a group pair, not a role."""

    mcp_addresses: dict[str, Any] | None = None
    """Both peers' FastMCP endpoints, which §9.3.3 asks the report to carry."""

    machine: dict[str, Any] | None = None
    """The hardware and provenance statement, signed under :attr:`signature`."""

    signature: str = ""
    """HMAC-SHA256 over the machine statement, or ``unsigned``.

    Carried rather than recomputed: the report attests to the declaration the
    match was actually played under, and a signature produced here would attest
    only to this file.
    """

    result_claim_sha256: str = ""
    """The digest both sides agreed on before either reported.

    §9.3.3 wants mutual agreement *backed by SHA-256*; ``agreed`` alone is this
    side's word for it. With the digest present a marker can check that two
    independently-sent reports describe one match rather than two claims.
    """

    def __post_init__(self) -> None:
        if not self.sub_games:
            raise ReportError("a report with no sub-games describes no match")
        numbers = [result.sub_game for result in self.sub_games]
        if len(set(numbers)) != len(numbers):
            raise ReportError(f"sub-game numbers repeat: {numbers}")
        if self.total_tokens < 0:
            raise ReportError(f"total_tokens cannot be negative, got {self.total_tokens}")

    @property
    def cop_total(self) -> int:
        return sum(result.cop_score for result in self.sub_games)

    @property
    def thief_total(self) -> int:
        return sum(result.thief_score for result in self.sub_games)

    def to_dict(self) -> dict[str, Any]:
        """The whole report, as the one structure a parser will read."""
        return {
            "schema_version": SCHEMA_VERSION,
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "reported_by": {"role": self.role, "team": self.team},
            "opponent_team": self.opponent_team,
            "repositories": self.repositories.to_dict(),
            "sub_games": [result.to_dict() for result in self.sub_games],
            "totals": {
                "cop": self.cop_total,
                "thief": self.thief_total,
                "sub_games_played": len(self.sub_games),
                "total_tokens": self.total_tokens,
            },
            "result_agreed_with_opponent": self.agreed,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "starting_role": self.starting_role or self.role,
            "series_result": self.series_result,
            "mcp_addresses": self.mcp_addresses,
            "machine": self.machine,
            "signature": self.signature,
            "result_claim_sha256": self.result_claim_sha256,
        }

    def to_json(self) -> str:
        """Sorted keys and a trailing newline, so two peers produce identical bytes."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @property
    def filename(self) -> str:
        return result_filename(self.game_id)

    def write(self, directory: Path) -> Path:
        """Write ``result_<game_id>.json`` — the same bytes that get attached.

        The file and the attachment come from one :meth:`to_json`, so the copy
        committed to the repository and the copy the lecturer receives cannot
        drift. Writing the report twice, from two serialisations, is how the
        evidence in the repository ends up disagreeing with the evidence in the
        mailbox — and the two are meant to be the same document.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.filename
        path.write_text(self.to_json())
        return path
