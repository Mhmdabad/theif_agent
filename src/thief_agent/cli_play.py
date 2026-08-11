"""Serving and opening a match — the half that needs another team to exist.

Kept apart from the command module because none of it can be tested here: what
it drives is an opponent. The command module decides *whether* to play; this
decides what playing does.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from .cli_failures import safely_describe
from .cli_identity import PACKAGE
from .cli_report import report
from .infra.inboxes import PeerInboxes
from .infra.mcp_server import ServerSettings, build, serve


def play(
    arguments: argparse.Namespace,
    private: dict[str, Any],
    settings: ServerSettings,
    inboxes: PeerInboxes,
    environ: dict[str, str],
) -> int:  # pragma: no cover - drives a live opponent
    """Serve, open a match, write the artefacts, then report it.

    Not covered by tests, and the reason is the same one that keeps
    ``run_live`` uncovered: the thing under test would be *another team*.
    Everything it composes — the handshake, the digest exchange, the ceremony,
    the audit, the artefact set — is covered against a real opponent in
    ``test_localhost_match``. This function is the part that cannot be.
    """
    import threading

    from .runtime.driver import ROLE, open_match

    if arguments.opponent:
        environ = {**environ, "OPPONENT_URL": arguments.opponent}
    if arguments.public:
        environ = {**environ, "PUBLIC_URL": arguments.public}
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
            starting_role=arguments.starting_role or ROLE,
        )
    except Exception as exc:  # noqa: BLE001 - a match failure is a message, not a traceback
        print(f"the match did not finish: {safely_describe(exc)}", file=sys.stderr)
        return 1
    for path in written:
        print(f"  wrote {path}")
    result = next((path for path in written if path.name.startswith("result_")), None)
    return _report_now(result, private, bool(arguments.rehearse))


def _report_now(
    result: Path | None, private: dict[str, Any], rehearsal: bool
) -> int:  # pragma: no cover - reaches Google
    """Mail the result the moment a real match ends, because §9.3 says to.

    **A rehearsal never sends**, and that exemption is the whole reason this can
    be automatic at all. §9.3 removes human judgement from reporting a *legal
    match against an opposing team*; a practice run against our own second
    laptop is not one, and mailing the lecturer every time somebody tests the
    plumbing would be the exact failure §9.3 warns about — code holding the key
    to a live mail account — arriving as a nuisance rather than a bug.

    Everything else is delegated to :func:`~.cli_report.report` rather than
    reimplemented, so the automatic path cannot be more permissive than the
    deliberate one: the same ``mode`` gate, the same refusal to send a score the
    opponent never confirmed (rule 35), the same three gatekeeper defences, and
    the same printed recipient. A second copy of those checks would drift, and
    the direction it would drift is mail going out that should not have.

    A refusal here returns non-zero even though the match itself succeeded. The
    artefacts are on disk either way, but rule 35 scores an unsent report as no
    report — zero for us *and* for the opponent — so this is not something to
    exit quietly on.
    """
    if result is None:
        print("\nno result file was written, so there is nothing to report", file=sys.stderr)
        return 1
    if rehearsal:
        print("\nRehearsal: nothing emailed. A real match reports itself; to send this one:")
        print(f"  python -m {PACKAGE} report --report {result} --send")
        return 0
    print("\nReporting automatically (§9.3 — both sides must send, separately):")
    return report(argparse.Namespace(report=str(result), send=True), private)
