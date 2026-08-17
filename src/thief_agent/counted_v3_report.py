"""Turn a settled reference-v3 ledger into this agent's counted report."""
# ruff: noqa: I001

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from . import reference_v3 as _reference_v3  # noqa: F401 - exposes vendored sparring

from sparring.rules.outcome import Outcome, Role, TIE_SCORE, score_for

from .infra.report import Report, Repositories, SubGameResult
from .shared.consensus import consensus_signature
from .shared.consensus_scope import consensus_scope
from .shared.config import canonical_bytes


class SettledResult(Protocol):
    game_id: str
    game_uid: str
    ledger: list[dict[str, Any]]


def _standing(ledger: list[dict[str, Any]], ours: str, theirs: str) -> dict[str, Any]:
    totals, won = {ours: 0, theirs: 0}, {ours: 0, theirs: 0}
    rows = []
    for item in ledger:
        role, outcome = Role(item["role"]), Outcome(item["outcome"])
        a, b = int(item["score"]), score_for(outcome, role.other)
        totals[ours] += a
        totals[theirs] += b
        winner = ours if a > b else theirs if b > a else None
        if winner:
            won[winner] += 1
        rows.append((role, outcome, a, b, winner))
    tied = totals[ours] == totals[theirs]
    if tied:
        totals = {group: score + TIE_SCORE for group, score in totals.items()}
    return {
        "total_score": totals,
        "sub_games_won": won,
        "ties": sum(winner is None for *_, winner in rows),
        "winner_group": None if tied else max(totals, key=lambda group: totals[group]),
        "series_tie": tied,
    }


def build_report(
    result: SettledResult, cfg: dict[str, Any], role: str, counts: tuple[int, int]
) -> Report:
    ours, theirs = cfg["ours"], cfg["theirs"]
    standing = _standing(result.ledger, ours, theirs)
    subs = []
    for item in result.ledger:
        outcome = Outcome(item["outcome"])
        subs.append(
            SubGameResult(
                sub_game=int(item["sub_game_number"]),
                cop_score=score_for(outcome, Role.POLICE),
                thief_score=score_for(outcome, Role.THIEF),
                commit_hash=str(item["github_commit"]),
                opponent_commit_hash=str(item["opponent_commit"]),
                steps=int(item["steps"]),
                log_verified=bool(item["audit_ok"]),
                tampered=bool(item.get("tampered", False)),
            )
        )
    repos = Repositories(
        cfg["cop_repo"], cfg["thief_repo"], cfg["opponent_cop_repo"], cfg["opponent_thief_repo"]
    )
    draft = Report(
        result.game_id,
        role,
        ours,
        theirs,
        tuple(subs),
        0,
        True,
        repositories=repos,
        game_uid=result.game_uid,
        starting_role=role,
        series_result=standing,
        games_played_including_this=counts[0],
        opponent_games_played_including_this=counts[1],
    )
    body = draft.to_dict()
    scope = consensus_scope(result.game_id, standing, body["sub_games"])
    digest = consensus_signature(scope)
    return replace(draft, result_claim_sha256=digest)


def promote_wire(directory: Path, cfg: dict[str, Any]) -> list[Path]:
    source = next((directory / ".wire").glob("sparring_*"))
    written: list[Path] = []
    league = {
        "authority": "book App. E rule 52 — the one counted series of this pairing",
        "counted": True,
        "reason": "counted",
    }
    for path in source.glob("*.json"):
        if path.name.startswith("result_"):
            continue
        body = json.loads(path.read_text(encoding="utf-8"))
        body["league"] = league
        if path.name.startswith("declaration_"):
            body.pop("mail_surface", None)
            body["max_tokens_per_game"] = 200000
            groups = body.get("groups", {})
            for block in groups.values():
                gid = block.get("group_id")
                if gid == cfg["ours"]:
                    block["group_name"] = cfg["our_name"]
                    block["members"] = cfg["our_members"]
                    block["repos"] = {"cop": cfg["cop_repo"], "thief": cfg["thief_repo"]}
                    block["mcp_servers"] = {"series": cfg["public"]}
                elif gid == cfg["theirs"]:
                    block["group_name"] = cfg["their_name"]
                    block["members"] = cfg["their_members"]
                    block["repos"] = {
                        "cop": cfg["opponent_cop_repo"],
                        "thief": cfg["opponent_thief_repo"],
                    }
                    block["mcp_servers"] = {"series": cfg["peer"]}
        target = directory / path.name
        target.write_bytes(canonical_bytes(body))
        written.append(target)
    return written


def agreement(report: Report) -> tuple[dict[str, Any], str]:
    body = json.loads(report.to_json())
    return consensus_scope(
        report.game_id, body["final_result"], body["sub_games"]
    ), report.result_claim_sha256
