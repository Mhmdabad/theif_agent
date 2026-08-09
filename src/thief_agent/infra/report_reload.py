"""Reading a written report back, and proving it is the same document.

``report --send`` mails a file that was written when the match finished, which
means something has to turn ``result_<game_id>.json`` back into a
:class:`~.report_document.Report`. Parsing is the easy half. The half that
matters is the check afterwards.

**A reconstruction that does not reproduce the file is refused.** The attachment
is built by re-serialising the object this module returns, so if the round trip
loses or renames a field, the lecturer receives a document that differs from the
one committed to the repository — and the two are meant to be the same evidence.
Rather than trusting the parser, :func:`load` re-serialises what it built and
compares it with the bytes on disk, byte for byte. A mismatch is an error naming
the file, not a report quietly sent in a shape nobody reviewed.

That check also makes this module self-policing as the report grows: a field
added to :meth:`~.report_document.Report.to_dict` and forgotten here fails the
first time anybody sends a report, instead of silently travelling as a default.
"""

import json
from pathlib import Path
from typing import Any

from .report_document import Report
from .report_parts import ReportError, Repositories, SubGameResult

__all__ = ["load"]


def _sub_game(body: dict[str, Any]) -> SubGameResult:
    return SubGameResult(
        sub_game=int(body["sub_game"]),
        cop_score=int(body["cop_score"]),
        thief_score=int(body["thief_score"]),
        commit_hash=str(body["commit_hash"]),
        steps=int(body.get("steps", 0)),
        technical_loss=bool(body.get("technical_loss", False)),
    )


def load(path: Path) -> Report:
    """The report a finished match wrote, as the object that produced it.

    Raises:
        ReportError: if the file is not a report, or if re-serialising what was
            parsed does not reproduce the file exactly. Both mean the bytes
            about to be attached are not the bytes on disk.
    """
    text = path.read_text()
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportError(f"{path} is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ReportError(f"{path} does not hold a report object")

    try:
        report = Report(
            game_id=str(body["game_id"]),
            game_uid=str(body.get("game_uid", "")),
            role=str(body["reported_by"]["role"]),
            team=str(body["reported_by"]["team"]),
            opponent_team=str(body["opponent_team"]),
            repositories=Repositories(**body["repositories"]),
            sub_games=tuple(_sub_game(entry) for entry in body["sub_games"]),
            total_tokens=int(body["totals"]["total_tokens"]),
            agreed=bool(body["result_agreed_with_opponent"]),
            started_at=str(body.get("started_at", "")),
            ended_at=str(body.get("ended_at", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportError(f"{path} is missing something a report needs: {exc}") from exc

    if report.to_json() != text:
        raise ReportError(
            f"{path} does not survive a round trip: what was read back does not "
            "re-serialise to the bytes on disk, so the attachment would differ from "
            "the file committed to the repository"
        )
    return report
