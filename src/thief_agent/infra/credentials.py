"""Reading ``credentials.json``, and refusing the wrong kind of client.

The file the Google Cloud console hands you identifies this application to
Google. It is not the thing that authorises sending — that is ``token.json``,
which step 5 produces — but it is the thing without which no authorisation flow
can start, and it is a secret in its own right: paired with a leaked token it
lets somebody continue impersonating this application indefinitely.

**The one check that earns this module is the client type.** The console offers
several, they all download as ``credentials.json``, and they all look
plausible. A **Desktop** client wraps its fields in ``"installed"``; a **Web**
client wraps them in ``"web"``. Handed a Web client, ``InstalledAppFlow``
proceeds normally through the browser and then fails at the redirect with

    Error 400: redirect_uri_mismatch

which names a URI nobody configured, invites an hour of adding
``http://localhost`` to authorised redirect URIs in the console, and never once
mentions that the client is simply the wrong type. Naming it at load time costs
one branch.

Nothing here talks to Google, and nothing here reads a secret it does not need:
the client secret stays in the parsed dictionary and is never logged, never put
in an exception message, and never returned as part of the summary this module
hands back.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CREDENTIALS_FILE = "credentials.json"
"""What the console downloads, and what ``.gitignore`` has covered since stage 0."""

DESKTOP_KEY = "installed"
"""Where a Desktop client keeps its fields. A Web client uses ``"web"``."""

REQUIRED = ("client_id", "client_secret", "auth_uri", "token_uri")
"""Fields the installed-app flow needs. Absent means a truncated or edited file."""


class CredentialsError(ValueError):
    """Raised when the credentials file is missing, malformed or the wrong type."""


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """The parts of the client that are safe to look at, log or print.

    The client secret is deliberately **not** here. This object exists to be
    shown to a person diagnosing a setup, and the moment a secret is on a
    dataclass somebody will put the dataclass in a log line.
    """

    client_id: str
    project_id: str = ""

    @property
    def summary(self) -> str:
        """One line naming the project, for the wrong-project mistake in step 1."""
        where = self.project_id or "an unnamed project"
        return f"client {self.client_id.split('.')[0]}… of {where}"


def load(path: Path) -> tuple[ClientInfo, dict[str, Any]]:
    """Read and check a Desktop-application credentials file.

    Returns:
        The safe-to-display :class:`ClientInfo`, and the raw ``installed``
        section for whatever Google library will consume it. Returned as a pair
        so the caller can pass the secret onward without it having passed
        through anything that formats itself.

    Raises:
        CredentialsError: if the file is missing, is not JSON, is a Web client
            rather than a Desktop one, or is missing a field the flow needs.
    """
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CredentialsError(
            f"no {path.name} at {path}; download it from the Google Cloud console "
            "(APIs & Services → Credentials → Create credentials → OAuth client ID "
            "→ Desktop app) and place it here — see docs/GMAIL_SETUP.md step 4"
        ) from exc
    except OSError as exc:
        raise CredentialsError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CredentialsError(f"{path.name} is not JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise CredentialsError(f"{path.name} is not a credentials object")
    if DESKTOP_KEY not in body:
        raise CredentialsError(_wrong_type(path, body))

    section = body[DESKTOP_KEY]
    if not isinstance(section, dict):
        raise CredentialsError(f"{path.name} has a {DESKTOP_KEY!r} that is not an object")
    missing = [field for field in REQUIRED if not section.get(field)]
    if missing:
        raise CredentialsError(
            f"{path.name} is missing {missing}; re-download it rather than editing it by hand"
        )

    return ClientInfo(
        client_id=str(section["client_id"]),
        project_id=str(section.get("project_id", "")),
    ), section


def _wrong_type(path: Path, body: dict[str, Any]) -> str:
    """Say which client type this actually is, because that is the whole fix."""
    if "web" in body:
        return (
            f"{path.name} is a **Web application** client; this agent needs a "
            "**Desktop app** client. A Web client gets as far as the browser and then "
            "fails with redirect_uri_mismatch, which names a URI nobody configured. "
            "Create a new OAuth client ID of type 'Desktop app' — no amount of "
            "redirect-URI editing makes a Web client work here"
        )
    found = sorted(body)
    return (
        f"{path.name} has no {DESKTOP_KEY!r} section (it has {found}); that is not an "
        "OAuth client file — a service-account key looks similar and cannot send mail "
        "as a person"
    )
