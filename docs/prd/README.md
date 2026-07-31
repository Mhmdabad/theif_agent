# PRD Index — THIEF Agent

Seven layered Product Requirements Documents, one per development stage, as
recommended in Rulebook Ch. 10. **Build them in order.** Each stage ends in a
system that works end-to-end, even if narrow in scope, so at any moment the space
of possible faults is confined to the newest layer.

| # | PRD | Builds | Rulebook |
|---|---|---|---|
| 1 | [Base Logic](PRD-1-base-logic.md) | Grid, movement rules, barrier quota, capture detection | Ch. 3 |
| 2 | [FastMCP Infrastructure](PRD-2-mcp-infrastructure.md) | FastMCP servers and geometric tools over localhost | Ch. 2 |
| 3 | [Blind Strategy](PRD-3-blind-strategy.md) | Initial strategy module: heuristic, LLM policy, or Bellman/Q-Learning (optional) | Ch. 6 |
| 4 | [Language & Scent](PRD-4-language-and-scent.md) | Natural language, scent/decay equations, LLM deception | Ch. 4, 6 |
| 5 | [Cloud Exposure](PRD-5-tunneling.md) | Public addresses and tunneling (Localtonet/ngrok) | Ch. 2 |
| 6 | [Cryptography](PRD-6-crypto-commit-reveal.md) | Commit-Reveal, nonce generator, Step-0 hardware declarations | Ch. 5 |
| 7 | [Reporting & Visualization](PRD-7-reporting-and-gui.md) | Gmail API over OAuth 2.0, GUI, Replay App | Ch. 9, 7, App. A |

## Do not skip ahead

Do not touch cryptography or the cloud before base logic and the MCP layer work
end-to-end over localhost. Skipping the foundations does not save time — it can
double it: a fault in an upper layer hides behind instability in the layer beneath
it, and hours are lost investigating a cause that does not exist.

## Related documents

- [../PLAN.md](../PLAN.md) — overall plan, architecture, config, risks
- [../TODO.md](../TODO.md) — checkable task list with milestone gates
- Companion repo: **COP agent** — [police_agent](https://github.com/Mhmdabad/police_agent)
