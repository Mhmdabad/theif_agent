from collections import deque
from types import SimpleNamespace

import pytest

from thief_agent import reference_v3 as _reference_v3  # noqa: F401
from thief_agent.reference_v3_series_consensus import (
    CLAIM,
    ConsensusError,
    exchange,
    settlement_scope,
)
from thief_agent.shared.consensus import consensus_signature


def result() -> SimpleNamespace:
    ledger = [
        {
            "sub_game_number": n,
            "role": "police" if n % 2 else "thief",
            "outcome": "survival",
            "score": 5 if n % 2 else 10,
        }
        for n in range(1, 7)
    ]
    return SimpleNamespace(game_id="s82kma9e-vs-yamanagh", ledger=ledger, settled=True)


def test_exchange_sends_and_accepts_the_exact_envelope() -> None:
    played, cfg = result(), SimpleNamespace(group_id="s82kma9e")
    digest = consensus_signature(settlement_scope(played, cfg))
    inboxes = SimpleNamespace(
        audits=deque(
            [
                {
                    "sender": "police",
                    "result_claim": CLAIM,
                    "records": [],
                    "consensus_sha": digest,
                    "ignored_extension": True,
                }
            ]
        )
    )

    class Client:
        sent: list[dict[str, object]] = []

        def submit_audit(self, payload: dict[str, object]) -> dict[str, bool]:
            self.sent.append(payload)
            return {"ok": True}

    client = Client()
    assert exchange(played, cfg, client, inboxes) == digest
    assert client.sent == [
        {
            "sender": "thief",
            "result_claim": CLAIM,
            "records": [],
            "consensus_sha": digest,
        }
    ]


def test_exchange_refuses_a_different_digest() -> None:
    inboxes = SimpleNamespace(
        audits=deque(
            [
                {
                    "sender": "police",
                    "result_claim": CLAIM,
                    "records": [],
                    "consensus_sha": "0" * 64,
                }
            ]
        )
    )
    client = SimpleNamespace(submit_audit=lambda _payload: {"ok": True})
    with pytest.raises(ConsensusError, match="series hash mismatch"):
        exchange(result(), SimpleNamespace(group_id="s82kma9e"), client, inboxes)


def test_exchange_waits_until_our_envelope_is_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    played, cfg = result(), SimpleNamespace(group_id="s82kma9e")
    digest = consensus_signature(settlement_scope(played, cfg))
    inboxes = SimpleNamespace(
        audits=deque(
            [
                {
                    "sender": "police",
                    "result_claim": CLAIM,
                    "records": [],
                    "consensus_sha": digest,
                }
            ]
        )
    )

    class Client:
        calls = 0

        def submit_audit(self, _payload: dict[str, object]) -> dict[str, bool]:
            self.calls += 1
            if self.calls == 1:
                raise OSError("receiver still closing")
            return {"ok": True}

    monkeypatch.setenv("SERIES_CONSENSUS_RETRY", "0")
    client = Client()
    assert exchange(played, cfg, client, inboxes) == digest
    assert client.calls == 2
