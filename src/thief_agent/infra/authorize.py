"""Step 5, run once by a human: the browser flow that produces the token file.

    python -m thief_agent.infra.authorize

Opens a browser, waits for consent, and writes a credential this agent can use
without a human present from then on. Every error message elsewhere in the mail
path ends by naming this command, because every one of those failures is fixed
the same way — by running it again.

**The browser flow is a seam, not the module.** :func:`authorize` takes a
``runner`` and calls it; :func:`google_flow` is the real one and is the only
code here that imports a Google library. That split is what makes the rest of
this testable: the ordering (check the client file *before* opening a browser),
the scope check on what came back, the file permissions, and the wording of
every failure can all be exercised without a network or an account.

Checking the credentials file first matters more than it looks. A Web client
sends the user through consent and *then* fails at the redirect (see
:mod:`.credentials`), so validating afterwards would mean the person has already
approved something before being told the file was the wrong type.
"""

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .credentials import CREDENTIALS_FILE, CredentialsError, load
from .gmail_auth import SCOPES, ScopeError, check_granted
from .token_store import ROLE_FIELD, TokenError, save, token_path

PACKAGE = "thief_agent"
ROLE = "thief"
"""Stamped into the token, so a copy to the other agent is detectable.

Both agents share one OAuth client, so ``client_id`` proves nothing about
*which* agent authorized. This is the field that does.
"""

Runner = Callable[[dict[str, Any], Sequence[str]], dict[str, Any]]
"""Takes the client config and the scopes, returns the credential as a dict."""


def google_flow(client: dict[str, Any], scopes: Sequence[str]) -> dict[str, Any]:
    """Run the real browser flow. The only place a Google library is imported.

    Imported inside the function so the rest of the mail path — and the whole
    test suite — does not depend on the library being installed or on it being
    importable in an environment with no display.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415

    flow = InstalledAppFlow.from_client_config({"installed": client}, list(scopes))
    credentials = flow.run_local_server(port=0)
    parsed = json.loads(credentials.to_json())
    return dict(parsed)


def authorize(
    credentials_path: Path,
    destination: Path,
    runner: Runner | None = None,
    package: str = PACKAGE,
) -> Path:
    """Check the client file, run the flow, check what came back, write it down.

    ``runner`` defaults to :func:`google_flow` but is resolved **here** rather
    than in the signature. A default argument is bound once, when the module is
    imported, so ``runner: Runner = google_flow`` would capture the original
    function and quietly ignore every later substitution of it — including the
    one a test makes to avoid opening a browser. That is not a testing
    inconvenience: the failure mode is a process that launches a real consent
    flow and then blocks forever on a local callback server, in a suite that is
    supposed to touch no network at all.

    Returns:
        The path the credential was written to.

    The role is stamped into the written credential. Both agents share one
    OAuth client — one project, one downloaded ``credentials.json`` — so the
    ``client_id`` in a token says nothing about which agent obtained it, and a
    file copied from the other one would otherwise pass every check.

    Raises:
        CredentialsError: if the client file is missing or the wrong type.
            Raised **before** the browser opens, so nobody approves a consent
            screen for a client that was never going to work.
        TokenError: if the flow returned something unusable — no refresh token,
            or a scope wider than we asked for. Refusing after the fact is not
            too late: the file is what matters, and it is not written.
    """
    client_info, client = load(credentials_path)
    print(f"authorizing {client_info.summary}", file=sys.stderr)

    body = (runner or google_flow)(client, SCOPES)
    if not isinstance(body, dict):
        raise TokenError(f"the authorization flow returned {type(body).__name__}, not a credential")

    try:
        check_granted(body.get("scopes", body.get("scope")))
    except ScopeError as exc:
        raise TokenError(f"the flow granted more than this agent asked for: {exc}") from exc

    if not body.get("refresh_token"):
        raise TokenError(
            "the flow returned no refresh token, so the agent could not report "
            "unattended. Google omits it when this client has been authorized "
            "before — revoke at https://myaccount.google.com/permissions and run "
            "this again"
        )

    body[ROLE_FIELD] = ROLE
    written = save(destination, body)
    print(f"wrote {written} (mode 600). Re-run within seven days if the app is in Testing.")
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point. Returns a process exit code rather than raising."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    credentials_path = Path(arguments[0]) if arguments else Path(CREDENTIALS_FILE)
    try:
        authorize(credentials_path, token_path(PACKAGE))
    except (CredentialsError, TokenError) as exc:
        print(f"authorization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
