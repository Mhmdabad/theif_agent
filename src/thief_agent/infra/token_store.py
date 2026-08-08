"""``token.json``: reading it, judging it, and writing it back after a refresh.

Step 5 of the setup produces this file. It holds a short-lived **access token**
and a long-lived **refresh token**, and it is the reason the agent can report
without a human present — the access token expires in an hour, the refresh
token mints a new one silently.

**The network call is a seam, not the module.** :func:`refresh` takes an
``exchange`` and calls it; :func:`google_refresh` is the real one and is the
only code here that imports a Google library. Everything with consequences —
whether a stored credential may be used at all, what a refreshed one must still
satisfy, what gets written back — is decided here and testable against every
awkward case without a network, a browser or a real account.

That split is also why :func:`refresh` resolves its default *inside the
function* rather than in the signature. A default argument binds once at import,
and the same mistake in :mod:`.authorize` produced a test suite that opened a
real browser and hung forever with no output.

Three refusals, and each exists because the failure it prevents is silent:

* **Over-scoped** — delegated to :func:`~.gmail_auth.check_granted`. A token
  granting more than we asked for is a token we do not want on disk.
* **No refresh token** — usable for an hour and then dead, at whatever moment
  that hour ends. Google omits it when the client has been authorised before,
  so this arrives exactly when somebody re-runs the flow to fix something else.
* **Wrong client** — a token minted for a different ``client_id`` may work and
  is not ours.
* **Wrong role** — the check that actually catches a cop/thief swap. The two
  agents share one OAuth client (one Google Cloud project, one downloaded
  ``credentials.json``), so a token copied between them has an entirely valid
  ``client_id`` and the previous check waves it through. The role is therefore
  written into the file at authorization time and compared on load.

The seven-day expiry that comes with an app in Testing (see
``docs/GMAIL_SETUP.md`` step 2) is not something code can prevent. What it can
do is fail with those words in the message, so the person reading it goes and
re-runs the flow instead of debugging the mail path.
"""

from .token_store_file import (
    REAUTHORIZE,
    TOKEN_FILE,
    TOKEN_PATH_ENV,
    TokenError,
    save,
    token_path,
)
from .token_store_read import read
from .token_store_record import ROLE_FIELD, StoredToken
from .token_store_refresh import Exchange, google_refresh, refresh

__all__ = [
    "REAUTHORIZE",
    "ROLE_FIELD",
    "TOKEN_FILE",
    "TOKEN_PATH_ENV",
    "Exchange",
    "StoredToken",
    "TokenError",
    "google_refresh",
    "read",
    "refresh",
    "save",
    "token_path",
]
