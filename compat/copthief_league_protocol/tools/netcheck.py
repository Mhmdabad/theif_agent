"""Probe a peer URL, and prove your OWN receiving path — stdlib only, no deps.

    python tools/netcheck.py https://peer.example.com/mcp
    python tools/netcheck.py https://peer.example.com/mcp --tool-call
    python tools/netcheck.py --loopback 8931 https://cop.example.com https://thief.example.com

Two jobs, and the second is the one teams skip.

**Probing the opponent** tells you which of five things is true, because "it doesn't work" has
five very different fixes. In particular `502` and `406` are not degrees of the same problem:
one means nothing is listening behind the edge, the other means a peer is listening and is
correctly refusing a browser-shaped request.

**Proving your own path** is the check a bare status probe cannot do for you. A tunnel connector
launched with mangled arguments and *no ingress rules at all* answers `502` forever — exactly
what a healthy-but-idle tunnel looks like from outside. Watching for `502` therefore cannot tell
"my peer hasn't started yet" from "my tunnel is broken and no peer will ever be reachable". The
only proof is a loopback: bind a throwaway listener on the series port, fetch your OWN public
hostname, and require *your listener's own answer* back through the edge. That exercises tunnel,
ingress rules and host-header rewrite in one shot. This script demands the answer carry a nonce
it generated, so another process answering on that port cannot be mistaken for success.

Exit codes:  0 = as expected · 1 = a probe failed · 2 = usage · 3 = the loopback proof failed
"""

from __future__ import annotations

import argparse
import http.client
import http.server
import json
import secrets
import socket
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

# What each status means for an MCP streamable-HTTP peer behind a tunnel.
VERDICTS = {
    406: ("PEER LISTENING",
          "an MCP streamable-HTTP server is behind this URL and correctly refused a bare GET "
          "(it wants Accept: application/json, text/event-stream). This is the state to poll "
          "for before a scheduled start — not a 200."),
    502: ("EDGE UP, NOTHING BEHIND IT",
          "the tunnel/proxy answered but found no origin. Either the peer has not started, or "
          "the connector is running with no ingress rules — those look identical from here. "
          "Run --loopback on your own hostnames to tell them apart."),
    421: ("HOST HEADER NOT REWRITTEN",
          "the server's DNS-rebinding guard rejected a Host that is not its bind address, which "
          "is every request arriving through a tunnel. Fix at the tunnel, no code change: "
          "Cloudflare named tunnel -> originRequest.httpHostHeader: 127.0.0.1:<port>; "
          "ngrok -> --host-header=rewrite. (SPEC Appendix D, issue #4.)"),
    404: ("WRONG PATH",
          "something is serving here, but not at this path. MCP peers usually mount at /mcp."),
    530: ("TUNNEL HOSTNAME NOT ROUTED",
          "the edge does not know this hostname — the DNS record or the tunnel route is missing."),
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects — classifying THIS url is the whole job.

    The default opener follows a 30x silently, so a redirector in front of a healthy peer used
    to classify as `PEER LISTENING` **attributed to the wrong URL** — and real tool calls there
    still fail, because urllib turns a redirected POST into a GET (anrbj666's E5). A redirect
    is now its own loud verdict.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N803
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def classify(url: str, timeout: float) -> tuple[str, str, str]:
    """Return (label, status_or_error, explanation) for a bare GET."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "copthief-netcheck/1"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        if 300 <= code < 400:
            return ("REDIRECT", str(code),
                    f"this URL answers with a redirect to {exc.headers.get('Location')!r} — it "
                    f"is a forwarder, not the peer. A redirected POST becomes a GET, so tool "
                    f"calls through it fail even though a probe that follows redirects would "
                    f"call it healthy. Point at the real endpoint.")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
            return ("TIMEOUT", "-", f"no answer within {timeout:g}s — a hung edge, a firewall "
                                    f"dropping packets, or a hostname that resolves nowhere.")
        return ("UNREACHABLE", "-", f"{reason} — nothing accepted a connection. Check the URL, "
                                    f"the tunnel process, and DNS.")
    except (http.client.HTTPException, OSError) as exc:
        return ("UNREACHABLE", "-", str(exc))
    label, why = VERDICTS.get(code, (
        "ANSWERED",
        "this URL answered a bare GET with a normal status. For an MCP peer that is unusual — "
        "406 is the healthy answer — so check you are pointing at the right path."))
    return (label, str(code), why)


def tool_call(url: str, timeout: float) -> tuple[bool, str]:
    """Ask the peer to `initialize` over MCP streamable-HTTP.

    The pre-match probe worth running: "does your public URL answer a tool call?" catches the
    421 host-header trap in seconds, which a status probe alone can leave you guessing about.
    """
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "copthief-netcheck", "version": "1"}},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(4096).decode("utf-8", "replace")
        return ("protocolVersion" in text or "result" in text,
                f"{resp.status} — {text[:160].strip()}")
    except urllib.error.HTTPError as exc:
        detail = exc.read(512).decode("utf-8", "replace").strip()
        return False, f"{exc.code} — {detail[:160]}"
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        return False, str(exc)


class _Echo(http.server.BaseHTTPRequestHandler):
    nonce = ""

    def do_GET(self):  # noqa: N802  (stdlib naming)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(self.nonce.encode())

    def log_message(self, *_args):
        pass  # the probe reports; the listener stays quiet


class _Server(http.server.ThreadingHTTPServer):
    # http.server sets allow_reuse_address = 1, and on Windows that lets a second process bind a
    # port another process is already listening on — both binds succeed and nobody is told. The
    # port-occupied check below therefore cannot be a trial bind; this only stops us from making
    # it worse.
    allow_reuse_address = False


def _port_is_held(port: int, timeout: float = 0.5) -> bool:
    """Is something already listening on the series port?

    A *connect* probe, not a trial bind. Binding to test would race the real server for the same
    address, and on Windows two binds can both succeed — which would make this check quietly
    useless on the platform most likely to be running the peer.
    """
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def loopback(port: int, hostnames: list[str], timeout: float) -> int:
    """Bind a throwaway listener on `port` and demand its own answer back through each edge."""
    nonce = secrets.token_hex(8)
    _Echo.nonce = nonce
    held = _port_is_held(port)
    try:
        server = None if held else _Server(("127.0.0.1", port), _Echo)
    except OSError as exc:
        server, held = None, True
        print(f"  (bind also failed: {exc})")
    if server is None:
        print(f"  FAIL  something is already listening on 127.0.0.1:{port}")
        print("        Do not start a series against this. If it is an orphaned peer from an\n"
              "        earlier attempt it will happily answer a sub-game your real peer was meant\n"
              "        to play — the real one starves behind it and reports a timeout it did not\n"
              "        cause, so one game gets sealed under two different indices and nothing\n"
              "        anywhere notices. Killing a shell does not kill what it spawned.")
        return 3
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  listener up on 127.0.0.1:{port}, nonce {nonce}")

    failed = 0
    try:
        for host in hostnames:
            url = host if "://" in host else f"https://{host}"
            try:
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    got = resp.read(256).decode("utf-8", "replace").strip()
                    code = resp.status
            except urllib.error.HTTPError as exc:
                code, got = exc.code, ""
            except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
                print(f"  FAIL  {url} — {exc}")
                failed += 1
                continue
            if got == nonce:
                print(f"  PASS  {url} -> {code}, our own nonce came back through the edge")
            elif code >= 500:
                print(f"  FAIL  {url} -> {code}. Your receiving path is broken: the edge is up but "
                      f"nothing\n        reaches your port. A connector with mangled arguments and "
                      f"no ingress answers\n        exactly this, forever. Check the tunnel's "
                      f"config path is quoted if it has spaces.")
                failed += 1
            else:
                print(f"  FAIL  {url} -> {code}, but the body was not our nonce (got {got[:40]!r}). "
                      f"Something\n        else is answering on this hostname — do not start a "
                      f"series against it.")
                failed += 1
    finally:
        server.shutdown()
        server.server_close()

    if failed:
        print(f"\n{failed} EDGE(S) NOT PROVEN — fix before naming a start time")
        return 3
    print("\nOWN RECEIVING PATH PROVEN end-to-end (tunnel + ingress + host header)")
    print("Now free the port before your real peer binds it.")
    return 0


def _selftest() -> int:
    """Stand up local servers answering each interesting status, and check the verdicts.

    Runs entirely on loopback with no network, so CI can prove the classifications and the
    loopback proof still work — including that an imposter answering 200 is rejected.
    """
    def free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def serve(code: int, body: bytes = b"") -> int:
        port = free_port()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body)
            do_POST = do_GET

            def log_message(self, *_a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return port

    bad = 0

    def expect(label: str, got, want) -> None:
        nonlocal bad
        ok = got in want if isinstance(want, tuple) else got == want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}{'' if ok else f'  got {got!r}, want {want!r}'}")

    def quietly(fn, *a):
        """Run a probe with its own diagnostics suppressed.

        The negative cases below are *meant* to print failure text; letting it through would make
        a passing self-test look like a failing one.
        """
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*a)

    for code, want in [(406, "PEER LISTENING"), (502, "EDGE UP, NOTHING BEHIND IT"),
                       (421, "HOST HEADER NOT REWRITTEN"), (404, "WRONG PATH")]:
        label, _, _ = classify(f"http://127.0.0.1:{serve(code)}/mcp", 5.0)
        expect(f"{code} classifies as {want}", label, want)

    # A redirector in front of a healthy peer must be its own verdict, never followed into a
    # false PEER LISTENING attributed to the wrong URL (anrbj666's E5).
    behind = serve(406)
    port = free_port()

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{behind}/mcp")
            self.end_headers()
        do_POST = do_GET

        def log_message(self, *_a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Redirector)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    expect("a 302 in front of a healthy peer classifies as REDIRECT, not PEER LISTENING",
           classify(f"http://127.0.0.1:{port}/mcp", 5.0)[0], "REDIRECT")
    # Either verdict is correct here: a closed loopback port refuses on most platforms and
    # silently drops on some. The property that matters is that it is never mistaken for a peer.
    expect("a closed port is not mistaken for a listening peer",
           classify(f"http://127.0.0.1:{free_port()}/mcp", 2.0)[0], ("UNREACHABLE", "TIMEOUT"))

    port = free_port()
    expect("loopback proves a live listener through its own edge",
           quietly(loopback, port, [f"http://127.0.0.1:{port}/"], 5.0), 0)
    expect("loopback rejects an imposter answering 200 without the nonce",
           quietly(loopback, free_port(),
                   [f"http://127.0.0.1:{serve(200, b'not-the-nonce')}/"], 5.0), 3)
    expect("loopback fails on a 502 edge with nothing behind it",
           quietly(loopback, free_port(), [f"http://127.0.0.1:{serve(502)}/"], 5.0), 3)
    expect("loopback refuses to start when the port is already held",
           quietly(loopback, serve(200), ["http://127.0.0.1:1/"], 2.0), 3)

    print(f"\n{'SELFTEST PASSES' if bad == 0 else f'{bad} SELFTEST FAILURE(S)'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="peer URL(s) to probe")
    ap.add_argument("--selftest", action="store_true",
                    help="check the classifications and the loopback proof on loopback only (CI)")
    ap.add_argument("--tool-call", action="store_true",
                    help="also POST an MCP `initialize` — the probe that catches 421 in seconds")
    ap.add_argument("--loopback", metavar="PORT", type=int,
                    help="prove YOUR path: bind this port and fetch the hostnames given as URLs")
    ap.add_argument("--timeout", type=float, default=10.0, help="seconds per request (default 10)")
    ap.add_argument("--expect", type=int, metavar="CODE",
                    help="exit non-zero unless every probe returns this status (e.g. --expect 406)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.urls:
        ap.print_usage(sys.stderr)
        print("give at least one URL", file=sys.stderr)
        return 2

    if args.loopback is not None:
        print(f"loopback proof through {len(args.urls)} edge(s)")
        return loopback(args.loopback, args.urls, args.timeout)

    bad = 0
    for url in args.urls:
        if not urlparse(url).netloc:
            print(f"  FAIL  {url!r} is not a URL")
            bad += 1
            continue
        label, code, why = classify(url, args.timeout)
        print(f"  {url}\n    {code:>5}  {label}\n           {why}")
        if args.expect is not None and code != str(args.expect):
            bad += 1
        elif args.expect is None and label in ("UNREACHABLE", "TIMEOUT"):
            bad += 1
        if args.tool_call:
            ok, detail = tool_call(url, args.timeout)
            print(f"    tool call: {'ANSWERED' if ok else 'NO'}  {detail}")
            if not ok:
                bad += 1

    print(f"\n{'ALL PROBES AS EXPECTED' if bad == 0 else f'{bad} PROBE(S) NOT AS EXPECTED'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
