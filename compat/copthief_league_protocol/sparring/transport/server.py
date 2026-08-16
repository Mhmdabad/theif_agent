"""The FastMCP surface: four tools, and none of them may block.

The other module permitted outbound networking, and the only one that imports fastmcp.

**Every handler validates, enqueues, and returns.** None of them waits for game progress. Two
peers each awaiting the other inside a handler is an instant deadlock, and it is the
highest-severity failure available in this design — which is why the game loop lives on a worker
thread and the handlers only ever touch a queue.

The tool names and argument names mirror the reference exactly, including the asymmetry:
``negotiate``, ``receive_turn`` and ``receive_control`` take ``message``; ``submit_audit`` takes
``payload``.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sparring import CODE_VERSION
from sparring.config import SparConfig
from sparring.preflight import assert_sparring_ready
from sparring.transport.loopback import Inboxes


def build_server(cfg: SparConfig, inboxes: Inboxes):
    """Construct the FastMCP app. Imported lazily so the zero-dependency tier stays honest."""
    from fastmcp import FastMCP

    mcp = FastMCP(name=f"copthief-sparring-{cfg.group_id}")

    @mcp.tool
    def negotiate(message: dict) -> dict:
        """Receive the opponent's signed game agreement."""
        inboxes.agreements.append(message)
        return {"ok": True}

    @mcp.tool
    def receive_turn(message: dict) -> dict:
        """Receive the opponent's turn message."""
        inboxes.turns.append(message)
        return {"ok": True}

    @mcp.tool
    def submit_audit(payload: dict) -> dict:
        """Receive the opponent's end-of-game audit reveal (records + nonces)."""
        inboxes.audits.append(payload)
        return {"ok": True}

    @mcp.tool
    def receive_control(message: dict) -> dict:
        """Receive an opponent control signal (enable / status / restart / quit)."""
        inboxes.controls.append(message)
        return {"ok": True}

    return mcp


def _port_is_held(host: str, port: int) -> bool:
    """A connect probe, never a trial bind.

    Binding to test would race the real server for the address — and on Windows two binds can
    both succeed, which would make this check quietly useless on the platform most likely to be
    running the peer.
    """
    import socket

    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def serve(cfg: SparConfig, *, host: str, port: int, peer_url: str | None,
          artifacts: Path, await_peer: bool = False) -> int:
    """Stand the peer up. Preflight first — the server never binds a port if it refuses."""
    report = assert_sparring_ready(cfg)

    if _port_is_held(host, port):
        print(f"  something is already listening on {host}:{port} — refusing to start a second "
              f"peer.\n"
              f"  A peer that starves behind another consumes a sub-game of the series and reports "
              f"a\n  timeout it did not cause. Check for an orphan: killing a shell does not kill "
              f"what it\n  spawned.")
        return 5

    inboxes = Inboxes()
    mcp = build_server(cfg, inboxes)

    print(f"SPARRING — UNCOUNTED (App. E rule 52) — NO REPORT OWED — mail surface ABSENT "
          f"(scan {report.mail_scan_sha256[:8]})")
    print(f"{CODE_VERSION}  listening on http://{host}:{port}/mcp")
    print(f"  wire=reference-v3  scent={cfg.scent_model}  policy={cfg.policy}  "
          f"group={cfg.group_id}")
    print(f"  artifacts -> {artifacts.resolve()}")
    print("  Expect NO report from this host: sparring is not a game under App. E rules 32/35.")
    if peer_url:
        print(f"  opponent: {peer_url}")
    else:
        # Without --peer there is nothing to drive: the four tools answer, and NOTHING else
        # happens. Say so loudly — the 2026-08-04 dogfood run followed docs that implied this
        # mode plays a game, and greetings queued into inboxes nobody drains, which is the
        # exact hazard the module docstring warns about.
        print("  TOOLS ONLY — no game loop runs in this mode. This process will accept your\n"
              "  greetings and turns into a queue and never answer with moves of its own.\n"
              "  To actually PLAY, this peer must also dial yours: add\n"
              "    --peer <your implementation's MCP url>   (and usually --role thief)\n"
              "  so both sides can push to each other — MCP pushes one way per session.")
        if await_peer:
            print("  If you are exposing this through a tunnel, rewrite the Host header or "
                  "fastmcp\n  will answer 421 to every request: Cloudflare "
                  "originRequest.httpHostHeader: "
                  f"127.0.0.1:{port} · ngrok --host-header=rewrite  (SPEC Appendix D).")

    if not peer_url:
        try:
            mcp.run(transport="http", host=host, port=port, show_banner=False)
        except KeyboardInterrupt:
            pass
        return 0

    # The server runs on a daemon thread and the game on this one. The four handlers only ever
    # touch a queue, so nothing about the game can block a tool call — two peers each awaiting the
    # other inside a handler is an instant deadlock.
    outcome: dict = {}

    def _serve():
        mcp.run(transport="http", host=host, port=port, show_banner=False)

    threading.Thread(target=_serve, daemon=True).start()

    from sparring.deadlines import MonotonicClock
    from sparring.netplay import play_series
    from sparring.transport.client import McpClient, PeerUnreachable, edge_answers

    # Give both sides a moment to bind before the first greeting; a connect that races the
    # opponent's startup looks exactly like an opponent that never arrived. Slept through the
    # clock module, which is the only place permitted to know what time it is (purity rule P-3).
    clock = MonotonicClock()
    clock.sleep(float(cfg.budgets.poll_interval) * 6)
    if await_peer:
        # The flag's promise, made real: poll the opponent's edge (the same "poll, don't dial"
        # contract the banner teaches — any HTTP answer, 406 included, means an edge is up)
        # for one handshake budget before the first greeting. Without this, two peers started
        # by hand lose the series to a startup race: a cold start takes longer than the grace
        # sleep above, the first connect is refused, and refused-once was fatal. The budget is
        # turn_timeout — the same budget SPAR-N09 gives an ARRIVED peer to greet, so "how long
        # will it wait for me" has one answer on both sides of the handshake.
        deadline = clock.now() + float(cfg.budgets.turn_timeout)
        if not edge_answers(peer_url, float(cfg.budgets.poll_interval) * 4):
            print(f"  awaiting the opponent's edge at {peer_url} "
                  f"(budget {cfg.budgets.turn_timeout:.0f}s — the handshake budget)")
            while clock.now() < deadline:
                if edge_answers(peer_url, float(cfg.budgets.poll_interval) * 4):
                    break
                clock.sleep(float(cfg.budgets.poll_interval))
    client = McpClient(peer_url, timeout=cfg.budgets.connect_timeout)

    try:
        result = play_series(cfg, client, inboxes, artifacts, sub_games=cfg.num_games)
    except PeerUnreachable as exc:
        print(f"  opponent unreachable: {exc}\n"
              f"  Run `python -m sparring.cli doctor --peer {peer_url}` — 502, 421 and a refused "
              f"connection\n  mean three different things and have three different fixes.")
        return 7

    print(f"\n  game_id  {result.game_id}\n  game_uid {result.game_uid}")
    for row in result.ledger:
        print(f"  {row['sub_game_number']:>3}  {row['role']:<7} {row['outcome']:<10} "
              f"steps {row['steps']:>3}  score {row['score']:>3}  "
              f"audit {'OK' if row['audit_ok'] else 'NOT VERIFIED'}")
    print(f"\n  {len(result.artifacts)} artifacts under {artifacts.resolve()}")
    print("  Nothing is owed for this run: sparring is not a game under App. E rules 32/35.")
    outcome["settled"] = result.settled
    return 0 if result.settled else 6
