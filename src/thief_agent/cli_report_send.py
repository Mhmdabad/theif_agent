"""Assembling the mail pipeline for one deliberate send.

Split from :mod:`.cli_report` so that reading a report needs neither a Google
library nor a credential on disk: the dry run imports nothing from here.

Everything below is composition. The gates, the bucket, the detector, the quota
ledger and the sender all exist and are tested; what had no home was the code
that builds one of each and hands them to :class:`~.infra.mailer.Mailer`. That
absence is why Appendix E rule 32's "report automatically" was a library nobody
could call.

**The three gates are built with their real parameters.** The bucket's limits
come from :mod:`.infra.token_bucket_core`, which reads them from Appendix F, and
the quota and lock files come from the same path helpers every other caller
uses. A send path that quietly used friendlier limits, or counted its daily
ceiling in a different file from the one the detector watches, would pass every
test here and be the wrong program.

Every path is derived from :data:`~.cli_identity.PACKAGE` rather than written
out, so this module is byte-identical in both repositories and each one still
keeps its own lock, its own ledger and its own token.
"""

import json
import time
from pathlib import Path
from typing import Any

from .cli_identity import PACKAGE
from .infra.credentials import CREDENTIALS_FILE, load
from .infra.dos_detector import Detector, lock_path
from .infra.gatekeeper import Gatekeeper
from .infra.mailer import Mailer, gmail_sender
from .infra.quota import Quota, quota_path
from .infra.report_document import Report
from .infra.token_bucket import Limiter, TokenBucket
from .infra.token_store import token_path

__all__ = ["deliver"]


def deliver(report: Report, sender_address: str, private: dict[str, Any]) -> dict[str, Any]:
    """Send one report through every gate the rulebook requires.

    The credential is assembled from two files that are both git-ignored: the
    client from ``credentials.json`` and the refresh token from the store
    :mod:`.infra.authorize` wrote. Neither is ever logged — what is printed is
    whatever the provider answers, which carries no secret.

    Raises:
        SendError: when a gate refused, when the retry budget is spent, or when
            the provider kept answering 429.
        CredentialsError, TokenError, OSError: when this machine has not been
            authorised. Each names the command that fixes it.
    """
    configured = str(private.get("email", {}).get("credentials", CREDENTIALS_FILE))
    _, client = load(Path(configured))
    stored = json.loads(token_path(PACKAGE).read_text())

    mailer = Mailer(
        gatekeeper=Gatekeeper(
            detector=Detector(path=lock_path(PACKAGE), now=time.monotonic),
            quota=Quota(path=quota_path(PACKAGE)),
            limiter=Limiter(bucket=TokenBucket()),
        ),
        sender=gmail_sender({**client, **stored}),
    )
    return mailer.send_report(report, sender_address)
