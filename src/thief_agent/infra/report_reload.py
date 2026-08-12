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
from .report_parts import ReportError, SubGameResult

__all__ = ["load"]


def _sub_game(body: dict[str, Any], us: str, them: str) -> SubGameResult:
    """One sub-game, read back out of the group-keyed document.

    The file says what each *group* scored; :class:`SubGameResult` holds what
    each *seat* scored, because that is what the book's scoring table is written
    in. Which seat we sat in is in ``roles``, so the mapping is recoverable --
    and doing it here keeps the rest of the code free of the question.
    """
    ours = str(body["roles"][us])
    our_score, their_score = int(body["score"][us]), int(body["score"][them])
    cop, thief = (our_score, their_score) if ours == "police" else (their_score, our_score)
    return SubGameResult(
        sub_game=int(body["sub_game_number"]),
        cop_score=cop,
        thief_score=thief,
        commit_hash=str(body["github_commit"][us]),
        steps=int(body.get("steps", 0)),
        technical_loss=str(body.get("result", "")) == "technical_loss",
        started_at=str(body.get("started_at", "")),
        ended_at=str(body.get("ended_at", "")),
        tokens=int(body.get("tokens", {}).get(us, 0)),
        log_verified=bool(body.get("audit", {}).get("log_verified", True)),
        tampered=bool(body.get("audit", {}).get("tampered", False)),
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
        us, them = (str(name) for name in body["groups"])
        final = body.get("final_result", {})
        agreement = body.get("mutual_agreement", {})
        played = [_sub_game(entry, us, them) for entry in body["sub_games"]]
        report = Report(
            game_id=str(body["game_id"]),
            game_uid=str(body.get("game_uid", "")),
            role=str(body["reported_by"]["role"]),
            team=us,
            opponent_team=them,
            sub_games=tuple(played),
            total_tokens=int(final.get("tokens_total_series", {}).get(us, 0)),
            agreed=bool(agreement.get("confirmed", False)),
            starting_role=str(body["sub_games"][0]["roles"][us]) if played else "",
            series_result=final or None,
            mcp_addresses=body.get("mcp_addresses"),
            machine=body.get("machine"),
            signature=str(body.get("signature", "")),
            result_claim_sha256=str(agreement.get("sha256", "")),
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
