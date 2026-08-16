"""Two real peers, two real servers, one sub-game over HTTP.

This is the test that would have caught the bug self-play could not: in self-play both sides
shared one outcome variable, which hid the fact that the thief computed its honest capture answer
and never sent it. Over a real transport the cop cannot see the board, so an answer that does not
travel means the cop waits out its budget and settles a game it won as a *timeout* — two peers
describing the same game differently, which is the shape App. E rule 35 zeroes for both teams.

One sub-game rather than six, deliberately: the property under test is that a networked sub-game
settles the same way on both sides with clean mutual audits, and six of them would take minutes of
CI for no extra signal.
"""

import socket
import tempfile
import threading
import unittest
from pathlib import Path

from sparring.config import SparConfig
from sparring.deadlines import Budgets
from sparring.transport.loopback import Inboxes

try:
    import fastmcp  # noqa: F401
    HAVE_FASTMCP = True
except ImportError:
    HAVE_FASTMCP = False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(HAVE_FASTMCP, "needs the one dependency")
class TestNetworkedSubGame(unittest.TestCase):
    def test_both_sides_settle_the_same_sub_game_identically(self):
        from sparring.deadlines import MonotonicClock
        from sparring.netplay import play_series
        from sparring.transport.client import McpClient
        from sparring.transport.server import build_server

        port_a, port_b = free_port(), free_port()
        inbox_a, inbox_b = Inboxes(), Inboxes()
        budgets = Budgets(turn_timeout=60.0, connect_timeout=20.0)

        for port, inboxes, gid in ((port_a, inbox_a, "sparring-a"),
                                   (port_b, inbox_b, "sparring-b")):
            mcp = build_server(SparConfig(group_id=gid), inboxes)
            threading.Thread(
                target=lambda m=mcp, p=port: m.run(transport="http", host="127.0.0.1", port=p,
                                                   show_banner=False),
                daemon=True).start()
        MonotonicClock().sleep(3.0)

        results: dict[str, object] = {}
        errors: dict[str, BaseException] = {}

        def run(name, gid, role, port_self, port_peer, inboxes, out):
            cfg = SparConfig(group_id=gid, natural_role=role, policy="random", seed=99,
                             budgets=budgets)
            client = McpClient(f"http://127.0.0.1:{port_peer}/mcp", timeout=20.0)
            try:
                results[name] = play_series(cfg, client, inboxes, Path(out), sub_games=1)
            except BaseException as exc:                       # noqa: BLE001 — reported below
                errors[name] = exc

        with tempfile.TemporaryDirectory() as td:
            threads = [
                threading.Thread(target=run, args=("a", "sparring-a", "police", port_a, port_b,
                                                   inbox_a, Path(td) / "a")),
                threading.Thread(target=run, args=("b", "sparring-b", "thief", port_b, port_a,
                                                   inbox_b, Path(td) / "b")),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=180)

            self.assertEqual(errors, {}, msg=f"a peer raised: {errors}")
            self.assertEqual(set(results), {"a", "b"}, "a peer never finished")

            a, b = results["a"], results["b"]
            self.assertEqual(a.game_uid, b.game_uid, "both peers must derive one game_uid")
            self.assertEqual(a.game_id, b.game_id, "game_id is the sorted pair, so it must match")
            self.assertEqual(len(a.ledger), 1)
            self.assertEqual(len(b.ledger), 1)

            # The property the self-play harness could not test: two independent drivers must
            # describe the same sub-game the same way. Step counts may differ by exactly one —
            # each side numbers its own half-turns, and the side that ends on an INBOUND
            # terminal claim legitimately ends one short (the reference's own convention,
            # observed cross-team in the 2026-08-04 dogfood run: 12 vs 13 on every window).
            # Under police-first ordering the counts happened to land equal, which is why this
            # assertion used to demand equality; thief-first (finding 1) surfaced the truth.
            self.assertEqual(a.ledger[0]["outcome"], b.ledger[0]["outcome"])
            self.assertLessEqual(abs(a.ledger[0]["steps"] - b.ledger[0]["steps"]), 1)
            self.assertNotEqual(a.ledger[0]["outcome"], "timeout",
                                "a settled sub-game must not read as a timeout — that was the bug")
            self.assertTrue(a.ledger[0]["audit_ok"], "our audit of their records must verify")
            self.assertTrue(b.ledger[0]["audit_ok"], "their audit of our records must verify")


if __name__ == "__main__":
    unittest.main()
