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

So: ``serve`` runs the peer and answers. ``check`` answers "would this work?"
without binding anything, which is the question somebody actually has five
minutes before a match. ``play`` is the other half — it starts the server *and*
opens a match against an opponent who has already started theirs.

``play`` writes the four artefacts and stops. **It does not send anything.**
FR-7.16 requires both sides to agree the result before either reports, so the
report is written to disk with ``agreed`` false and mailing it is a separate,
later, human act.

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
        choices=("serve", "check", "play"),
        help=(
            "serve: run the peer and answer. check: report the configuration and exit. "
            "play: serve and open a match against an opponent who has already started."
        ),
    )
    parser.add_argument("--config", type=Path, default=CONFIG, help="private per-peer TOML")
    parser.add_argument("--game-id", default="", help="agreed with the opponent beforehand")
    parser.add_argument("--out", type=Path, default=Path("artefacts"), help="where to write")
    parser.add_argument("--sub-games", type=int, default=1)
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
        if arguments.command == "play":
            require_playable(arguments, source)
    except (StartupError, ValueError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 1

    inboxes = PeerInboxes()
    if arguments.command == "play":
        return play(arguments, private, settings, inboxes, source)

    print("serving — stop with Ctrl-C", flush=True)
    serve(build(inboxes), settings)
    return 0


def require_playable(arguments: argparse.Namespace, environ: dict[str, str]) -> None:
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
    if discover(environ) is None:
        raise StartupError(
            "no public address to announce. Start a tunnel and export PUBLIC_URL, "
            "because announcing a loopback address to another team means every call "
            "they make times out — and a technical loss scores zero for both sides, "
            "not just for us. Use `check` to confirm before you try again"
        )


def play(
    arguments: argparse.Namespace,
    private: dict[str, Any],
    settings: ServerSettings,
    inboxes: PeerInboxes,
    environ: dict[str, str],
) -> int:  # pragma: no cover - drives a live opponent
    """Serve, then open a match. Writes artefacts; sends nothing.

    Not covered by tests, and the reason is the same one that keeps
    ``run_live`` uncovered: the thing under test would be *another team*.
    Everything it composes — the handshake, the digest exchange, the ceremony,
    the audit, the artefact set — is covered against a real opponent in
    ``test_localhost_match``. This function is the part that cannot be.
    """
    import threading

    from .runtime.driver import open_match

    threading.Thread(target=serve, args=(build(inboxes), settings), daemon=True).start()
    print(f"serving on {settings.host}:{settings.port}", flush=True)
    try:
        written = open_match(
            inboxes=inboxes,
            private=private,
            environ=environ,
            game_id=arguments.game_id,
            sub_games=arguments.sub_games,
            directory=arguments.out,
        )
    except Exception as exc:  # noqa: BLE001 - a match failure is a message, not a traceback
        print(f"the match did not finish: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"  wrote {path}")
    print("\nNothing has been emailed. Agree the result with the opponent first,")
    print("then send it deliberately — FR-7.16.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
