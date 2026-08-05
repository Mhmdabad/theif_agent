"""``token.json``: reading it, judging it, and writing it back after a refresh.

Step 5 of the setup produces this file. It holds a short-lived **access token**
and a long-lived **refresh token**, and it is the reason the agent can report
without a human present — the access token expires in an hour, the refresh
token mints a new one silently.

**This module does no network I/O and imports no Google library.** Refreshing is
one HTTP call that the vendor's client already makes correctly; what it does not
do is decide whether a stored credential should be used at all, and that
decision is the part with consequences. Keeping it separate means the rules can
be tested against every awkward case — expired, over-scoped, no refresh token,
written by a different client — without a network, a browser or a real account.

Three refusals, and each exists because the failure it prevents is silent:

* **Over-scoped** — delegated to :func:`~.gmail_auth.check_granted`. A token
  granting more than we asked for is a token we do not want on disk.
* **No refresh token** — usable for an hour and then dead, at whatever moment
  that hour ends. Google omits it when the client has been authorised before,
  so this arrives exactly when somebody re-runs the flow to fix something else.
* **Wrong client** — a token minted for a different ``client_id`` may work and
  is not ours. Usually it means a file was copied between the two agents.

The seven-day expiry that comes with an app in Testing (see
``docs/GMAIL_SETUP.md`` step 2) is not something code can prevent. What it can
do is fail with those words in the message, so the person reading it goes and
re-runs the flow instead of debugging the mail path.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .gmail_auth import ScopeError, check_granted

TOKEN_FILE = "token.json"
"""Default name. Overridden per agent — see :func:`token_path`."""

TOKEN_PATH_ENV = "GMAIL_TOKEN_PATH"
"""Explicit override, so the two agents never share a token by accident."""

REAUTHORIZE = (
    "run `python -m {package}.infra.authorize` to authorize again; note that an app "
    "in Testing issues a refresh token that expires after seven days"
)


class TokenError(ValueError):
    """Raised when a stored credential exists but must not be used."""


def token_path(package: str, environ: "dict[str, str] | None" = None) -> Path:
    """Where this agent's token lives.

    Named per package rather than ``token.json`` in both repositories. The two
    agents authorise separately and their tokens are not interchangeable, and a
    file with the same name in two sibling directories is an invitation to copy
    one across to skip the flow — which produces the ``wrong client`` refusal
    below at the least convenient moment.
    """
    chosen = (environ if environ is not None else dict(os.environ)).get(TOKEN_PATH_ENV)
    return Path(chosen) if chosen else Path(f"token_{package.split('_')[0]}.json")


@dataclass(frozen=True, slots=True)
class StoredToken:
    """A credential read from disk, already checked.

    Holds the refresh token because refreshing needs it, and defines no
    ``__str__``: the default dataclass ``repr`` would print it, so callers must
    never log this object. :attr:`summary` is what is safe to show.
    """

    client_id: str
    refresh_token: str
    scopes: tuple[str, ...]
    expiry: datetime | None = None

    @property
    def expired(self) -> bool:
        """Whether the *access* token has run out. Not a problem — just a refresh."""
        return self.expiry is not None and self.expiry <= datetime.now(UTC)

    @property
    def summary(self) -> str:
        state = "expired" if self.expired else "current"
        return (
            f"token for client {self.client_id.split('.')[0]}… ({state}, {len(self.scopes)} scope)"
        )


def read(path: Path, client_id: str, package: str = "thief_agent") -> StoredToken:
    """Load a stored credential, refusing any that should not be used.

    Args:
        path: the token file, from :func:`token_path`.
        client_id: the ``client_id`` from ``credentials.json``. A token minted
            for another client is refused even though it might work.
        package: names the module to re-run in the error messages.

    Raises:
        TokenError: on a missing, malformed, over-scoped, refresh-less or
            foreign-client token. Every message ends by naming the command that
            fixes it, because every one of these is fixed the same way.
    """
    hint = REAUTHORIZE.format(package=package)
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise TokenError(f"no {path.name}; {hint}") from exc
    except OSError as exc:
        raise TokenError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TokenError(f"{path.name} is not JSON: {exc}; delete it and {hint}") from exc

    if not isinstance(body, dict):
        raise TokenError(f"{path.name} is not a token object; delete it and {hint}")

    try:
        scopes = check_granted(body.get("scopes", body.get("scope")))
    except ScopeError as exc:
        raise TokenError(f"{path.name}: {exc}. Then {hint}") from exc

    refresh = body.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise TokenError(
            f"{path.name} has no refresh token, so it stops working within the hour "
            "and does so mid-match. Google omits it when the client has been "
            f"authorised before — revoke at https://myaccount.google.com/permissions, "
            f"then {hint}"
        )

    stored = str(body.get("client_id", ""))
    if stored != client_id:
        raise TokenError(
            f"{path.name} was minted for a different client ({stored.split('.')[0]}… "
            f"rather than {client_id.split('.')[0]}…). A token copied between the two "
            f"agents is the usual cause; each authorises for itself. {hint}"
        )

    return StoredToken(
        client_id=stored,
        refresh_token=refresh,
        scopes=scopes,
        expiry=_expiry(body.get("expiry")),
    )


def _expiry(value: object) -> datetime | None:
    """Parse an expiry, treating an unreadable one as unknown rather than fatal.

    An expiry we cannot read is not a reason to refuse a credential: the worst
    case is one wasted refresh, while refusing costs a report. The access token
    expiring is the ordinary case, not the error case.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def save(path: Path, body: dict[str, Any]) -> Path:
    """Write a credential back after a refresh, readable only by this user.

    The permissions are set **before** anything is written. Creating the file
    world-readable and narrowing it afterwards leaves a window in which the
    refresh token is readable by every account on the machine, and on a shared
    university machine that window is the whole exposure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as stream:
        json.dump(body, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.chmod(path, 0o600)
    return path
