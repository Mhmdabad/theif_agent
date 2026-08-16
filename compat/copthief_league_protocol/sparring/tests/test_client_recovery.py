"""Dogfood finding 2: a held MCP session dies legitimately at every sub-game boundary against
a process-per-sub-game opponent (the rolling-window topology both real league teams use). The
client must re-establish once before deciding the peer is unreachable — the unpatched client
aborted a whole live series at the first boundary.

No fastmcp needed: the session machinery is stubbed at the seams the client itself defines.
"""

import unittest

from sparring.transport.client import McpClient, PeerUnreachable


class _FlakySession:
    """Dies on the first call, answers on the second — a sub-game boundary in miniature."""

    def __init__(self) -> None:
        self.calls = 0

    def call_tool(self, tool, args):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Session terminated")
        return {"ok": True}


class _Harness(McpClient):
    def __init__(self) -> None:
        super().__init__("http://stub.invalid/mcp")
        self.sessions_opened = 0
        self.session = _FlakySession()

    def _ensure_session(self) -> None:          # replaces the fastmcp handshake
        if not self._entered:
            self.sessions_opened += 1
            self._client = self.session
            self._entered = True

    def _await(self, value):                    # the stub is synchronous already
        return value


class TestSessionRecovery(unittest.TestCase):
    def test_a_dead_session_is_reopened_once_and_the_call_succeeds(self):
        client = _Harness()
        self.assertEqual(client.receive_turn({"step": 1}), {"ok": True})
        self.assertEqual(client.sessions_opened, 2)     # died once, reopened once

    def test_a_peer_that_stays_dead_is_still_diagnosed_as_unreachable(self):
        client = _Harness()
        client.session.call_tool = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("still terminated"))
        with self.assertRaises(PeerUnreachable):
            client.receive_turn({"step": 1})

    def test_the_audit_argument_asymmetry_survives_the_retry_path(self):
        # `submit_audit` takes `payload`; the other three take `message` — the reference's own
        # asymmetry, load-bearing at the one moment both sides must agree on a result.
        seen = []
        client = _Harness()
        client.session.call_tool = lambda tool, args: seen.append((tool, sorted(args))) or {}
        client.submit_audit({"records": []})
        client.negotiate({"terms": {}})
        self.assertEqual(seen, [("submit_audit", ["payload"]), ("negotiate", ["message"])])


if __name__ == "__main__":
    unittest.main()
