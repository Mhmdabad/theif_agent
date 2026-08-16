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

**The body and attachment are the same report bytes.** This satisfies both the
book's body example and its attachment rule without maintaining two truths.

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
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage

from .report_document import SCHEMA_VERSION, Report
from .report_parts import ReportError, Repositories, SubGameResult

__all__ = [
    "CONTENT_TYPE",
    "RECIPIENT_ENV",
    "SCHEMA_VERSION",
    "Message",
    "Report",
    "ReportError",
    "Repositories",
    "SubGameResult",
    "recipient",
]

RECIPIENT_ENV = "REPORT_RECIPIENT"
"""The only place the destination comes from. Set it in ``.env``.

FR-7.17 names the address Appendix ו mandates, and the address itself lives in
``.env`` rather than in this file — deliberately, so that changing where reports
go is a configuration act rather than a code change, and so no copy of it can go
stale against another.
"""


def recipient(environ: Mapping[str, str] | None = None) -> str:
    """Where a report is addressed. **Refuses rather than guessing.**

    There is no default and no fallback: an unset, empty or blank variable is an
    error, not a hint. The alternative — quietly substituting an address nobody
    asked for — is worse than stopping, because the one thing a caller cannot
    check afterwards is whether the report went where they meant it to. A
    refusal is visible on the terminal the moment it happens; a silent
    substitution is visible only in somebody else's inbox, or in nobody's.

    Rule 35 charges an unreported match to *both* teams, so this failing is
    expensive — which is exactly why it fails loudly, at the point where the
    person who can fix it is still watching, rather than after a match has been
    played and the only remaining evidence is that no mail arrived.

    Raises:
        ReportError: naming the variable and the file it belongs in.
    """
    source = os.environ if environ is None else environ
    chosen = (source.get(RECIPIENT_ENV) or "").strip()
    if not chosen:
        raise ReportError(
            f"{RECIPIENT_ENV} is not set, so the report has no destination. "
            f"Put the address from Appendix ו in .env as {RECIPIENT_ENV}=... "
            "(see .env.example); nothing is sent until it is there."
        )
    return chosen


CONTENT_TYPE = ("application", "json")


@dataclass
class Message:
    """The mail, with the report as its only payload of record."""

    report: Report
    sender: str
    to: str = field(default_factory=recipient)

    _built: EmailMessage | None = field(default=None, init=False, repr=False)

    def subject(self) -> str:
        return f"[uoh26] {self.report.role} result — {self.report.game_id}"

    def body(self) -> str:
        """The exact canonical report text, also used by the attachment."""
        return self.report.to_json()

    def build(self) -> EmailMessage:
        """Assemble the MIME message with the report attached as JSON."""
        mail = EmailMessage()
        mail["To"] = self.to
        mail["From"] = self.sender
        mail["Subject"] = self.subject()
        encoded = base64.b64encode(self.body().encode("utf-8")).decode("ascii")
        mail.set_payload(encoded)
        mail["Content-Type"] = 'text/plain; charset="utf-8"'
        mail["Content-Transfer-Encoding"] = "base64"
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
