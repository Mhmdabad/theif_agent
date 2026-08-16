"""The four tools, over a real FastMCP server."""

import unittest

from sparring.config import SparConfig
from sparring.transport.loopback import Inboxes

try:
    import fastmcp  # noqa: F401
    HAVE_FASTMCP = True
except ImportError:
    HAVE_FASTMCP = False


@unittest.skipUnless(HAVE_FASTMCP, "needs the one dependency: pip install -r sparring/requirements.txt")
class TestToolSurface(unittest.TestCase):
    def setUp(self):
        from sparring.transport.server import build_server

        self.inboxes = Inboxes()
        self.mcp = build_server(SparConfig(), self.inboxes)

    def test_exactly_the_four_tools_the_reference_defines(self):
        import asyncio

        names = set(asyncio.run(self.mcp.get_tools()))
        self.assertEqual(names, {"negotiate", "receive_turn", "submit_audit", "receive_control"})

    def test_submit_audit_takes_payload_and_the_others_take_message(self):
        """The asymmetry that catches people out on a first meeting.

        It looks like an inconsistency in the reference and it is load-bearing: a peer that sends
        `message` to `submit_audit` gets a schema error at the one moment both sides are trying to
        agree on a result — the end-of-game audit.
        """
        import asyncio

        tools = asyncio.run(self.mcp.get_tools())
        for name, expected in (("negotiate", "message"), ("receive_turn", "message"),
                               ("receive_control", "message"), ("submit_audit", "payload")):
            params = tools[name].parameters.get("properties", {})
            self.assertIn(expected, params, msg=f"{name} should take {expected!r}, got {list(params)}")

    def test_handlers_enqueue_and_return_without_blocking(self):
        """No handler may wait on game progress.

        Two peers each awaiting the other inside a handler is an instant deadlock, and it is the
        highest-severity failure available in this design.
        """
        import asyncio

        tools = asyncio.run(self.mcp.get_tools())

        async def call(name, args):
            return await asyncio.wait_for(tools[name].run(args), timeout=2.0)

        asyncio.run(call("negotiate", {"message": {"terms": {}}}))
        asyncio.run(call("receive_turn", {"message": {"step": 1, "commit": "c1"}}))
        asyncio.run(call("submit_audit", {"payload": {"sender": "thief", "records": []}}))
        asyncio.run(call("receive_control", {"message": {"kind": "status", "sender": "police"}}))

        self.assertEqual(len(self.inboxes.agreements), 1)
        self.assertEqual(len(self.inboxes.turns), 1)
        self.assertEqual(len(self.inboxes.audits), 1)
        self.assertEqual(len(self.inboxes.controls), 1)


@unittest.skipUnless(HAVE_FASTMCP, "needs the one dependency")
class TestPortGuard(unittest.TestCase):
    def test_a_held_port_is_detected_by_connect_not_by_bind(self):
        """On Windows two binds can both succeed, so a trial bind would be quietly useless."""
        import socket

        from sparring.transport.server import _port_is_held

        with socket.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            port = held.getsockname()[1]
            self.assertTrue(_port_is_held("127.0.0.1", port))

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        self.assertFalse(_port_is_held("127.0.0.1", free))


if __name__ == "__main__":
    unittest.main()
