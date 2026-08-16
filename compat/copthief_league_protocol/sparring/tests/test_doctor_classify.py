"""`diagnose`'s classifier, testable without a socket — anrbj666's E6.

The old probe sent only an MCP initialize POST whose Accept header already included
`text/event-stream`, so a healthy FastMCP peer answered 200 and the 406 branch — the state the
banner teaches you to poll for — was unreachable by the probe's own request. And the whole
function had no test at all. The classification is now a pure function of the two probes' raw
results, pinned here row by row.
"""

import unittest

from sparring.transport.client import classify_probe

MCP_OK = '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}'


class TestClassifyProbe(unittest.TestCase):
    def test_healthy_peer_is_exit_zero(self):
        code, message = classify_probe(406, 200, MCP_OK)
        self.assertEqual(code, 0)
        self.assertIn("PEER LISTENING", message)

    def test_421_wins_from_either_probe(self):
        for get_s, post_s in ((421, 200), (406, 421)):
            code, message = classify_probe(get_s, post_s, "")
            self.assertEqual(code, 7)
            self.assertIn("HOST HEADER", message)

    def test_502_is_edge_with_nothing_behind(self):
        code, message = classify_probe(502, 502, "")
        self.assertEqual(code, 7)
        self.assertIn("NOTHING BEHIND IT", message)

    def test_406_without_an_mcp_answer_is_a_fault_not_health(self):
        # The exact blind spot of the old probe, inverted: a GET that gets the healthy 406 but
        # an initialize that gets nothing MCP-shaped must NOT read as a ready peer.
        code, message = classify_probe(406, 500, "internal error")
        self.assertEqual(code, 7)
        self.assertIn("NO valid answer", message)

    def test_an_unusual_stack_that_answers_mcp_still_passes(self):
        code, message = classify_probe(200, 200, MCP_OK)
        self.assertEqual(code, 0)
        self.assertIn("unusual", message)

    def test_nothing_peer_shaped_fails(self):
        code, _ = classify_probe(404, 404, "<html>not found</html>")
        self.assertEqual(code, 7)


if __name__ == "__main__":
    unittest.main()
