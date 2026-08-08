"""Where the token file lives, and how it is written back.

Split out of :mod:`.token_store`, which re-exports these names; see its
module docstring for why each rule here exists.
"""

import json
import os
from pathlib import Path
from typing import Any

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
