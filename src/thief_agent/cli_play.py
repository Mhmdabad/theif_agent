"""Serving and opening a match — the half that needs another team to exist.

Kept apart from the command module because none of it can be tested here: what
it drives is an opponent. The command module decides *whether* to play; this
decides what playing does.
"""

import argparse
import sys
from typing import Any

from .cli_failures import safely_describe
from .infra.inboxes import PeerInboxes
from .infra.mcp_server import ServerSettings, build, serve


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
            directory=arguments.out,
            rehearsal=arguments.rehearse,
        )
    except Exception as exc:  # noqa: BLE001 - a match failure is a message, not a traceback
        print(f"the match did not finish: {safely_describe(exc)}", file=sys.stderr)
        return 1
    for path in written:
        print(f"  wrote {path}")
    print("\nNothing has been emailed. Agree the result with the opponent first,")
    print("then send it deliberately — FR-7.16.")
    return 0
