"""Capture and validate the evidence required by a counted result."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .infra.report import Report
from .infra.report_parts import ReportError

TIMEZONE = ZoneInfo("Asia/Jerusalem")
ROW_KEYS = {
    "audit",
    "ended_at",
    "github_commit",
    "log_files",
    "result",
    "roles",
    "score",
    "started_at",
    "steps",
    "sub_game_number",
    "tie",
    "tokens",
    "winner_group",
}
TOP_KEYS = {
    "_schema",
    "final_result",
    "game_id",
    "game_uid",
    "groups",
    "league",
    "links",
    "mutual_agreement",
    "num_sub_games",
    "report_type",
    "schema_version",
    "sub_games",
    "timezone",
}


class _Peer(Protocol):
    sub_game_number: int


class _Artifacts(Protocol):
    log: Callable[..., object]


class _Netplay(Protocol):
    _play_one: Callable[..., object]
    ArtifactSet: _Artifacts


def _now() -> str:
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


@contextmanager
def capture(netplay: _Netplay) -> Iterator[dict[int, dict[str, str]]]:
    """Observe the vendored runner without changing the friendly wire."""
    timings: dict[int, dict[str, str]] = {}
    artifact_set = netplay.ArtifactSet
    original_play, original_log = netplay._play_one, artifact_set.log

    def timed_play(peer: _Peer, *args: object, **kwargs: object) -> object:
        timings[peer.sub_game_number] = {"started_at": _now()}
        return original_play(peer, *args, **kwargs)

    def timed_log(owner: object, number: int, *args: object, **kwargs: object) -> object:
        timings.setdefault(number, {"started_at": _now()})["ended_at"] = _now()
        return original_log(owner, number, *args, **kwargs)

    netplay._play_one, artifact_set.log = timed_play, timed_log
    try:
        yield timings
    finally:
        netplay._play_one, artifact_set.log = original_play, original_log


def add_timings(ledger: list[dict[str, Any]], timings: dict[int, dict[str, str]]) -> None:
    for row in ledger:
        row.update(timings.get(int(row["sub_game_number"]), {}))


def _timestamp(value: object, field: str, number: int) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReportError(f"sub-game {number} has no {field}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReportError(f"sub-game {number} has invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ReportError(f"sub-game {number} has timezone-free {field}")
    return parsed


def require_complete(report: Report) -> None:
    body = report.to_dict()
    missing = TOP_KEYS - body.keys()
    if missing:
        raise ReportError(f"counted result is missing top-level fields: {sorted(missing)}")
    groups = set(body["groups"])
    if set(body["links"].get("github", {})) != groups:
        raise ReportError("counted result must link both teams' repositories")
    for row in body["sub_games"]:
        number = int(row.get("sub_game_number", 0))
        missing = ROW_KEYS - row.keys()
        if missing:
            raise ReportError(f"sub-game {number} is missing fields: {sorted(missing)}")
        started = _timestamp(row["started_at"], "started_at", number)
        ended = _timestamp(row["ended_at"], "ended_at", number)
        if ended < started:
            raise ReportError(f"sub-game {number} ends before it starts")
        commits = row["github_commit"]
        if set(commits) != groups or any(value in ("", "unknown") for value in commits.values()):
            raise ReportError(f"sub-game {number} does not identify both Git commits")
