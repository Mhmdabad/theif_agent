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

``play`` writes the four artefacts and then **reports itself**. §9.3 leaves no
room for human intervention at the end of a legal match and requires *both*
sides to send separately; rule 35 scores a report that never arrives as zero for
both teams. A send somebody has to remember is a send that gets forgotten once,
by whichever team is more tired, and takes the other team down with it.

The result is still agreed on the wire before anything is mailed, so what goes
out carries whether the opponent confirmed the score — and a score they never
confirmed is refused rather than sent. A rehearsal mails nothing at all.

**It prints where it is reachable, and says plainly when that is nowhere.**
Advertising a loopback address to another team is not a small mistake — every
call times out, the deadline tracker turns that into a technical loss, and a
technical loss scores zero for *both* sides. The check runs before the socket
opens, so the failure is a line on our own terminal rather than a mystery in
somebody else's match.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from .cli_announce import describe, require_playable, where_we_are
from .cli_arguments import parse
from .cli_config import StartupError, load_private, resolve_series_length
from .cli_failures import MAX_DEPTH, describe_failure, safely_describe
from .cli_identity import CONFIG, PACKAGE, ROLE
from .cli_play import play
from .cli_report import report
from .infra.inboxes import TOOL_NAMES, PeerInboxes
from .infra.mcp_client import ClientSettings
from .infra.mcp_server import SERVER_NAME, ServerSettings, build, serve
from .infra.tunnel import NotPublicError, discover, read_ngrok_api
from .shared.config import SHARED_CONFIG, series_length
from .shared.config import load as load_shared

__all__ = [
    "CONFIG",
    "MAX_DEPTH",
    "PACKAGE",
    "ROLE",
    "SERVER_NAME",
    "SHARED_CONFIG",
    "TOOL_NAMES",
    "ClientSettings",
    "NotPublicError",
    "PeerInboxes",
    "ServerSettings",
    "StartupError",
    "build",
    "describe",
    "describe_failure",
    "discover",
    "load_private",
    "load_shared",
    "parse",
    "main",
    "play",
    "read_ngrok_api",
    "report",
    "require_playable",
    "resolve_series_length",
    "safely_describe",
    "series_length",
    "serve",
    "where_we_are",
]


ENV_FILE = Path(".env")
"""Local, git-ignored overrides, read relative to the repository root.

Same convention as :data:`~.cli_identity.CONFIG`: the commands are documented as
being run from the root, and a path resolved against the caller's directory
would load a different file depending on where somebody stood.
"""


def main(argv: Sequence[str] | None = None, environ: dict[str, str] | None = None) -> int:
    """Run the command. Returns an exit code rather than raising."""
    arguments = parse(argv, __doc__)

    import os  # noqa: PLC0415 - read once, here, so tests can supply their own

    if environ is None:
        # Only the real process reads ``.env``; a caller that supplied an
        # environment gets exactly that one. ``override=False`` means a variable
        # already exported wins, so a one-off on the command line still beats the
        # file. This loads into ``os.environ`` rather than a local copy because
        # the things that need it — the report's destination among them — are
        # reached through call paths that never see this dict.
        load_dotenv(ENV_FILE, override=False)
    source = dict(os.environ) if environ is None else environ

    try:
        private = load_private(arguments.config)
        for line in describe(private, source, getattr(arguments, "rehearse", False)):
            print(line)
        sub_games = resolve_series_length(arguments.sub_games, SHARED_CONFIG)
        print(f"  series         {sub_games} sub-games (Appendix F table 18 row 1, fixed)")
        if arguments.command == "check":
            return 0
        if arguments.command == "report":
            return report(arguments, private)
        settings = ServerSettings.from_config(private.get("network", {}))
        if arguments.command == "play":
            require_playable(arguments, source, read_ngrok_api)
    except (StartupError, ValueError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 1

    inboxes = PeerInboxes()
    if arguments.command == "play":
        return play(arguments, private, settings, inboxes, source)

    print("serving — stop with Ctrl-C", flush=True)
    serve(build(inboxes), settings)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
