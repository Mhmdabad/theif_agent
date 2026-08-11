"""``report`` — read a written result and, on ``--send``, mail it.

Appendix E rule 32 requires the result to be reported automatically by Gmail,
and everything that does so already existed: :mod:`.infra.report` builds the
message, :mod:`.infra.gatekeeper` runs the three gates, :mod:`.infra.mailer`
sends. Nothing called them. The pipeline was complete, tested and unreachable
from the command line, so "automatic reporting" was a library.

**Sending is still not something a match does on its own**, and that is not a
contradiction of rule 32 but the other half of it. Rule 35 and FR-7.16 require
both sides to agree the result *before* either reports it, so the agreement
happens on the wire at the end of the match, and the sending happens here, when
somebody has looked at what was agreed. One command, run deliberately, is the
smallest thing that satisfies both rules at once.

**Two switches have to be thrown, not one.** ``--send`` says this invocation
intends to mail, and ``[email] mode = "send"`` in the private config says this
machine is configured to. A single flag one keystroke away from a lecturer's
inbox is the kind of interface that eventually sends a rehearsal report to a
real address; two, one of which lives in a file under review, is not.

Without ``--send`` the command is a dry run: it reads the report, says what it
would send and to whom, and exits. That is also the fastest way to check that a
result file is well formed before a match day.
"""

import argparse
from pathlib import Path
from typing import Any

from .infra.report import Message, Report, recipient
from .infra.report_parts import ReportError
from .infra.report_reload import load

__all__ = ["report"]


def _summarise(path: Path, body: Report, mode: str, sending: bool, to: str) -> list[str]:
    """What this command is about to do, in the order somebody would check it."""
    agreed = "yes" if body.agreed else "NO — the opponent did not confirm this score"
    return [
        f"  report        {path}",
        f"  game          {body.game_id} ({body.role} for {body.team} vs {body.opponent_team})",
        f"  score         cop {body.cop_total}, thief {body.thief_total} "
        f"over {len(body.sub_games)} sub-game(s)",
        f"  agreed        {agreed}",
        f"  recipient     {to}",
        f"  email mode    {mode}",
        f"  action        {'sending now' if sending else 'dry run, nothing will be sent'}",
    ]


def report(arguments: argparse.Namespace, private: dict[str, Any]) -> int:
    """Read the result file, print what it says, and mail it only if told twice.

    Every refusal below is covered in ``test_cli_report`` — an unreadable file,
    a missing ``mode``, an unagreed result — because each one is a case where
    the correct behaviour is *not* sending, and a bug in any of them would show
    up as mail in a lecturer's inbox rather than as a red test. Only
    :func:`_send`, which reaches Google, is left uncovered.
    """
    mode = str(private.get("email", {}).get("mode", "draft"))
    try:
        body = load(Path(arguments.report))
    except (OSError, ReportError) as exc:
        print(f"cannot read the report: {exc}")
        return 1
    try:
        to = recipient()
    except ReportError as exc:
        # Resolved before the summary rather than inside it: the destination is
        # the one line of that summary somebody is actually checking, and a
        # summary printed with it missing is worse than no summary at all.
        print(f"cannot report: {exc}")
        return 1

    sending = bool(arguments.send) and mode == "send"
    for line in _summarise(Path(arguments.report), body, mode, sending, to):
        print(line)

    if not arguments.send:
        print("\nDry run. Re-run with --send to mail it.")
        return 0
    if mode != "send":
        print(
            f'\nRefusing: --send was given but [email] mode is "{mode}". Set it to "send" '
            "in the private config once this machine is meant to mail a real lecturer."
        )
        return 1
    if not body.agreed:
        print(
            "\nRefusing: this report says the opponent never confirmed the score. "
            "Appendix E rule 35 wants an agreed result; settle it with the other "
            "team and re-run the match, or agree it and re-write the file."
        )
        return 1

    return _send(body, private)


def _send(body: Report, private: dict[str, Any]) -> int:  # pragma: no cover - reaches Google
    """Hand the report to the mail pipeline, reporting whatever it says.

    Imported here rather than at module scope so that reading a report needs no
    Google library installed, which is what makes the dry run usable anywhere.
    """
    from .cli_report_send import deliver  # noqa: PLC0415
    from .infra.mailer import SendError  # noqa: PLC0415

    address = str(private.get("email", {}).get("sender", ""))
    try:
        answer = deliver(body, address, private)
    except (SendError, OSError, ValueError) as exc:
        print(f"\nthe report was not sent: {exc}")
        return 1
    print(f"\nsent — {Message(report=body, sender=address).subject()}")
    print(f"  provider said {answer}")
    return 0
