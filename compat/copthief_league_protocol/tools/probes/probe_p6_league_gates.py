"""Probe: the pass-six findings stay fixed (anrbj666, 2026-08-05 — P6-1..P6-8).

Ten cases against the REAL checker, each a finding that was live at `4597613`: the league
gates that one absent key (total_score) switched off entirely, the join that could not see a
dropped sub-game, four crash-instead-of-verdict paths on malformed input, the Hebrew-ids
crash through a Windows pipe, and the flat-layout refusal that now names its own fix. A red
row here means a fixed finding regressed.

Each case builds a synthetic bundle with the selftest's own recipe, mutates it, and runs the
checker as a subprocess — a crash (Traceback on stderr) is a failure regardless of exit code,
because a traceback is never a verdict.

Exit 0 = all cases hold; 1 = at least one regressed.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))
import verify_vectors as ref  # noqa: E402

CHECKER = KIT / "tools" / "check_artifacts.py"

a, b = "team-bet", "team-aleph"
terms = {"board_size": 7, "smell_grid_size": 5, "decay_per_step": 0.1, "emit_intensity": 0.9,
         "min_center_intensity": 0.5, "max_steps": 35, "barriers_max": 14, "setting": "Haifa",
         "hint_max_words": 15, "axis_origin_corner": "top-left", "axis_start_index": 0,
         "thief_start": [3, 3], "cop_start": [0, 0], "num_games": 6}
gid, guid = ref.ref_game_id(a, b), ref.ref_game_uid(terms, a, b)
base = {"game_id": gid, "game_uid": guid,
        "links": {"declaration": f"declaration_{gid}.json", "result": f"result_{gid}.json",
                  "config": f"config_{gid}_g<NN>.json", "log": f"log_{gid}_g<NN>.json"}}
FILES = {
    f"declaration_{gid}.json": {**base, "num_sub_games": 1,
                                "groups": {"group_1": {"group_id": a},
                                           "group_2": {"group_id": b}}},
    f"config_{gid}_g01.json": {**base, "sub_game_number": 1, "terms": terms},
    f"log_{gid}_g01.json": {**base, "summary": {"sub_game_number": 1}, "records": []},
    f"result_{gid}.json": {**base, "num_sub_games": 1,
                           "groups": [{"group_id": a}, {"group_id": b}],
                           "sub_games": [{"sub_game_number": 1, "score": {a: 20, b: 5}}],
                           "final_result": {"total_score": {a: 20, b: 5}}},
}

bad = 0


def build(dest: Path, mutate=None) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    data = {n: json.loads(json.dumps(d)) for n, d in FILES.items()}
    if mutate:
        mutate(data)
    for name, doc in data.items():
        (dest / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    return dest


def case(label: str, want: int, *dirs: Path) -> None:
    global bad
    proc = subprocess.run([sys.executable, str(CHECKER), *[str(d) for d in dirs], "--quiet"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    crashed = "Traceback" in (proc.stderr or "")
    ok = proc.returncode == want and not crashed
    bad += not ok
    got = "CRASH" if crashed else f"exit {proc.returncode}"
    print(f"  {'PASS' if ok else 'FAIL'}  {label} -> {got} (want exit {want}, no traceback)")


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)

    # P6-1: every league gate hung off total_score; omitting it let winner_group name the
    # loser (and a negative count, and a reward to the wrong side) with exit 0.
    def no_totals(data):
        data[f"result_{gid}.json"]["final_result"] = {
            "winner_group": b,
            "games_played_including_this": {a: 1, b: -7},
            "first_meeting_between_groups": True,
            "diversity_reward_applied": {a: False, b: True},
        }
    case("P6-1: league frauds with total_score omitted", 1, build(tmp / "A", no_totals))

    # P6-5: a null inside total_score TypeError'd the winner gate mid-verdict.
    def null_total(data):
        fr = data[f"result_{gid}.json"]["final_result"]
        fr["total_score"] = {a: None, b: 5}
        fr["winner_group"] = b
    case("P6-5: null in total_score + winner_group (verdict, not a stack)", 1,
         build(tmp / "B", null_total))

    # P6-3 / P6-4: a scalar count crashed the JOIN and was silently skipped single-dir.
    def count_int(data):
        data[f"result_{gid}.json"]["final_result"]["games_played_including_this"] = 7
    d1, d2 = build(tmp / "C1", count_int), build(tmp / "C2", count_int)
    case("P6-3: JOIN with a scalar game count (named FAIL, join continues)", 1, d1, d2)
    case("P6-4: single dir, same scalar count (FAIL, not a silent skip)", 1, d1)

    # P6-6: "tokens": 12 satisfied the key-presence guard and crashed the summation.
    def bad_tokens(data):
        r = data[f"result_{gid}.json"]
        r["sub_games"] = [{"sub_game_number": 1, "score": {a: 20, b: 5}, "tokens": 12}]
        r["final_result"]["tokens_total_series"] = {a: 12, b: 0}
    case("P6-6: per-row tokens as an int (shape FAIL, no traceback)", 1,
         build(tmp / "D", bad_tokens))

    # P6-2: a quietly dropped sub-game — compatible totals, different rows — joined clean.
    def two_rows(data):
        r = data[f"result_{gid}.json"]
        r["num_sub_games"] = 2
        r["sub_games"] = [{"sub_game_number": 1, "score": {a: 10, b: 5}},
                          {"sub_game_number": 2, "score": {a: 10, b: 0}}]
        r["final_result"] = {"total_score": {a: 20, b: 5}, "winner_group": a}
        data[f"declaration_{gid}.json"]["num_sub_games"] = 2
        data[f"log_{gid}_g02.json"] = {**base, "summary": {"sub_game_number": 2}, "records": []}

    def one_row(data):
        r = data[f"result_{gid}.json"]
        r["sub_games"] = [{"sub_game_number": 1, "score": {a: 20, b: 5}}]
        r["final_result"] = {"total_score": {a: 20, b: 5}, "winner_group": a}
    case("P6-2: JOIN sees the dropped sub-game (2 rows vs 1, same totals)", 1,
         build(tmp / "E1", two_rows), build(tmp / "E2", one_row))

    # P6-7: the declaration's promised series length vs the result's, reconciled.
    def decl_two(data):
        data[f"declaration_{gid}.json"]["num_sub_games"] = 2
    case("P6-7: declaration promises 2 sub-games, result reports 1", 1,
         build(tmp / "F", decl_two))

    # P6-8: Hebrew group ids through a PIPE (this subprocess IS one) — the reporting layer
    # must never fail an honest bundle. On Windows this crashed with UnicodeEncodeError.
    ua, ub = "קבוצה-אלף", "קבוצה-בית"
    ugid, uguid = ref.ref_game_id(ua, ub), ref.ref_game_uid(terms, ua, ub)
    d = tmp / "G"
    d.mkdir()
    ubase = {"game_id": ugid, "game_uid": uguid, "links": {}}
    for name, doc in {
            f"declaration_{ugid}.json": {**ubase, "num_sub_games": 1,
                                         "groups": {"group_1": {"group_id": ua},
                                                    "group_2": {"group_id": ub}}},
            f"config_{ugid}_g01.json": {**ubase, "sub_game_number": 1, "terms": terms},
            f"log_{ugid}_g01.json": {**ubase, "summary": {"sub_game_number": 1}, "records": []},
            f"result_{ugid}.json": {**ubase, "num_sub_games": 1,
                                    "groups": [{"group_id": ua}, {"group_id": ub}],
                                    "sub_games": [{"sub_game_number": 1,
                                                   "score": {ua: 20, ub: 5}}],
                                    "final_result": {"total_score": {ua: 20, ub: 5}}},
    }.items():
        (d / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    case("P6-8: Hebrew group ids verify through a pipe", 0, d)

    # P6-9's flat-layout contract, kept ON PURPOSE: a split layout is refused (exit 1) — and
    # the refusal names the restaging fix, which is the checkable half of the decision.
    d = build(tmp / "H")
    (d / "config" / "games").mkdir(parents=True)
    (d / f"config_{gid}_g01.json").rename(d / "config" / "games" / f"config_{gid}_g01.json")
    proc = subprocess.run([sys.executable, str(CHECKER), str(d)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    hinted = "subdirector" in (proc.stdout or "")
    ok = proc.returncode == 1 and hinted and "Traceback" not in (proc.stderr or "")
    bad += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  P6-9: split layout refused BY NAME "
          f"-> exit {proc.returncode}, hint {'present' if hinted else 'MISSING'} "
          f"(want exit 1 + the restaging hint)")

print(f"\n{'ALL PASS-SIX FINDINGS HOLD' if bad == 0 else f'{bad} REGRESSION(S)'}")
sys.exit(1 if bad else 0)
