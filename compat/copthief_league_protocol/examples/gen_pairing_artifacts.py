"""Regenerate examples/pairing-artifacts/ — a full six-sub-game artifact bundle in the
counted-series format, with games that are actually PLAYABLE.

    python examples/gen_pairing_artifacts.py          # rewrites the bundle in place
    python tools/check_artifacts.py examples/pairing-artifacts

Deterministic and stdlib-only, like every generator in this kit: teams are synthetic
(team-aleph / team-bet), and every hash is computed by the reference constructions in
verify_vectors.py — nothing is hand-typed, so the bundle cannot drift from the
constructions it demonstrates. The aggregate and the league fields are DERIVED from the
sub-game rows (SPEC section 6: "derived, not declared"), never restated.

Every game here is legal under the book's physics and reaches its declared outcome:
the cop windows walk (0,0) to the thief at (3,3) in six orthogonal steps and capture;
the thief windows survive the full 35; sub-game 5 spends a step placing a barrier
instead of moving, so its capture lands one step later. An earlier revision of this
generator shipped one-step logs whose summaries declared `capture` and `survival` — a
row asserting a clean audit over a game that could not produce its own result. Found by
anrbj666's audit of anrbj666's own contribution, 2026-08-04.

WHAT THIS BUNDLE IS NOT
-----------------------
**The nonces here are derivable on purpose and MUST NOT be copied.** `nonce()` below is a
hash of a guessable tag, so the whole bundle regenerates byte-identically — which is what a
fixture needs and the exact opposite of what a game needs. A real nonce is unpredictable
(`secrets.token_hex(16)`); with a guessable one an opponent recovers your sealed move from
its commit before you reveal it, and the commit-reveal has no hiding property at all.

**The result file here is pretty-printed.** The report you EMAIL must be the compact
canonical bytes (SPEC section 2), never a re-serialization — see SPEC section 6.

**The league fields here are ARMED**, because this is the counted-series shape. A warm-up
must not copy them armed: an uncounted game that claims a counted record is a false
declaration under App. E rules 37-38 (PAIRING-PLAYBOOK stage 4d).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import verify_vectors as ref  # noqa: E402

OUT = Path(__file__).resolve().parent / "pairing-artifacts"

A, B = "team-aleph", "team-bet"  # sorted: A first -> A cops the odd sub-games
BOARD, COP_START, THIEF_START, MAX_STEPS = 7, (0, 0), (3, 3), 35
TERMS = {
    "board_size": BOARD, "smell_grid_size": 5, "decay_per_step": 0.1, "emit_intensity": 0.9,
    "min_center_intensity": 0.5, "max_steps": MAX_STEPS, "barriers_max": 14,
    "setting": "New York", "hint_max_words": 15, "axis_origin_corner": "top-left",
    "axis_start_index": 0, "thief_start": list(THIEF_START), "cop_start": list(COP_START),
    "num_games": 6,
}
GID = ref.ref_game_id(A, B)
GUID = ref.ref_game_uid(TERMS, A, B)
LINKS = {
    "declaration": f"declaration_{GID}.json", "config": f"config_{GID}_g<NN>.json",
    "log": f"log_{GID}_g<NN>.json", "result": f"result_{GID}.json",
    "github": {g: {"cop": f"https://github.com/{g}/cop", "thief": f"https://github.com/{g}/thief"}
               for g in (A, B)},
}
COMMITS = {A: {"cop": "a1ef0000" + "c0f" * 10 + "5c", "thief": "a1ef0001" + "7f1" * 10 + "3e"},
           B: {"cop": "b2e70000" + "abc" * 10 + "90", "thief": "b2e70001" + "de2" * 10 + "71"}}
HARDWARE = {
    A: {"os": "Windows 10", "cpu_type": "GenuineIntel x86_64", "cpu_cores": 24,
        "cpu_freq_mhz": 3418, "ram_gb": 32, "gpu_model": "Radeon RX 7900 XTX",
        "vram_gb": 24, "python": "3.13.13"},
    B: {"os": "Windows (10.0.19045)", "cpu_type": "AuthenticAMD x86_64", "cpu_cores": 24,
        "cpu_freq_mhz": 3693, "ram_gb": 31.9, "gpu_type": "RTX 3080 Ti",
        "gpu_cores_or_cuda": "cuda", "vram_gb": 12.0},
}
TZ = "Asia/Jerusalem"
T0 = datetime(2026, 8, 4, 1, 0, 0, tzinfo=timezone(timedelta(hours=3)))
LEAGUE = {"authority": "book App. E rule 52 — the one counted series of this pairing",
          "counted": True, "reason": "counted",
          "_synthetic": "example bundle: no game was played to produce these bytes"}


def nonce(tag: str) -> str:
    """DERIVABLE BY DESIGN — see the module docstring. Never ship this scheme."""
    return ref.canonical_hash({"nonce_tag": tag})[:32]


def sealed(payload: dict, tag: str) -> dict:
    n = nonce(tag)
    return {"payload": payload, "nonce": n, "commit": ref.ref_commit(payload, n)}


def state_str(pos: tuple[int, int], barriers: list[tuple[int, int]]) -> str:
    """The reference's self-only state encoding — note the space after each comma."""
    walls = "[" + ", ".join(f"[{r}, {c}]" for r, c in barriers) + "]"
    return f"grid={BOARD}x{BOARD};self=[{pos[0]}, {pos[1]}];barriers={walls}"


def cop_track(n: int) -> list[dict]:
    """The cop's legal walk from (0,0) onto the thief at (3,3): three souths, three easts.

    Sub-game 5 opens by PLACING A BARRIER instead of moving (the cop forgoes its move,
    book ch.3), so its capture lands at step 7 rather than step 6.
    """
    steps: list[dict] = []
    barriers: list[tuple[int, int]] = []
    pos = COP_START
    if n == 5:  # the barrier window: forgo the move, place at an orthogonal neighbour
        barriers = [(0, 1)]
        steps.append({"pos": pos, "move": "STAY", "verdict": "placed_barrier",
                      "barriers": list(barriers), "barrier_placed": [0, 1],
                      "hint": "Blocking the eastern alley before I start walking.",
                      "intent": "truth"})
    for move, delta in (("MOVE:S", (1, 0)),) * 3 + (("MOVE:E", (0, 1)),) * 3:
        pos = (pos[0] + delta[0], pos[1] + delta[1])
        steps.append({"pos": pos, "move": move, "verdict": "moved", "barriers": list(barriers),
                      "hint": "Working south through the avenues, closing the block.",
                      "intent": "truth"})
    steps[-1]["capture_claim"] = list(pos)          # the landing that ends it
    return steps


def thief_stay_track(n: int) -> list[dict]:
    """The thief the cop walks onto: it holds its ground and is caught."""
    length = len(cop_track(n))
    return [{"pos": THIEF_START, "move": "STAY", "verdict": "moved", "barriers": [],
             "hint": "Holding position, watching the avenue.", "intent": "truth"}
            for _ in range(length)]


def _cycle(start: tuple[int, int], ring: list[tuple[int, int]], count: int) -> list[dict]:
    out, pos = [], start
    moves = {(0, 1): "MOVE:E", (1, 0): "MOVE:S", (0, -1): "MOVE:W", (-1, 0): "MOVE:N"}
    for i in range(count):
        nxt = ring[i % len(ring)]
        delta = (nxt[0] - pos[0], nxt[1] - pos[1])
        out.append({"pos": nxt, "move": moves[delta], "verdict": "moved", "barriers": []})
        pos = nxt
    return out


def thief_survive_track() -> list[dict]:
    """35 legal steps that reach the survival threshold: a four-cell orbit."""
    ring = [(3, 4), (4, 4), (4, 3), (3, 3)]
    steps = _cycle(THIEF_START, ring, MAX_STEPS)
    for i, step in enumerate(steps, start=1):
        lying = i == 5           # one deliberate bluff — why `intent` exists at all
        step["intent"] = "lie" if lying else "truth"
        step["hint"] = ("אני בדרך צפונה, הרחק מכאן 🚕" if lying
                        else "Circling the same few blocks, staying loose.")
    steps[-1]["win_claim"] = {"type": "survival"}
    return steps


def cop_chase_track() -> list[dict]:
    """The cop that never closes: two steps in, then its own orbit two cells clear."""
    approach = [{"pos": (1, 0), "move": "MOVE:S", "verdict": "moved", "barriers": []},
                {"pos": (1, 1), "move": "MOVE:E", "verdict": "moved", "barriers": []}]
    steps = approach + _cycle((1, 1), [(1, 2), (2, 2), (2, 1), (1, 1)], MAX_STEPS - 2)
    for step in steps:
        step["intent"], step["hint"] = "truth", "Sweeping the north-west grid, no contact yet."
    return steps


def tracks(n: int) -> tuple[list[dict], list[dict], str, int]:
    """(team-aleph's steps, team-bet's steps, outcome, steps played) for sub-game n.

    Odd: aleph cops and captures. Even: aleph thieves and survives (first-sorted group
    cops the odd sub-games — PAIRING-PLAYBOOK stage 3).
    """
    if n % 2 == 1:
        ours, theirs = cop_track(n), thief_stay_track(n)
        return ours, theirs, "capture", len(ours)
    ours, theirs = thief_survive_track(), cop_chase_track()
    return ours, theirs, "survival", len(ours)


def record(step: dict, index: int, role: str, n: int, tag: str) -> dict:
    payload = {
        "step": index, "sub_game": n, "role": role,
        "state": state_str(step["pos"], step["barriers"]),
        "position": list(step["pos"]), "move": step["move"], "intent": step["intent"],
        "hint": step["hint"], "verdict": step["verdict"],
    }
    for extra in ("barrier_placed", "capture_claim", "win_claim"):
        if extra in step:
            payload[extra] = step[extra]
    return sealed(payload, tag)


def group_block(gid: str) -> dict:
    """A declaration group block; `signature` is sign-then-insert over the block's
    canonical form (the block hashed BEFORE its own signature key is added).

    The headline `github_commit` is the emitting repo's HEAD — a two-repo team emits one
    declaration per role repo, each carrying its own. The per-role, per-sub-game commits,
    which is what rule 53 actually binds, live in the result's rows.
    """
    block = {
        "group_id": gid, "group_name": gid,
        "members": [f"{gid}-member-1", f"{gid}-member-2"],
        "repos": LINKS["github"][gid],
        "mcp_servers": {"cop": f"https://cop.{gid}.example/mcp",
                        "thief": f"https://thief.{gid}.example/mcp"},
        "llm_model": "template",
        "hardware_spec": HARDWARE[gid],
        "hardware_spec_sha256": ref.canonical_hash(HARDWARE[gid]),
        "github_commit": COMMITS[gid]["cop"],   # this bundle is the COP repo's copy
        "counted_games_played": 0,              # PRIOR count: this series is not in it
        "code_version": "1.00",
    }
    block["signature"] = "sha256:" + ref.canonical_hash(block)
    return block


def sub_game_row(n: int) -> dict:
    odd = n % 2 == 1
    cop, thief = (A, B) if odd else (B, A)
    _, _, outcome, steps = tracks(n)
    score = {A: 20 if odd else 10, B: 5}         # App. F: capture 20/5, survival 5/10
    started = T0 + timedelta(seconds=10 * n)
    return {
        "sub_game_number": n,
        "roles": {A: "police" if odd else "thief", B: "thief" if odd else "police"},
        "started_at": started.isoformat(),
        "ended_at": (started + timedelta(seconds=9)).isoformat(),
        "result": outcome, "winner_group": A, "tie": False, "steps": steps,
        "github_commit": {A: COMMITS[A]["cop" if odd else "thief"],
                          B: COMMITS[B]["thief" if odd else "cop"]},
        "tokens": {A: 0, B: 0},
        "score": score,
        "log_files": {A: f"log_{GID}_g{n:02d}.json", B: f"log_{GID}_g{n:02d}.json"},
        "audit": {"log_verified": True, "tampered": False},
    }


def log_doc(n: int) -> dict:
    odd = n % 2 == 1
    my_role, their_role = ("police", "thief") if odd else ("thief", "police")
    ours, theirs, outcome, steps = tracks(n)
    my_commit = COMMITS[A]["cop" if odd else "thief"]
    their_commit = COMMITS[B]["thief" if odd else "cop"]
    # step-0, in BOTH conformant spellings: ours slim + declaration_ref, theirs the
    # reference's inline system_spec. A reader must accept either (SPEC section 7.2).
    records = [sealed({"step": 0, "type": "step_zero", "declaration_ref": LINKS["declaration"],
                       "group_id": A, "role": my_role, "sub_game_number": n,
                       "github_commit": my_commit}, f"g{n}-own-step0")]
    records += [record(s, i, my_role, n, f"g{n}-own-{i}") for i, s in enumerate(ours, start=1)]
    opponent = [sealed({"step": 0, "type": "system_spec", "spec": HARDWARE[B], "model": "none",
                        "code_version": "1.00", "group_name": B, "sub_game_number": n,
                        "github_commit": their_commit, "num_games_declared": 6},
                       f"g{n}-their-step0")]
    opponent += [record(s, i, their_role, n, f"g{n}-their-{i}")
                 for i, s in enumerate(theirs, start=1)]
    return {
        "_schema": "Per-sub-game log: every step sealed commit-reveal, both step-0 spellings "
                   "(ours slim + declaration_ref, theirs the reference's inline system_spec). "
                   "Static team metadata is NOT repeated here - it lives in the declaration; "
                   "join by game_uid. The nonces are DERIVABLE BY DESIGN (see the generator): "
                   "a real game needs unpredictable ones or the commitment hides nothing.",
        "schema_version": "1.1", "game_id": GID, "game_uid": GUID, "links": LINKS,
        "league": LEAGUE, "sub_game_number": n,
        "summary": {
            "sub_game_number": n, "group_id": A, "role": my_role, "opponent_group_id": B,
            "result": outcome, "winner_group": A, "timezone": TZ, "steps": steps,
            "audit": {"passed": True, "skipped": False,
                      "verified_steps": len(opponent), "failed_steps": []},
        },
        "records": records, "opponent_records": opponent,
    }


def build() -> dict[str, dict]:
    rows = [sub_game_row(n) for n in range(1, 7)]
    # DERIVED, never declared (SPEC section 6) - the aggregate is computed from the rows
    # exactly once and reused, so the consensus preimage and final_result cannot diverge.
    totals = {g: sum(r["score"][g] for r in rows) for g in (A, B)}
    won = {g: sum(1 for r in rows if r["winner_group"] == g) for g in (A, B)}
    ties = sum(1 for r in rows if r["tie"])
    series_tie = totals[A] == totals[B]
    winner = None if series_tie else max(totals, key=totals.get)
    aggregate = {"total_score": totals, "sub_games_won": won, "ties": ties,
                 "winner_group": winner, "series_tie": series_tie}
    # SPEC section 6's trimmed scope — the reference's 5-key symmetric row, verbatim. An
    # earlier revision signed a sixth key ("tie") that no played implementation signs; the
    # tuple is pinned to the reference's own artifact by probe_s6_consensus_scope.py.
    consensus_scope = {
        "game_id": GID, "aggregate": aggregate,
        "sub_games": [{k: r[k] for k in
                       ("sub_game_number", "roles", "result", "winner_group", "score")}
                      for r in rows],
    }
    declaration = {
        "_schema": "Pre-game declaration: the single home for everything fixed across the "
                   "series - identity, members, repos, MCP endpoints, BOTH teams' hardware "
                   "specs, LLM model, token cap (book ch5 step-0; section 9.3.3's template "
                   "list). No end time: nothing here is known only after the games.",
        "schema_version": "1.1", "declaration_type": "pre_game_declaration",
        "report_type": "declaration", "league": LEAGUE,
        "game_id": GID, "game_uid": GUID, "links": LINKS, "timezone": TZ,
        "game_started_at": T0.isoformat(),
        "num_sub_games": 6, "max_tokens_per_game": 200000,
        "groups": {"group_1": group_block(A), "group_2": group_block(B)},
    }
    result = {
        "_schema": "Final series result - the emailed binding report (book section 9.3.3). "
                   "EMAIL THE COMPACT CANONICAL BYTES, not this pretty-print (SPEC section 2). "
                   "The league fields below are ARMED because this is a counted series; a "
                   "warm-up that copies them armed is a false declaration (App. E rules 37-38).",
        "schema_version": "1.1", "report_type": "final_game_result", "league": LEAGUE,
        "game_id": GID, "game_uid": GUID, "links": LINKS, "timezone": TZ,
        "groups": [A, B], "num_sub_games": 6, "sub_games": rows,
        "final_result": {
            **aggregate,
            "tokens_total_series": {g: sum(r["tokens"][g] for r in rows) for g in (A, B)},
            "games_played_including_this": {g: 1 for g in (A, B)},
            "first_meeting_between_groups": True,
            "diversity_reward_applied": {g: g == winner for g in (A, B)},
        },
        "mutual_agreement": {"sha256": ref.ref_report_consensus_signature(consensus_scope),
                             "confirmed": True},
    }
    files: dict[str, dict] = {f"declaration_{GID}.json": declaration,
                              f"result_{GID}.json": result}
    for n in range(1, 7):
        files[f"config_{GID}_g{n:02d}.json"] = {
            "_schema": "Per-sub-game config artifact: the flat 14-key terms inline, which is "
                       "what lets tools/check_artifacts.py RE-DERIVE the game_uid rather than "
                       "merely check it is consistent (WARNINGS section 2). `config_sha256` is "
                       "the canonical hash of those terms; the pre-game AGREEMENT SIGNATURE is "
                       "a different construction (it binds a nonce, SPEC section 4) and rides "
                       "the wire, not this artifact.",
            "schema_version": "1.1", "game_id": GID, "game_uid": GUID, "links": LINKS,
            "league": LEAGUE, "sub_game_number": n, "terms": TERMS,
            # config_sha256 — the REFERENCE's key name, which the played artifacts and the
            # sparring peer both use. An earlier revision said `terms_sha256`: same hash,
            # different key, and a third team could not know which its opponent reads
            # (anrbj666's P5-14; converged here).
            "config_sha256": ref.canonical_hash(TERMS),
        }
        files[f"log_{GID}_g{n:02d}.json"] = log_doc(n)
    return files


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bundle = build()
    for name, doc in sorted(bundle.items()):
        (OUT / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        print(f"wrote {name}")
    print(f"\n{len(bundle)} artifacts -> {OUT}")
    print("verify: python tools/check_artifacts.py examples/pairing-artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
