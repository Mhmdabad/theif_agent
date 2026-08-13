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
from .report_reference import SCHEMA_VERSION as REFERENCE_SCHEMA
from .report_reference import result_document

SCHEMA_VERSION = REFERENCE_SCHEMA
"""One definition, re-exported. Two constants for one field in one document is
how a writer and its own test come to disagree about what was written."""


@dataclass(frozen=True, slots=True)
class Report:
    """A finished match, ready to be serialised and attached."""

    game_id: str
    role: str
    team: str
    opponent_team: str
    sub_games: tuple[SubGameResult, ...]
    total_tokens: int
    agreed: bool
    repositories: Repositories | None = None
    """The four links. Held for callers that have them, but **not serialised**:
    the reference's result omits static team metadata and refers back to the
    declaration by ``game_id``, and this document matches it field for field."""

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
        """The whole report, in the shape the lecturer's tooling reads.

        Delegated to :mod:`.report_reference`, which follows the reference
        implementation's sample field for field. The rulebook does not specify a
        layout, so the grader's own format is the only specification there is.
        """
        return result_document(self)

    @property
    def groups_named(self) -> tuple[str, str]:
        """The two groups this result is about, in the order it lists them."""
        return (self.team, self.opponent_team)

    def to_json(self) -> str:
        """Sorted keys and a trailing newline, so two peers produce identical bytes.

        ``ensure_ascii=False`` for the same reason the digests use it: the file
        should read as what it is. The consensus signature key is Hebrew, and
        escaping rendered it ``\\u05d7\\u05ea…`` in every emailed report --
        verifiable, since a parser decodes it back, but unreadable to the person
        the attachment is for.
        """
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

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
