"""Bind counted reference-v3 games to both peers' Git revisions."""

from __future__ import annotations

import re
import subprocess
from typing import Any, cast

from sparring import kitref
from sparring.audit import AuditResult
from sparring.config import SparConfig
from sparring.negotiate import Agreed
from sparring.proto.messages import AuditPayload, Negotiation
from sparring.turnloop import SubGamePeer

SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_OPPONENT: dict[int, str] = {}
_CONFLICTS: set[int] = set()
_INSTALLED = False


def local_commit() -> str:
    answer = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, check=False, text=True
    ).stdout.strip()
    if not SHA_PATTERN.fullmatch(answer):
        raise RuntimeError("cannot resolve the Git commit used by this counted peer")
    return answer


def require_clean() -> str:
    for command in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        if subprocess.run(command, check=False).returncode:
            raise RuntimeError("counted play requires a clean tracked Git checkout")
    return local_commit()


def _remember(number: int | None, value: object) -> None:
    commit = str(value or "").lower()
    if number is None or not SHA_PATTERN.fullmatch(commit):
        return
    if number in _OPPONENT and _OPPONENT[number] != commit:
        _CONFLICTS.add(number)
    _OPPONENT[number] = commit


def reset() -> None:
    _OPPONENT.clear()
    _CONFLICTS.clear()


def annotate(
    ledger: list[dict[str, Any]], cop_fallback: str | None, thief_fallback: str | None
) -> None:
    fallback = {"police": cop_fallback, "thief": thief_fallback}
    ours = local_commit()
    for row in ledger:
        number, role = int(row["sub_game_number"]), str(row["role"])
        opponent_role = "thief" if role == "police" else "police"
        theirs = _OPPONENT.get(number) or str(fallback[opponent_role] or "").lower()
        if number in _CONFLICTS:
            raise ValueError(f"opponent declared conflicting Git commits in sub-game {number}")
        if not SHA_PATTERN.fullmatch(theirs):
            raise ValueError(
                f"opponent declared no Git commit for sub-game {number}; supply "
                f"--opponent-{opponent_role}-commit"
            )
        row["github_commit"], row["opponent_commit"] = ours, theirs


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    import sparring.netplay as netplay

    original_greeting = netplay.our_greeting
    original_verify = netplay.verify_peer
    original_step_zero = SubGamePeer.seal_step_zero
    original_audit = SubGamePeer._audit

    def greeting(
        cfg: SparConfig,
        role: str,
        sub_game_number: int,
        nonce: str,
        locks: dict[str, str],
        opponent_group: str | None = None,
    ) -> Negotiation:
        message = original_greeting(cfg, role, sub_game_number, nonce, locks, opponent_group)
        message.github_commit = local_commit()
        return message

    def verify(cfg: SparConfig, ours: Negotiation, raw: dict[str, Any]) -> Agreed:
        agreed = original_verify(cfg, ours, raw)
        _remember(ours.sub_game_number, raw.get("github_commit"))
        return agreed

    def step_zero(self: SubGamePeer, group_name: str) -> dict[str, Any]:
        record = cast(dict[str, Any], original_step_zero(self, group_name))
        record["payload"]["github_commit"] = local_commit()
        record["commit"] = kitref.commit(record["payload"], record["nonce"])
        return record

    def audit(self: SubGamePeer, theirs: dict[str, Any]) -> AuditResult:
        result = original_audit(self, theirs)
        for record in AuditPayload.from_wire(theirs).records:
            payload = record.get("payload", {})
            if payload.get("step") == 0:
                _remember(self.n, payload.get("github_commit"))
        return result

    netplay.our_greeting, netplay.verify_peer = greeting, verify
    SubGamePeer.seal_step_zero, SubGamePeer._audit = step_zero, audit
    _INSTALLED = True
