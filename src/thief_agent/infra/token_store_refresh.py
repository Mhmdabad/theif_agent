"""The refresh: the network seam, and what a refreshed credential must satisfy.

Split out of :mod:`.token_store`, which re-exports these names; see its
module docstring for why the exchange is a parameter rather than a call.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .gmail_auth import SCOPES, ScopeError, check_granted
from .token_store_file import TokenError, save
from .token_store_read import read
from .token_store_record import ROLE_FIELD, StoredToken

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
