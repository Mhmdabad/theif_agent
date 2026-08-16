"""PROBE P5-1 — the two-directory join sweeps archived series and calls honest history
a rule-35 contradiction.

Finding (anrbj666 pass five, 2026-08-04):

  `main()` collects artifacts with `root.glob("*.json")` — NON-recursive (check_artifacts.py:293).
  `_check_many()` collects them with `Path(directory).rglob("*.json")` — RECURSIVE
  (check_artifacts.py:90, and again at :117 for the result comparison).

  So the join sees artifacts the single-directory check never would: every archived series a team
  keeps in a subdirectory. Those archives legitimately carry different game_ids, different scores
  and different winners — they are different matches — and the join reports them as

      FAIL  all results agree on final_result.total_score ... the contradictory-report shape
            rule 35 zeroes

  which is the single scariest verdict the tool can emit: it tells two honest teams that they are
  about to be zeroed, at the exact moment (pre-report) when the tool is designed to be believed.

  It is self-inflicted: the layout that triggers it is the one the kit's OWN playbook prescribes —
  PAIRING-PLAYBOOK stage 0 tells teams to "snapshot every settled series into its own committed
  archive folder" and "keep the live top level empty". A team that follows the kit's advice
  cannot run the kit's join.

  Verified against the real thing: pointing the join at the two repos of a team that had played
  five archived friendlies plus one counted series produced three game_ids, three contradictory
  total_scores and two different winner_groups — all honest history. With the archives excluded,
  both bundles pass individually and the join prints ALL SETS AGREE.

Suggested fix: the join should distinguish "two teams disagree about ONE match" (the rule-35
hazard it exists to catch) from "these trees contain SEVERAL matches" (an archive). Group by
game_id and join per match, or refuse with that wording — but do not print the rule-35 sentence
for artifacts that never claimed to describe the same game.

Run:  python probe_p5_join_sweeps_archives.py [path-to-kit-repo]
Builds its own synthetic layout in a temp dir; touches nothing in the repo.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else
           str(Path(__file__).resolve().parents[2]))  # P5-16: relative default
sys.path.insert(0, str(KIT))

import verify_vectors as ref                                    # noqa: E402

TERMS = {"board_size": 7, "smell_grid_size": 5, "decay_per_step": 0.1, "emit_intensity": 0.9,
         "min_center_intensity": 0.5, "max_steps": 35, "barriers_max": 14, "setting": "New York",
         "hint_max_words": 15, "axis_origin_corner": "top-left", "axis_start_index": 0,
         "thief_start": [3, 3], "cop_start": [0, 0], "num_games": 6}


def write_set(root: Path, a: str, b: str, score: dict, sub_games: int = 1) -> None:
    """One conformant single-sub-game artifact set for pairing (a, b)."""
    root.mkdir(parents=True, exist_ok=True)
    gid, guid = ref.ref_game_id(a, b), ref.ref_game_uid(TERMS, a, b)
    links = {"declaration": f"declaration_{gid}.json", "result": f"result_{gid}.json",
             "config": f"config_{gid}_g<NN>.json", "log": f"log_{gid}_g<NN>.json"}
    base = {"game_id": gid, "game_uid": guid, "links": links}
    files = {
        f"declaration_{gid}.json": {**base, "num_sub_games": sub_games,
                                    "groups": {"group_1": {"group_id": a},
                                               "group_2": {"group_id": b}}},
        f"config_{gid}_g01.json": {**base, "sub_game_number": 1, "terms": TERMS},
        f"log_{gid}_g01.json": {**base, "summary": {"sub_game_number": 1}, "records": []},
        f"result_{gid}.json": {**base, "num_sub_games": sub_games,
                               "groups": [{"group_id": a}, {"group_id": b}],
                               "sub_games": [{"sub_game_number": 1, "score": score}],
                               "final_result": {"total_score": score,
                                                "winner_group": max(score, key=score.get)}},
    }
    for name, doc in files.items():
        (root / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def run(*dirs: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(KIT / "tools" / "check_artifacts.py"),
                           *[str(d) for d in dirs]], capture_output=True, text=True)
    return proc.returncode, proc.stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Two teams' LIVE bundles for the same match: honest, agreeing, conformant.
        for side in ("ours", "theirs"):
            write_set(tmp / side, "team-aleph", "team-bet", {"team-aleph": 20, "team-bet": 5})

        code_clean, out_clean = run(tmp / "ours", tmp / "theirs")
        print(f"  join, no archives           -> exit {code_clean}: {out_clean.strip().splitlines()[-1]}")

        # Now do exactly what PAIRING-PLAYBOOK stage 0 says: keep past series as committed
        # archives in a subfolder. A different opponent, a different score — a DIFFERENT MATCH.
        write_set(tmp / "ours" / "archive" / "2026-07-25",
                  "team-aleph", "team-gimel", {"team-aleph": 5, "team-gimel": 20})

        code_arch, out_arch = run(tmp / "ours", tmp / "theirs")
        last = out_arch.strip().splitlines()[-1]
        print(f"  join, one archived series   -> exit {code_arch}: {last}")
        poisoned = "rule 35" in out_arch or code_arch != 0
        if poisoned:
            for line in out_arch.splitlines():
                if "FAIL" in line or "rule 35" in line:
                    print(f"      {line.strip()}")

        print()
        print("  the archived set is a DIFFERENT match (different opponent, different game_id).")
        print("  It never claimed to describe the same game, so 'the contradictory-report shape")
        print("  rule 35 zeroes' is a false alarm — emitted at the moment teams most believe it.")
        print()
        reproduced = code_clean == 0 and poisoned
        print("VERDICT: " + ("REPRODUCED — the join must not read archives as contradictions"
                             if reproduced else "join no longer poisoned by archives"))
        return 0 if not reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
