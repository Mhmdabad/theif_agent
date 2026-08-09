"""What this peer would tell an opponent, and whether it is fit to be told.

The address we would advertise, the summary printed before anything binds, and
the refusal that stops ``play`` from announcing a loopback. They belong
together: each one exists because announcing the wrong address costs both teams
the match rather than only us.
"""

import argparse
from collections.abc import Callable
from typing import Any

from .cli_config import StartupError
from .cli_identity import ROLE
from .infra.inboxes import TOOL_NAMES
from .infra.mcp_client import ClientSettings
from .infra.mcp_server import SERVER_NAME, ServerSettings
from .infra.tunnel import NotPublicError, discover, read_ngrok_api

_DEFAULT: Any = object()
"""Stands in for "use the real ngrok probe", resolved at call time.

``reader = read_ngrok_api`` would bind the default **once, at import**, so
substituting the module attribute afterwards would change nothing — the exact
defect that made the authorize suite open a real browser and hang (#280). A
sentinel keeps the resolution where a test can reach it, and ``None`` stays
available as a meaningful value: *do not probe at all*.
"""


def where_we_are(
    environ: dict[str, str], reader: Callable[[], str | bytes] | None = _DEFAULT
) -> str:
    """The address to advertise, or a sentence explaining that there is none.

    ``reader`` is the ngrok probe, exposed so a test can be hermetic. Without
    it these checks pass or fail depending on whether the developer happens to
    have a tunnel running — which is a test that reports the machine rather
    than the code.

    A missing tunnel is not an error — localhost is explicitly permitted while
    developing, and refusing to start without one would make every local run
    conditional on ngrok. A *malformed* one is an error, because it means
    somebody set an address and got it wrong, which is worse than not setting it.
    """
    try:
        endpoint = discover(environ, read_ngrok_api if reader is _DEFAULT else reader)
    except NotPublicError as exc:
        raise StartupError(f"the address we would advertise is unusable: {exc}") from exc
    if endpoint is None:
        return "not publicly reachable — fine for local play, not for a league match"
    return endpoint.url


def describe(private: dict[str, Any], environ: dict[str, str]) -> list[str]:
    """Everything worth printing before a socket opens, in order of usefulness."""
    network = private.get("network", {})
    server = ServerSettings.from_config(network)
    client = ClientSettings.from_config(network, environ)
    return [
        f"{SERVER_NAME} ({ROLE})",
        f"  listening on   {server.host}:{server.port} ({server.transport})",
        f"  reachable at   {where_we_are(environ)}",
        f"  opponent at    {client.opponent_url}",
        f"  tools          {', '.join(sorted(TOOL_NAMES))}",
    ]


def require_playable(
    arguments: argparse.Namespace,
    environ: dict[str, str],
    reader: Callable[[], str | bytes] | None = _DEFAULT,
) -> None:
    """Refuse to open a match that cannot succeed, before anything is announced.

    ``serve`` is happy without a tunnel — local development is the normal case
    and refusing would make every test run conditional on ngrok. ``play`` is
    not: it *announces our address to an opponent*, and announcing nothing (or
    a loopback) means every call they make times out, the deadline tracker
    turns that into a technical loss, and a technical loss scores zero for
    **both** sides.

    Checked here rather than in the handshake because the handshake's own
    complaint is ``'' must use one of ['https', 'http']`` — true, and no use at
    all to somebody who has simply not started a tunnel.
    """
    if not arguments.game_id:
        raise StartupError(
            "play needs --game-id, agreed with the opponent before either side "
            "starts; both sides' files are named from it and must match"
        )
    if getattr(arguments, "rehearse", False):
        return
    probe = read_ngrok_api if reader is _DEFAULT else reader
    if discover(environ, probe) is None:
        raise StartupError(
            "no public address to announce. Start a tunnel and export PUBLIC_URL, "
            "because announcing a loopback address to another team means every call "
            "they make times out — and a technical loss scores zero for both sides, "
            "not just for us. Use `check` to confirm before you try again"
        )
