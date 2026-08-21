"""Optional post-series consensus exchange used by stricter reference-v3 peers."""
# ruff: noqa: ANN401

from __future__ import annotations

import os
import time
from typing import Any

from .shared.consensus import consensus_signature
from .shared.consensus_scope import consensus_scope

ENABLED = "SERIES_CONSENSUS"
TIMEOUT = "SERIES_CONSENSUS_TIMEOUT"
RETRY = "SERIES_CONSENSUS_RETRY"
CLAIM = "series_consensus"
_INSTALLED = False


class ConsensusError(RuntimeError):
    """The peer did not confirm the same final series bytes."""


def _opponent(game_id: str, ours: str) -> str:
    prefix, suffix = f"{ours}-vs-", f"-vs-{ours}"
    if game_id.startswith(prefix):
        return game_id[len(prefix) :]
    if game_id.endswith(suffix):
        return game_id[: -len(suffix)]
    raise ConsensusError(f"game_id {game_id!r} does not contain our group {ours!r}")


def settlement_scope(result: Any, cfg: Any) -> dict[str, Any]:
    """Derive the kit's five-key aggregate and five-key row consensus scope."""
    from sparring.rules.outcome import TIE_SCORE, Outcome, Role, score_for

    ours, theirs = cfg.group_id, _opponent(result.game_id, cfg.group_id)
    totals, won = {ours: 0, theirs: 0}, {ours: 0, theirs: 0}
    rows: list[dict[str, Any]] = []
    for item in result.ledger:
        role, outcome = Role(item["role"]), Outcome(item["outcome"])
        our_score = int(item["score"])
        their_score = score_for(outcome, role.other)
        totals[ours] += our_score
        totals[theirs] += their_score
        winner = ours if our_score > their_score else theirs if their_score > our_score else None
        if winner:
            won[winner] += 1
        rows.append(
            {
                "sub_game_number": int(item["sub_game_number"]),
                "roles": {ours: role.value, theirs: role.other.value},
                "result": outcome.value,
                "winner_group": winner,
                "score": {ours: our_score, theirs: their_score},
            }
        )
    tied = totals[ours] == totals[theirs]
    awarded = {group: score + TIE_SCORE for group, score in totals.items()} if tied else totals
    aggregate = {
        "total_score": awarded,
        "sub_games_won": won,
        "ties": sum(row["winner_group"] is None for row in rows),
        "winner_group": None if tied else max(totals, key=totals.__getitem__),
        "series_tie": tied,
    }
    return consensus_scope(result.game_id, aggregate, rows)


def settlement_sha(result: Any, cfg: Any) -> str:
    return consensus_signature(settlement_scope(result, cfg))


def exchange(result: Any, cfg: Any, client: Any, inboxes: Any) -> str:
    """Resend our envelope until the peer's matching envelope is queued locally."""
    from sparring.rules.outcome import Role

    digest = settlement_sha(result, cfg)
    sender = str(result.ledger[-1]["role"])
    expected_sender = Role(sender).other.value
    envelope = {
        "sender": sender,
        "result_claim": CLAIM,
        "records": [],
        "consensus_sha": digest,
    }
    timeout = float(os.getenv(TIMEOUT, "400"))
    retry = float(os.getenv(RETRY, "2"))
    deadline, last_error = time.monotonic() + timeout, "peer sent no envelope"
    while time.monotonic() < deadline:
        try:
            client.submit_audit(envelope)
        except Exception as exc:  # network retries are the contract of this exchange
            last_error = f"send failed: {exc}"
        while inboxes.audits:
            peer = inboxes.audits.popleft()
            if peer.get("result_claim") != CLAIM:
                continue
            if peer.get("sender") != expected_sender:
                raise ConsensusError(
                    f"peer consensus sender is {peer.get('sender')!r}, expected {expected_sender!r}"
                )
            if peer.get("records") != []:
                raise ConsensusError("peer consensus envelope has non-empty records")
            if peer.get("consensus_sha") != digest:
                raise ConsensusError(
                    f"series hash mismatch: ours {digest}, theirs {peer.get('consensus_sha')}"
                )
            print(f"  series consensus confirmed: {digest}")
            return digest
        time.sleep(retry)
    raise ConsensusError(f"series consensus timed out after {timeout:g}s ({last_error})")


def install() -> None:
    """Wrap the network series driver, leaving ordinary kit peers unchanged by default."""
    global _INSTALLED
    if _INSTALLED:
        return
    import sparring.netplay as netplay

    original = netplay.play_series

    def wrapped(cfg: Any, client: Any, inboxes: Any, artifacts: Any, sub_games: int = 6) -> Any:
        result = original(cfg, client, inboxes, artifacts, sub_games=sub_games)
        enabled = os.getenv(ENABLED, "").lower() in {"1", "true", "yes"}
        if enabled and result.settled and len(result.ledger) == sub_games:
            try:
                exchange(result, cfg, client, inboxes)
            except ConsensusError as exc:
                result.settled = False
                result.note = str(exc)
                print(f"  series consensus failed: {exc}")
        return result

    netplay.play_series = wrapped
    _INSTALLED = True
