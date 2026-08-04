# Going public — putting a tunnel in front of the MCP server

**Stage 5** · Rulebook Ch. 2.4 · Spec: [PRD-5](prd/PRD-5-tunneling.md)

Running on `localhost` is permitted **only during early coding**. For league
play the rulebook requires each team to expose its FastMCP server to the public
internet through a tunnelling tool such as **ngrok** or **Localtonet** — and
*"FastMCP over a public URL, not just localhost"* is an explicit line on the
final pre-submission checklist.

## Why a tunnel at all

This machine sits behind a firewall and behind NAT, so nothing on the internet
can route to it. The tunnel opens an outbound connection to the vendor's edge
and publishes a public URL that forwards back down it — NAT traversal, the same
fundamental peer-to-peer problem that STUN exists to solve.

The practical consequence: the opponent, anywhere in the world, reaches our
server through that URL, and **that URL is the entire description of us**. They
know nothing else.

## No code change is needed

`infra/mcp_server.py` binds `0.0.0.0` and has since Stage 2, deliberately:

```python
BIND_HOST = "0.0.0.0"  # a tunnel must be able to reach us
```

Binding `127.0.0.1` would make the server unreachable *through* the tunnel too,
and that failure would surface at first contact with another team rather than
here.

## Starting a tunnel

The agent's port is `my_port` in `config/thief/game.toml` (default `8802`).

### ngrok

```bash
ngrok http 8802
```

The agent prints a forwarding line like `https://a1b2c3d4.ngrok-free.app`. The
MCP endpoint is that address plus `/mcp` — which `infra/tunnel.py` appends for
you, so the base address is what you copy.

While `ngrok` runs it also serves a local inspection API on
`http://127.0.0.1:4040/api/tunnels`. `tunnel.discover()` reads it automatically,
so with ngrok running **nothing needs to be set by hand**.

### Localtonet

Localtonet has no equivalent local API, so its URL is supplied explicitly:

```bash
export PUBLIC_URL=https://your-subdomain.localtonet.com
```

`PUBLIC_URL` is checked before ngrok discovery and works for any vendor. If it
is set to something an opponent could not reach — a loopback or LAN address —
startup fails loudly rather than falling back to localhost. Someone who set the
variable meant to expose this peer; silently ignoring a typo is the outcome they
would notice last.

## Secrets stay out of the repository

An ngrok authtoken is a credential. Configure it with

```bash
ngrok config add-authtoken <token>
```

which writes to `~/.config/ngrok/ngrok.yml` — **outside this repository**. Never
paste a token into `config/`, a workflow file, or a commit message. Appendix C
makes "nothing sensitive anywhere in Git history" a submission gate, and a
leaked credential in git history is permanent.

## The free tier rotates the URL

Free ngrok and Localtonet accounts issue a **new URL every restart**. A
six-sub-game series can outlive one tunnel, so the runtime must pick up a
changed address by re-handshake rather than by restarting the series — that is
issue #65, and the reason it exists.

Keeping one tunnel process alive for the whole series avoids the problem
entirely, which is the recommended way to run a league match.

## Verifying before the match

Ask a machine that is not this one — a phone off wifi is enough:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://a1b2c3d4.ngrok-free.app/mcp
```

Anything that answers proves NAT traversal works. A hang or a connection error
means the opponent would hang too, and **a technical loss scores zero for both
sides** — so a tunnel verified late costs a match that was already won on the
board.
