"""PROBE S6 — the consensus-scope row stays the reference's 5-key form (no `tie`).

Finding (anrbj666, 2026-08-13; independently reproduced by imreeyal the same day): SPEC §6's
row list, the bundle generator's scope tuple, the shipped bundle hash and the bundle README all
signed a SIXTH row key, `tie` — attributed to the reference "verbatim" — while the reference's
`emit.py` deliberately writes `tie` into the document row and leaves it OUT of the `symmetric`
hash preimage. Every hash ever settled live is 5-key: the reference's own sample run, the
2026-08-03/04 validation window and counted series, every filed pairing artifact since. A team
calibrating on the bundle built a signer that fails settlement against every played
implementation, invisibly until a live report diff — on a counted series that is rule 35, zero
for both. Both roots landed 2026-08-04, the same day the filed bytes disproved them.

Four checks:
  1. REFERENCE PIN — the embedded trimmed scope of the course demo's own sample-run result
     (`docs/sample-run/result_segal-police-team-vs-segal-thief-team.json`, reference repo
     rmisegal/Game-P2P-Cop-Chase) hashes to the value that artifact ships. This pins the
     serialization AND the 5-key row to bytes the kit does not control.
  2. BUNDLE RECOMPUTE — the shipped bundle result's `mutual_agreement.sha256` equals the 5-key
     recompute from that file's own rows. Red while the 6-key bundle ships; green after.
  3. DISCRIMINATION — the 6-key (tie-bearing) recompute does NOT equal the shipped hash. A
     probe that cannot tell the two scopes apart pins nothing.
  4. PROSE TRIPWIRE — SPEC.md and the bundle README never spell the six-key row again; the
     erroneous carrier was prose, so prose is checked too.

Run:  python probe_s6_consensus_scope.py [kit-root]
Exit 0 = the scope holds the reference form; 1 = the finding is back.
"""

import json
import sys
from pathlib import Path

KIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))
import verify_vectors as ref  # noqa: E402

ROW_KEYS = ("sub_game_number", "roles", "result", "winner_group", "score")
AGG_KEYS = ("total_score", "sub_games_won", "ties", "winner_group", "series_tie")
SIX_KEY_SPELLINGS = ("winner_group, tie, score", '"winner_group", "tie", "score"')

# The course demo's sample-run result, trimmed to the consensus scope — quoted from the
# reference repo's docs/sample-run (public course material). The expected hash is the
# artifact's own shipped mutual_agreement value, computed by the lecturer's tooling.
REFERENCE_SCOPE = {
    "game_id": "segal-police-team-vs-segal-thief-team",
    "aggregate": {
        "total_score": {"segal-police-team": 20, "segal-thief-team": 5},
        "sub_games_won": {"segal-police-team": 1, "segal-thief-team": 0},
        "ties": 0,
        "winner_group": "segal-police-team",
        "series_tie": False,
    },
    "sub_games": [{
        "sub_game_number": 1,
        "roles": {"segal-thief-team": "thief", "segal-police-team": "police"},
        "result": "capture",
        "winner_group": "segal-police-team",
        "score": {"segal-thief-team": 5, "segal-police-team": 20},
    }],
}
REFERENCE_HASH = "31d678dadbd226dcb1ad87848386416702dcf0735746d7c812350ebc69cbdc81"

bad = 0


def check(label: str, ok: bool, detail: str) -> None:
    global bad
    bad += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {label} -> {detail}")


def scope_hash(doc: dict, row_keys: tuple) -> str:
    aggregate = {k: doc["final_result"][k] for k in AGG_KEYS}
    return ref.ref_report_consensus_signature({
        "game_id": doc["game_id"],
        "aggregate": aggregate,
        "sub_games": [{k: r[k] for k in row_keys} for r in doc["sub_games"]],
    })


# 1. The 5-key row + pinned serialization reproduce the reference's own artifact hash.
got = ref.ref_report_consensus_signature(REFERENCE_SCOPE)
check("S6-1: reference sample-run hash from the 5-key scope", got == REFERENCE_HASH,
      f"{got[:12]}… (want {REFERENCE_HASH[:12]}…)")

# 2 + 3. The shipped bundle settles 5-key and would NOT settle 6-key.
results = sorted((KIT / "examples" / "pairing-artifacts").glob("result_*.json"))
check("S6-2a: bundle has exactly one result artifact", len(results) == 1,
      f"{len(results)} found")
if results:
    doc = json.loads(results[0].read_text(encoding="utf-8"))
    shipped = doc["mutual_agreement"]["sha256"]
    five = scope_hash(doc, ROW_KEYS)
    check("S6-2b: shipped bundle hash == 5-key recompute", five == shipped,
          f"{five[:12]}… vs shipped {shipped[:12]}…")
    try:
        six = scope_hash(doc, ROW_KEYS[:4] + ("tie",) + ROW_KEYS[4:])
        check("S6-3: 6-key (tie) recompute differs from shipped", six != shipped,
              f"{six[:12]}…")
    except KeyError as exc:  # rows without a tie key cannot even form the bad scope
        check("S6-3: 6-key (tie) recompute differs from shipped", True,
              f"rows carry no {exc} key at all")

# 4. Neither prose carrier spells the six-key row again.
for name in ("SPEC.md", "examples/pairing-artifacts/README.md"):
    text = (KIT / name).read_text(encoding="utf-8")
    hits = [s for s in SIX_KEY_SPELLINGS if s in text]
    check(f"S6-4: {name} never lists tie inside the hash row", not hits,
          f"found {hits}" if hits else "clean")

print(f"\nVERDICT: {'SCOPE HOLDS THE REFERENCE FORM' if bad == 0 else f'{bad} CHECK(S) RED — the six-key scope is back'}")
sys.exit(1 if bad else 0)
