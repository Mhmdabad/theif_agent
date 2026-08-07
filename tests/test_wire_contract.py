"""Every payload this peer sends, replayed against the server it will hit.

The gap this closes cost a live warm-up. ``test_mcp_server`` already asserted
that the four tools take a parameter called ``message`` — *"the parameter name
is message, not something else"* — and it was right. Nothing asserted that the
**client sends that name**, and two of the four call sites did not: the
announcement went out under ``greeting`` and the digest under ``config_sha256``.

Both halves were correct. Both halves were tested. Neither test could see the
other, and the in-process match could not either, because it hands mappings to
:class:`PeerInboxes` as Python keyword arguments and never goes near FastMCP's
schema validation. The mismatch was reachable only over a socket, against a
peer, which is the one configuration no test in this project ran.

So this drives the real client methods through a recording transport, then
replays exactly what they emitted at the real registered server. A wrong key
fails here rather than in front of another team.
"""

import asyncio
from typing import Any

import pytest
from fastmcp import Client

from thief_agent.infra.ceremony import Commitment
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.mcp_server import build
from thief_agent.infra.protocol import AuditPayload
from thief_agent.runtime.orchestrator import Orchestrator
from thief_agent.runtime.peer import McpPeer
from thief_agent.shared.config import config_sha256

WHEN = "2026-08-05T12:00:00+00:00"
SETTINGS = ClientSettings(opponent_url="http://127.0.0.1:8801/mcp", retry_backoff_sec=0.0)


class Recorder:
    """A transport that answers plausibly and keeps what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.sent.append((tool, payload))
        return {"ok": True}


def outbound() -> list[tuple[str, dict[str, Any]]]:
    """One of every call this peer makes, as the real code builds it.

    Driven through the real methods rather than written out by hand. A literal
    copied into a test is a copy of the same mistake — this bug was two string
    literals that agreed with nothing.
    """
    recorder = Recorder()
    client = OpponentClient(recorder, SETTINGS)
    orchestrator = Orchestrator(PeerInboxes(), client)
    parameters = {"board_and_agents": {"grid_size": 8}}

    orchestrator.announce(orchestrator.greeting("https://x.ngrok-free.app", "g1"))
    # The gate consumes the opponent's digest before it returns, so this stands
    # in for the peer that agreed. Answering through the real ``negotiate`` door
    # rather than by seeding the queue keeps the recorded call the honest one.
    orchestrator.inboxes.negotiate({"config_sha256": config_sha256(parameters)})
    orchestrator.agree_config(parameters)

    peer = McpPeer(
        role="thief",
        client=client,
        inboxes=PeerInboxes(),
        game_uid="series-123",
        sub_game=1,
        now=WHEN,
    )
    peer.send_commit(Commitment(step=1, sender="thief", commit="a" * 64, timestamp=WHEN))
    peer._submit([], "in_progress")

    return recorder.sent


async def deliver(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Call the tool on a real server, and hand back what it answered."""
    inboxes = PeerInboxes(game_uid="series-123", sub_game=1)
    async with Client(build(inboxes)) as client:
        answer = await client.call_tool(tool, payload)
    data = answer.data
    assert isinstance(data, dict), f"{tool} answered {type(data).__name__}, not an object"
    return data


class TestWhatWeSendIsWhatTheyAccept:
    """The client's payloads, against the server's registered signatures."""

    def test_every_call_site_is_covered_here(self) -> None:
        """A fifth outbound call added without a case here would slip through."""
        assert {tool for tool, _ in outbound()} == {"negotiate", "receive_turn", "submit_audit"}

    @pytest.mark.parametrize(("tool", "payload"), outbound())
    def test_the_server_accepts_it(self, tool: str, payload: dict[str, Any]) -> None:
        """No pydantic validation error, which is what a wrong key produces."""
        assert asyncio.run(deliver(tool, payload))["ok"] is True, (
            f"{tool} refused {sorted(payload)}"
        )

    @pytest.mark.parametrize(("tool", "payload"), outbound())
    def test_it_carries_exactly_one_argument(self, tool: str, payload: dict[str, Any]) -> None:
        """The protocol's tools take one body. An extra key is a second mistake.

        Worth stating separately: the server would accept a payload that merely
        *contained* the right key, so a call sending both the right name and a
        leftover wrong one would pass the check above and confuse an auditor
        reading the wire.
        """
        assert len(payload) == 1, f"{tool} sends {sorted(payload)}"


class TestTheDigestExchangeStillTravelsUnderMessage:
    """``negotiate`` carries two different bodies, and both go in the same slot.

    A greeting and a config digest are unrelated payloads sharing one tool, so
    the temptation is to name the parameter after the content. That is exactly
    the mistake that was there: ``{"config_sha256": ...}`` described the body
    and matched no signature.
    """

    def test_the_digest_is_nested_rather_than_spread(self) -> None:
        calls = [payload for tool, payload in outbound() if tool == "negotiate"]
        digest = [p for p in calls if "config_sha256" in str(p)][0]
        assert list(digest) == ["message"]
        assert "config_sha256" in digest["message"]

    def test_the_greeting_is_too(self) -> None:
        """The body was never wrong — only the argument it travelled in was.

        ``accept_greeting`` reads ``message["greeting"]``, so the inner shape
        was correct from the start. What was missing was the tool parameter
        wrapping it, which is why the failure was a pydantic binding error and
        not a malformed-greeting error.
        """
        calls = [payload for tool, payload in outbound() if tool == "negotiate"]
        greeting = [p for p in calls if "public_url" in str(p)][0]
        assert list(greeting) == ["message"]
        assert greeting["message"]["greeting"]["role"] == "thief"


class TestAuditPayloadShape:
    def test_submit_audit_sends_its_body_under_payload(self) -> None:
        """The one tool whose parameter is *not* called ``message``.

        Named for what it carries because an audit body is not a message in the
        protocol's sense, and the asymmetry is the kind of thing a second
        implementer gets wrong. Pinned here so it cannot drift quietly.
        """
        sent = dict(outbound())["submit_audit"]
        assert list(sent) == ["payload"]
        assert AuditPayload.from_dict(sent["payload"]).sender == "thief"
