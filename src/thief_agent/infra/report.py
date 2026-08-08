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
from dataclasses import dataclass, field
from email.message import EmailMessage

from .report_document import SCHEMA_VERSION, Report
from .report_parts import ReportError, Repositories, SubGameResult

__all__ = [
    "CONTENT_TYPE",
    "LECTURER",
    "SCHEMA_VERSION",
    "Message",
    "Report",
    "ReportError",
    "Repositories",
    "SubGameResult",
]

LECTURER = "rmisegal+uoh26finalgame@gmail.com"
"""FR-7.17: the mandatory destination, hard-coded and not configurable.

Deliberately not a parameter and not read from config. A configurable
destination is one typo away from a report that was sent, looks sent, and never
arrived — and the failure is indistinguishable from not reporting, which scores
zero for the side that did it.
"""

CONTENT_TYPE = ("application", "json")


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
