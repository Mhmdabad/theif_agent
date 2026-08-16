"""Reaching the opponent over MCP, and telling a stranger what is wrong when we cannot.

One of two modules permitted to open outbound networking (``guards/no_mail.py`` rule NM-5). The
whole fastmcp surface lives here and in ``server.py`` — about a hundred lines between them — so a
breaking release upstream is a two-file fix and never touches the rules.

``diagnose`` is the pre-match probe worth running before you agree a start time. The status codes
are not degrees of one problem, and confusing them costs windows:

* ``406`` — an MCP peer is listening and correctly refused a browser-shaped GET. **This is ready.**
* ``502`` — the edge answered but found no origin: either their peer has not started, or their
  tunnel has no ingress. Indistinguishable from outside, which is why each side must prove its
  *own* path (``tools/netcheck.py --loopback``).
* ``421`` — a DNS-rebinding guard rejected the Host header, which is every request through a
  tunnel. Fixed at the tunnel, not in code (SPEC Appendix D).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TOOLS = ("negotiate", "receive_turn", "submit_audit", "receive_control")


class PeerUnreachable(Exception):
    pass


def _post(url: str, body: dict, timeout: float) -> tuple[int, str]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2048).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise PeerUnreachable(str(exc)) from exc


class McpClient:
    """The four calls, with the argument-name asymmetry the reference defines.

    ``submit_audit`` takes ``payload``; the other three take ``message``. It looks like an
    inconsistency and it is load-bearing: a peer that sends ``message`` to ``submit_audit`` gets a
    schema error at the one moment both sides are trying to agree on a result.

    MCP over streamable HTTP is **session-oriented**: a bare `tools/call` without an established
    session is answered ``400 Missing session ID``, which reads like an unreachable peer and is
    not one. So the session is held open here rather than re-established per call, on a private
    event loop this class owns — the game loop stays synchronous, which is what keeps the rules,
    the state machine and the tests free of async.
    """

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        self.url = url
        self.timeout = timeout
        self._loop = None
        self._client = None
        self._entered = False

    def _ensure_session(self) -> None:
        import asyncio
        import threading

        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            threading.Thread(target=self._loop.run_forever, daemon=True).start()
        if self._entered:
            return

        from fastmcp import Client

        self._client = Client(self.url)
        try:
            self._await(self._client.__aenter__())
            self._entered = True
        except Exception as exc:                       # noqa: BLE001 — surfaced as one diagnosis
            self._client = None
            raise PeerUnreachable(f"could not open an MCP session at {self.url}: {exc}") from exc

    def _await(self, coro):
        import asyncio

        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(self.timeout)

    def _call(self, tool: str, argument: dict) -> dict:
        # A held session can die legitimately mid-series: an opponent that plays each sub-game
        # in its OWN process (the rolling-window topology — how both real league teams drive a
        # series) tears the session down at every sub-game boundary. That is an ordinary
        # boundary event, not an unreachable peer, so a dead session is re-established once
        # before this call gives up. Found by the 2026-08-04 dogfood run, where the unpatched
        # client aborted a whole series at the first boundary with "Session terminated".
        arg_name = "payload" if tool == "submit_audit" else "message"
        last: Exception | None = None
        for attempt in (0, 1):
            self._ensure_session()
            try:
                self._await(self._client.call_tool(tool, {arg_name: argument}))
                return {"ok": True}
            except Exception as exc:                   # noqa: BLE001
                last = exc
                self._entered = False
                self._client = None
        raise PeerUnreachable(f"{tool} -> {type(last).__name__}: {last}") from last

    def close(self) -> None:
        if self._entered and self._client is not None:
            try:
                self._await(self._client.__aexit__(None, None, None))
            except Exception:                          # noqa: BLE001 — closing is best-effort
                pass
        self._entered = False

    def negotiate(self, message: dict) -> dict:
        return self._call("negotiate", message)

    def receive_turn(self, message: dict) -> dict:
        return self._call("receive_turn", message)

    def submit_audit(self, payload: dict) -> dict:
        return self._call("submit_audit", payload)

    def receive_control(self, message: dict) -> dict:
        return self._call("receive_control", message)


def _get(url: str, timeout: float) -> int:
    """A browser-shaped GET — no Accept: text/event-stream — the request 406 exists to refuse."""
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "sparring-doctor/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError) as exc:
        raise PeerUnreachable(str(exc)) from exc


def edge_answers(url: str, timeout: float = 2.0) -> bool:
    """True once ANYTHING HTTP answers at the URL — 406 is the healthy answer, but any status
    proves an edge is up, which is all `--await-peer` needs to know before the first greeting.
    A refused connection (nothing bound yet) is the one state that returns False."""
    try:
        _get(url, timeout)
        return True
    except PeerUnreachable:
        return False


def classify_probe(get_status: int | None, post_status: int | None,
                   post_text: str) -> tuple[int, str]:
    """(exit code, message) from the two probes' raw results. Pure, so it is testable.

    An earlier revision sent ONLY the MCP initialize POST — whose Accept header already
    includes `text/event-stream`, so a healthy FastMCP peer answered 200 and the 406 branch,
    the very state the banner teaches you to poll for, was unreachable by the probe's own
    request (anrbj666's E6). The browser-shaped GET is what actually elicits 406.
    """
    if 421 in (get_status, post_status):
        return 7, ("HOST HEADER NOT REWRITTEN (421). Their MCP server's DNS-rebinding guard "
                   "rejects\n  any Host that is not its bind address — which is every request "
                   "through a tunnel.\n  Fix at the tunnel, no code change:\n"
                   "    Cloudflare  originRequest.httpHostHeader: 127.0.0.1:<port>\n"
                   "    ngrok       --host-header=rewrite\n"
                   "  (SPEC Appendix D, kit issue #4.)")
    if 502 in (get_status, post_status):
        return 7, ("EDGE UP, NOTHING BEHIND IT (502). Their peer has not started, or their "
                   "connector\n  is running with no ingress. Those look identical from here — "
                   "ask them to run\n  `python tools/netcheck.py --loopback <port> <their "
                   "hostnames>`.")
    healthy_get = get_status == 406
    answered_mcp = bool(post_text) and ("protocolVersion" in post_text or "result" in post_text)
    if healthy_get and answered_mcp:
        return 0, ("PEER LISTENING — 406 to a browser-shaped GET (the state to poll for before "
                   "a scheduled start)\n  AND a real answer to an MCP initialize.\n"
                   f"  tools this peer must expose: {', '.join(TOOLS)}\n"
                   "  note submit_audit takes `payload`; the other three take `message`.")
    if healthy_get:
        return 7, ("406 to a GET but NO valid answer to an MCP initialize "
                   f"(status {post_status}) — something MCP-shaped is listening and not "
                   "speaking. Check the path and the server logs.")
    if answered_mcp:
        return 0, (f"answered an MCP initialize (GET gave {get_status}, not the usual 406 — "
                   "an unusual but serving stack).\n"
                   f"  tools this peer must expose: {', '.join(TOOLS)}")
    return 7, (f"neither probe got a peer-shaped answer (GET {get_status}, "
               f"POST {post_status}). Check you are pointing at the right path — MCP peers "
               "usually mount at /mcp.")


def diagnose(url: str, timeout: float = 10.0) -> int:
    """Classify a peer URL and say what to do about it. Returns a CLI exit code."""
    print(f"probing {url}")
    try:
        get_status = _get(url, timeout)
        post_status, post_text = _post(
            url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "sparring-doctor", "version": "1"}}}, timeout)
    except PeerUnreachable as exc:
        print(f"  UNREACHABLE — {exc}\n"
              f"  Nothing accepted a connection. Check the URL, the tunnel process, and DNS.")
        return 7
    code, message = classify_probe(get_status, post_status, post_text)
    print(f"  {message}")
    return code
