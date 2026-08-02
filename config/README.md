# Configuration

Two files, two purposes (Rulebook Appendix B).

| File | Format | Scope | Signed |
| --- | --- | --- | --- |
| [`game.json`](game.json) | JSON | **Shared** — loaded byte-identically by both peers | **Yes** (`config_sha256`) |
| [`thief/game.toml`](thief/game.toml) | TOML | **Private** — local only, never crosses the network | No |

## Why the split

There is no referee. Each side runs its own copy of the game logic, so if the
two copies disagree on a single value the race dissolves into two irreconcilable
realities. `game.json` is the constitution both teams sign; it is exchanged and
hash-verified before the first move, and any mismatch means **refuse to play**.

`game.toml` holds what is nobody else's business: our port, the opponent's URL,
which brain class to load, how banter is generated, our team identity.

**Decision test:** *must the opponent agree to this value, or rely on it?*
Yes → `game.json`. No → `game.toml`.

JSON is chosen for the shared file because it is unambiguous across languages,
serialises canonically (sorted keys) so it hashes consistently, and suits
byte-identical exchange. TOML is chosen for the private file because it is
hand-edited and supports comments.

**Precedence:** where both define a key, **`game.json` wins**, so a private file
can never weaken a signed match condition.

## Parameter status

Every value in `game.json` carries a status from Appendix F, the single source
of truth for quantitative values:

- **fixed** — may not change at all. Deviation **disqualifies the team**.
  Scoring, pheromones, move set, agent count.
- **minimum** — may be negotiated *upward* only, never below the book default.
  Grid size, barrier quota, move ceiling, survival threshold, rate limits.
- **negotiable** — any mutually agreed value. Start positions, axis convention,
  map area, hint word cap, timeouts, token budget.

The contract is a **floor, not a ceiling**. Raising a minimum by agreement is
allowed and sometimes wise; lowering one is not.

## Per-match naming

The committed `game.json` is the **default template**. Each actual match gets
its own file named `config_<game_id>_g<NN>.json`, and Appendix F mandatory rule 4
requires it to be committed here so any match can be reconstructed exactly.
These files are deliberately **not** gitignored.

## Placeholders

`TBD` markers in `game.toml` (`group_name`, `group_id`, `members`) are filled by
issue #7. `agreed_between` in `game.json` is filled during pre-match negotiation.

## Before every match

1. Negotiate the contract with the opponent.
2. Exchange `config_sha256` — **refuse to play on any mismatch**.
3. Exchange the scent emission/decay model plus a numeric example, and hash-lock it.
4. Declare how many counted matches each team has already played.
5. Step-0: signed hardware declaration including the exact GitHub commit hash.
