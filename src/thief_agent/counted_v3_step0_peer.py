"""Strict peer declaration validation for counted Step-0 V2."""
# ruff: noqa: ANN401

from __future__ import annotations

import re
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}")
KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _slot(group_id: str, opponent: str) -> str:
    return "group_a" if group_id == sorted((group_id, opponent))[0] else "group_b"


def validate_declaration(body: dict[str, Any], spec: Any) -> None:
    if not KEY_ID.fullmatch(spec.key_id) or not spec.secret:
        raise ValueError("local Step-0 key configuration is invalid")
    if (body.get("game_id"), body.get("game_uid")) != (spec.game_id, spec.game_uid):
        raise ValueError("Step-0 game identity mismatch")
    if body.get("token_budget_per_series") != spec.token_budget:
        raise ValueError("Step-0 token budget mismatch")
    times = body.get("times", {})
    if not STAMP.fullmatch(str(times.get("game_start", ""))) or times.get("game_end") is not None:
        raise ValueError("Step-0 times must contain UTC game_start and null game_end")
    if times["game_start"] != spec.game_start:
        raise ValueError("Step-0 game_start mismatch")
    slot = _slot(spec.opponent_group, spec.group_id)
    other = "group_b" if slot == "group_a" else "group_a"
    teams = body.get("teams", {})
    if set(teams) != {"group_a", "group_b"}:
        raise ValueError("Step-0 must carry both deterministic team slots")
    if teams.get(other) is not None or not isinstance(teams.get(slot), dict):
        raise ValueError("Step-0 must use explicit null for the non-producing slot")
    _validate_team(teams[slot], spec)


def _validate_team(team: dict[str, Any], spec: Any) -> None:
    expected = spec.peer_team
    if team.get("group_id") != spec.opponent_group:
        raise ValueError("Step-0 producer group mismatch")
    if team.get("group_name") != expected["group_name"]:
        raise ValueError("Step-0 producer name mismatch")
    if team.get("members") != expected["members"]:
        raise ValueError("Step-0 producer members mismatch")
    repos = {"police": expected["repos"]["cop"], "thief": expected["repos"]["thief"]}
    if team.get("repos") != repos:
        raise ValueError("Step-0 producer repositories mismatch")
    for field in ("mcp_endpoint", "hardware", "llm_model", "code_version"):
        if field not in team:
            raise ValueError(f"Step-0 producer lacks {field}")
    commits = team.get("github_commits", {})
    if set(commits) != {"police", "thief"} or any(
        not SHA.fullmatch(str(value)) for value in commits.values()
    ):
        raise ValueError("Step-0 role commits are invalid")
    for role, frozen in spec.expected_peer_commits.items():
        if frozen and commits.get(role) != frozen:
            raise ValueError(f"Step-0 {role} commit differs from the coordinated release")
