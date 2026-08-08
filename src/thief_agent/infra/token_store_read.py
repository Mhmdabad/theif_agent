"""Loading a stored credential, and refusing any that must not be used.

Split out of :mod:`.token_store`, which re-exports these names; see its
module docstring for why each refusal here exists.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from .gmail_auth import ScopeError, check_granted
from .token_store_file import REAUTHORIZE, TokenError
from .token_store_record import ROLE_FIELD, StoredToken


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
