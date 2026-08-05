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

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .gmail_auth import SCOPES, ScopeError, check_granted

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
    role: str = ""

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


ROLE_FIELD = "declared_role"
"""Which agent authorized. Ours, not Google's — see the module docstring."""


def read(path: Path, client_id: str, package: str = "thief_agent", role: str = "") -> StoredToken:
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

    declared = str(body.get(ROLE_FIELD, ""))
    if role and declared and declared != role:
        raise TokenError(
            f"{path.name} was authorized by the {declared} agent, not the {role} agent. "
            "Both agents share one OAuth client, so the client_id matches and proves "
            f"nothing here — this is a copied token. {hint}"
        )

    return StoredToken(
        client_id=stored,
        refresh_token=refresh,
        scopes=scopes,
        expiry=_expiry(body.get("expiry")),
        role=declared,
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


Exchange = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Takes the refresh token and the client section; returns the refreshed body."""


def google_refresh(refresh_token: str, client: dict[str, Any]) -> dict[str, Any]:
    """Exchange a refresh token for a fresh access token. The only network call.

    Imported inside the function so the rest of the mail path does not depend
    on the Google library being installed or importable.
    """
    from google.auth.transport.requests import Request  # noqa: PLC0415
    from google.oauth2.credentials import Credentials  # noqa: PLC0415

    # The Google library's own functions are untyped, so strict mode objects to
    # calling them. Ignored here, on three lines, rather than relaxing the rule
    # for a module that also holds the decisions worth type-checking.
    credentials = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=refresh_token,
        token_uri=client["token_uri"],
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=list(SCOPES),
    )
    credentials.refresh(Request())  # type: ignore[no-untyped-call]
    parsed = json.loads(credentials.to_json())  # type: ignore[no-untyped-call]
    return dict(parsed)


def refresh(
    path: Path,
    stored: StoredToken,
    client: dict[str, Any],
    exchange: Exchange | None = None,
) -> StoredToken:
    """Mint a fresh access token from the refresh token, and write it back.

    This is what makes the agent able to report unattended: the access token
    lasts an hour, the refresh token replaces it silently, and the file on disk
    is updated so the next process starts from the new one.

    The result is judged before it is written — same scope rules, same refresh
    token requirement. A refresh that came back over-scoped, or without a
    refresh token to use next time, is not an improvement on what we had, and
    writing it would replace a good credential with a worse one.

    Raises:
        TokenError: if the exchange returns something unusable. Nothing is
            written in that case, so the existing token survives a bad refresh.
    """
    body = (exchange or google_refresh)(stored.refresh_token, client)
    if not isinstance(body, dict):
        raise TokenError(f"the refresh returned {type(body).__name__}, not a credential")

    body.setdefault(ROLE_FIELD, stored.role)
    body.setdefault("refresh_token", stored.refresh_token)
    body.setdefault("client_id", stored.client_id)

    try:
        check_granted(body.get("scopes", body.get("scope")))
    except ScopeError as exc:
        raise TokenError(f"the refreshed credential is not one we may hold: {exc}") from exc
    if not body.get("refresh_token"):
        raise TokenError(
            "the refresh returned no refresh token, so the next one would have nothing "
            "to use; keeping the existing credential rather than replacing it with a "
            "worse one"
        )

    save(path, body)
    return read(path, stored.client_id, role=stored.role)


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
