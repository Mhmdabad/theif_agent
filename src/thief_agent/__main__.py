"""``python -m thief_agent`` — start this peer and keep it answering.

The entry point the project has never had. It does the smallest honest amount:
read the private config, build the server, say where we are, and serve until
something stops it.

**Starting the server is the whole job of this command.** Playing a match needs
an opponent to have started theirs, a negotiated config, and an agreed game id —
none of which this process can decide alone, and all of which arrive through the
tools the server exposes. A command that tried to do both would have to guess at
the half it does not control, and the guess would be wrong exactly when a real
opponent behaved slightly differently from the one we imagined.

So: ``serve`` runs the peer. ``check`` answers "would this work?" without
binding anything, which is the question somebody actually has five minutes
before a match.

**It prints where it is reachable, and says plainly when that is nowhere.**
Advertising a loopback address to another team is not a small mistake — every
call times out, the deadline tracker turns that into a technical loss, and a
technical loss scores zero for *both* sides. The check runs before the socket
opens, so the failure is a line on our own terminal rather than a mystery in
somebody else's match.
"""

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .infra.inboxes import TOOL_NAMES, PeerInboxes
from .infra.mcp_client import ClientSettings
from .infra.mcp_server import SERVER_NAME, ServerSettings, build, serve
from .infra.tunnel import NotPublicError, discover

PACKAGE = "thief_agent"
ROLE = "thief"
CONFIG = Path("config/thief/game.toml")


class StartupError(RuntimeError):
    """Raised when this peer cannot honestly start."""


def load_private(path: Path) -> dict[str, Any]:
    """Read the private per-peer TOML, or say which file is missing."""
    try:
        body: dict[str, Any] = tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise StartupError(
            f"no private config at {path}; it is committed to this repository, so a "
            "missing one means the command is being run from somewhere other than the "
            "repository root"
        ) from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StartupError(f"cannot read {path}: {exc}") from exc
    return body


def where_we_are(environ: dict[str, str]) -> str:
    """The address to advertise, or a sentence explaining that there is none.

    A missing tunnel is not an error — localhost is explicitly permitted while
    developing, and refusing to start without one would make every local run
    conditional on ngrok. A *malformed* one is an error, because it means
    somebody set an address and got it wrong, which is worse than not setting it.
    """
    try:
        endpoint = discover(environ)
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


def main(argv: Sequence[str] | None = None, environ: dict[str, str] | None = None) -> int:
    """Run the command. Returns an exit code rather than raising."""
    parser = argparse.ArgumentParser(prog=f"python -m {PACKAGE}", description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=("serve", "check"),
        help="serve: run the peer. check: report the configuration and exit.",
    )
    parser.add_argument("--config", type=Path, default=CONFIG, help="private per-peer TOML")
    arguments = parser.parse_args(argv)

    import os  # noqa: PLC0415 - read once, here, so tests can supply their own

    source = dict(os.environ) if environ is None else environ

    try:
        private = load_private(arguments.config)
        for line in describe(private, source):
            print(line)
        if arguments.command == "check":
            return 0
        settings = ServerSettings.from_config(private.get("network", {}))
    except (StartupError, ValueError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 1

    print("serving — stop with Ctrl-C", flush=True)
    serve(build(PeerInboxes()), settings)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
