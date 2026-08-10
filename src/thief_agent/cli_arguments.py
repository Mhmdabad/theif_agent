"""Every flag this peer accepts, and the help text that keeps it honest.

Split out of :mod:`.__main__`, which grew past the module budget when ``report``
arrived. The separation is not only arithmetic: the parser is the one part of
the command that is pure description — no config is read, no socket is bound,
nothing is decided — so keeping it apart leaves the entry point as the sequence
of decisions it actually makes.

The help strings are load-bearing rather than decorative. ``--sub-games`` exists
only so that asking for a series of any other length is refused out loud, and
``--send`` says in its own text why it is not sufficient on its own. Somebody
reading ``--help`` five minutes before a match is the reader these are for.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from .cli_identity import CONFIG, PACKAGE

__all__ = ["parse"]


def parse(argv: Sequence[str] | None, description: str | None) -> argparse.Namespace:
    """Read the command line. Raises ``SystemExit`` on a bad one, as argparse does."""
    parser = argparse.ArgumentParser(prog=f"python -m {PACKAGE}", description=description)
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=("serve", "check", "play", "report"),
        help=(
            "serve: run the peer and answer. check: report the configuration and exit. "
            "play: serve and open a match against an opponent who has already started. "
            "report: read a written result and, with --send, mail it to the lecturer."
        ),
    )
    parser.add_argument("--config", type=Path, default=CONFIG, help="private per-peer TOML")
    parser.add_argument("--game-id", default="", help="agreed with the opponent beforehand")
    parser.add_argument("--out", type=Path, default=Path("artefacts"), help="where to write")
    parser.add_argument(
        "--sub-games",
        type=int,
        default=None,
        help="sub-games in the series. Appendix F table 18 row 1 fixes this at six and "
        "deviating disqualifies the team, so the length comes from the shared config; "
        "the flag exists only so that asking for another is refused out loud",
    )
    parser.add_argument(
        "--starting-role",
        choices=("police", "thief"),
        default=None,
        help="the role WE play in sub-game 1, agreed with the opponent (they start as "
        "the opposite). Roles alternate every sub-game either way; omitted, this "
        "repository's natural role opens",
    )
    parser.add_argument(
        "--opponent",
        default="",
        help="the opponent's public MCP URL (…/mcp). Overrides OPPONENT_URL",
    )
    parser.add_argument(
        "--public",
        default="",
        help="our own public URL as the opponent should call it. Overrides PUBLIC_URL; "
        "omitted, a locally running ngrok is asked for it",
    )
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="play this project's other agent over loopback, no tunnel — practice only, "
        "never against another team",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artefacts/result.json"),
        help="the result file the report command reads",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help='actually mail the report. Also needs [email] mode = "send" in the private '
        "config: one flag between a rehearsal and a lecturer's inbox is one too few",
    )
    return parser.parse_args(argv)
