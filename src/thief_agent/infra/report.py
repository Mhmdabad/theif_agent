"""The report: structured JSON, sent as an attachment, never as prose.

FR-7.23 makes the format a scoring matter rather than a style one. A report the
lecturer's tooling cannot parse **is rejected**, and a rejected report loses the
round's league points even though the match was played correctly. Two teams can
play a clean game, agree the result, and score nothing because one of them wrote
a sentence where a field belonged.

So there is exactly one way to produce a report here, and **no free-text path
exists at all**. Not a discouraged one, not one behind a flag — the module has no
function that accepts a body of prose, and a test reads the source to keep it
that way. An escape hatch that exists gets used at 2am by somebody who is sure
this once is fine.

**The attachment is the report; the body is not.** A MIME body is for the human
who opens the mail, so it says what the attachment contains and stops. Anything
a parser needs lives in ``result_<game_id>.json``, because a summary in the body
is a second copy of the truth that will eventually disagree with the first.

**Both teams' four GitHub links, the per-sub-game commit hashes and the total
tokens are mandatory** (FR-7.28), so they are required at construction rather
than validated on the way out. A report that cannot be built wrong does not need
checking later, and the error arrives while somebody is still looking at the
code that caused it.

Nothing here sends anything. Building the message and putting it on the wire are
separate jobs, and this one has no network, no credentials and no side effects —
which is what lets the exact bytes of a real report be asserted in a test.
"""

import base64
import json
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from ..shared.naming import result_filename

LECTURER = "rmisegal+uoh26finalgame@gmail.com"
"""FR-7.17: the mandatory destination, hard-coded and not configurable.

Deliberately not a parameter and not read from config. A configurable
destination is one typo away from a report that was sent, looks sent, and never
arrived — and the failure is indistinguishable from not reporting, which scores
zero for the side that did it.
"""

CONTENT_TYPE = ("application", "json")
SCHEMA_VERSION = "1.0.0"


class ReportError(ValueError):
    """Raised when a report is missing something the rulebook requires."""


@dataclass(frozen=True, slots=True)
class SubGameResult:
    """One sub-game's outcome, with the commit it was played at."""

    sub_game: int
    cop_score: int
    thief_score: int
    commit_hash: str
    steps: int = 0
    technical_loss: bool = False

    def __post_init__(self) -> None:
        if self.sub_game < 1:
            raise ReportError(f"sub-games are numbered from 1, got {self.sub_game}")
        if not self.commit_hash:
            raise ReportError(
                f"sub-game {self.sub_game} has no commit hash; FR-7.28 requires one per "
                "sub-game, and without it nobody can say which code played the game"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub_game": self.sub_game,
            "cop_score": self.cop_score,
            "thief_score": self.thief_score,
            "commit_hash": self.commit_hash,
            "steps": self.steps,
            "technical_loss": self.technical_loss,
        }


@dataclass(frozen=True, slots=True)
class Repositories:
    """Four links, both teams, both roles. FR-7.28 requires all of them."""

    cop_repo: str
    thief_repo: str
    opponent_cop_repo: str
    opponent_thief_repo: str

    def __post_init__(self) -> None:
        missing = [name for name, value in self.to_dict().items() if not value]
        if missing:
            raise ReportError(
                f"FR-7.28 requires four repository links and {missing} are empty; a "
                "report that cannot be traced back to the code is not a result"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "cop_repo": self.cop_repo,
            "thief_repo": self.thief_repo,
            "opponent_cop_repo": self.opponent_cop_repo,
            "opponent_thief_repo": self.opponent_thief_repo,
        }


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


@dataclass
class Message:
    """The mail, with the report as its only payload of record."""

    report: Report
    sender: str
    to: str = LECTURER

    _built: EmailMessage | None = field(default=None, init=False, repr=False)

    def subject(self) -> str:
        return f"[uoh26] {self.report.role} result — {self.report.game_id}"

    def body(self) -> str:
        """What a person reads. Deliberately says nothing a parser would want.

        A summary here would be a second copy of the result, and two copies of
        one fact disagree eventually — usually after somebody edits the easier
        one to read.
        """
        return (
            f"Automated match report from the {self.report.role} agent.\n"
            f"The result is the attached {self.report.filename}; this text is not "
            "part of the report and is not machine-readable on purpose.\n"
        )

    def build(self) -> EmailMessage:
        """Assemble the MIME message with the report attached as JSON."""
        mail = EmailMessage()
        mail["To"] = self.to
        mail["From"] = self.sender
        mail["Subject"] = self.subject()
        mail.set_content(self.body())
        mail.add_attachment(
            self.report.to_json().encode("utf-8"),
            maintype=CONTENT_TYPE[0],
            subtype=CONTENT_TYPE[1],
            filename=self.report.filename,
        )
        self._built = mail
        return mail

    def raw(self) -> dict[str, str]:
        """The Gmail API's ``users.messages.send`` body: url-safe base64 MIME."""
        mail = self._built or self.build()
        return {"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode("ascii")}
