"""Verify a bundle is a set of games that could actually be PLAYED.

    python examples/verify_pairing_physics.py [dir]      # default: examples/pairing-artifacts

`tools/check_artifacts.py` checks names, ids, required keys and score arithmetic — by
design it never opens a sealed payload, so it cannot see a log whose records contradict
its own summary. This does: it re-hashes every sealed record, walks both sides' moves
under the book's physics, and requires each sub-game to actually REACH the outcome its
row declares.

It exists because an earlier revision of this bundle shipped one-step logs declaring
`capture` (with the cop three cells from the thief) and `survival` (against a threshold of
35) — each row asserting `log_verified: true` over a game that could not produce its own
result. `check_artifacts` passed it. Found by anrbj666 auditing anrbj666's contribution,
2026-08-04; this checker is the regression gate for that class.

It takes the bundle path as an optional argument (anrbj666's pass-six probes did the same, for
the same reason): the check that matters most is the one you run against artifacts you did NOT
generate — a real counted set, an opponent's bundle before a join — and a gate wired to one
hardcoded directory can only ever re-certify the fixture it ships with. CI still passes no
argument, so the default is unchanged.

Exit 0 = every game is legal and reaches its declared outcome.
Exit 2 = the directory holds nothing this can read (see the note it prints — a foreign bundle
         may seal its logs in a shape this walker does not know, which is not a physics fault).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import verify_vectors as ref  # noqa: E402

BUNDLE = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1
          else Path(__file__).resolve().parent / "pairing-artifacts")
DELTAS = {"MOVE:N": (-1, 0), "MOVE:S": (1, 0), "MOVE:E": (0, 1), "MOVE:W": (0, -1),
          "STAY": (0, 0)}          # the book's move set: orthogonal or stay, never diagonal

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        failures.append(f"{label}{('  ' + detail) if detail else ''}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail and not ok else ''}")


def walk(records: list[dict], start: tuple[int, int], board: int,
         label: str) -> tuple[int, int]:
    """Replay one side's revealed moves; every step must be legal and on the board."""
    pos = start
    for rec in records:
        payload = rec["payload"]
        if payload.get("step") == 0:
            continue
        move = payload.get("move")
        if move not in DELTAS:
            failures.append(f"{label}: step {payload.get('step')} move {move!r} is not in the "
                            f"book's move set (no diagonals)")
            continue
        delta = DELTAS[move]
        nxt = (pos[0] + delta[0], pos[1] + delta[1])
        if not (0 <= nxt[0] < board and 0 <= nxt[1] < board):
            failures.append(f"{label}: step {payload['step']} leaves the board at {nxt}")
        if list(nxt) != payload.get("position"):
            failures.append(f"{label}: step {payload['step']} declares position "
                            f"{payload.get('position')} but {move} from {list(pos)} lands {list(nxt)}")
        if payload.get("state", "").split("self=")[-1].split(";")[0] != f"[{nxt[0]}, {nxt[1]}]":
            failures.append(f"{label}: step {payload['step']} state disagrees with position")
        pos = nxt
    return pos


def unreadable(why: str) -> int:
    """Refuse with a diagnosis, never with a stack.

    Pointed at a bundle it did not generate, this walker meets shapes it does not know — and a
    shape it cannot read is NOT a physics fault. Saying so in words is the difference between
    "their logs are wrong" and "our tool cannot read their logs", which is the whole distinction
    an audit of someone else's artifacts exists to make.
    """
    print(f"cannot read this bundle: {why}\n"
          f"  This is a limit of THIS checker, not a verdict on the bundle. "
          f"tools/check_artifacts.py and `sparring.cli replay` read a wider range of shapes; "
          f"run those and report this as unreadable-here rather than as a physics failure.",
          file=sys.stderr)
    return 2


def main() -> int:
    results = sorted(BUNDLE.glob("result_*.json"))
    if not results:
        return unreadable(f"no result_*.json at the top level of {BUNDLE}")
    result = json.loads(results[0].read_text(encoding="utf-8"))
    if not isinstance(result.get("sub_games"), list):
        return unreadable(f"{results[0].name} has no sub_games list")
    rows = {row.get("sub_game_number"): row for row in result["sub_games"]
            if isinstance(row, dict)}

    logs = sorted(BUNDLE.glob("log_*_g*.json"))
    if not logs:
        return unreadable(f"no log_*_g<NN>.json at the top level of {BUNDLE}")
    for log_path in logs:
        doc = json.loads(log_path.read_text(encoding="utf-8"))
        n = doc.get("sub_game_number", (doc.get("summary") or {}).get("sub_game_number"))
        cfg_path = BUNDLE / f"config_{doc.get('game_id')}_g{n:02d}.json" \
            if isinstance(n, int) else None
        if cfg_path is None or not cfg_path.is_file():
            return unreadable(f"{log_path.name} does not name a sub-game with a config beside "
                              f"it (looked for {cfg_path.name if cfg_path else 'config_*'})")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # Every key this walker goes on to DEREFERENCE, checked here — not just the top-level
        # containers. The first revision gated on the containers and then read row["steps"],
        # row["result"], summary["role"], summary["steps"] and the terms' cells unchecked, so a
        # real foreign bundle got past the gate and died on `KeyError: 'steps'`: a stack instead
        # of the diagnosis this whole function exists to print. Found against anrbj666's counted
        # bundle, 2026-08-05, whose result rows carry no `steps` and need not.
        summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
        row = rows.get(n) if isinstance(rows.get(n), dict) else {}
        terms = cfg.get("terms") if isinstance(cfg.get("terms"), dict) else None
        missing = [k for k in ("records", "opponent_records", "summary") if k not in doc]
        missing += [f"summary.{k}" for k in ("role", "steps") if k not in summary]
        missing += [] if terms is None else \
            [f"terms.{k}" for k in ("board_size", "max_steps", "cop_start", "thief_start")
             if k not in terms]
        if terms is None:
            missing.append("config terms")
        if n not in rows:
            missing.append(f"result row {n}")
        else:
            missing += [f"row.{k}" for k in ("result", "steps") if k not in row]
        if missing:
            return unreadable(f"{log_path.name}: missing {sorted(set(missing))} — this walker "
                              f"needs both sides' sealed records, the flat terms and the row "
                              f"that declares the outcome")
        board, max_steps = terms["board_size"], terms["max_steps"]
        print(f"{log_path.name}  ({row['result']}, {row['steps']} steps)")

        # A sealed record is payload + nonce + commit. One that is not is a shape this walker
        # cannot judge, and guessing at it below would be another KeyError.
        sealed = doc["records"] + doc["opponent_records"]
        if not all(isinstance(r, dict) and {"payload", "nonce", "commit"} <= set(r)
                   and isinstance(r["payload"], dict) for r in sealed):
            return unreadable(f"{log_path.name}: a sealed record is not "
                              f"{{payload, nonce, commit}} with an object payload")
        if not doc["records"]:
            return unreadable(f"{log_path.name}: no own records to walk")

        # 1. every sealed record re-hashes
        bad = [r["payload"].get("step") for r in sealed
               if ref.ref_commit(r["payload"], r["nonce"]) != r["commit"]]
        check("every sealed record re-hashes to its commit", not bad, f"failed steps {bad}")

        # 2. both sides' walks are legal, from the START CELLS THE TERMS DECLARE
        mine_is_cop = summary["role"] == "police"
        my_start = tuple(terms["cop_start"] if mine_is_cop else terms["thief_start"])
        their_start = tuple(terms["thief_start"] if mine_is_cop else terms["cop_start"])
        before = len(failures)
        my_end = walk(doc["records"], my_start, board, f"g{n:02d} own")
        their_end = walk(doc["opponent_records"], their_start, board, f"g{n:02d} opponent")
        check("both sides' moves are legal and on the board", len(failures) == before,
              "; ".join(failures[before:]))

        # 3. the declared step count matches the records
        steps_seen = [r["payload"]["step"] for r in doc["records"]
                      if isinstance(r["payload"].get("step"), int)]
        if not steps_seen:
            return unreadable(f"{log_path.name}: no record numbers itself with an integer step")
        played = max(steps_seen)
        check("summary.steps matches the sealed records",
              played == row["steps"] == summary["steps"],
              f"records reach {played}, summary says {summary['steps']}, row says {row['steps']}")

        # 4. THE OUTCOME IS ACTUALLY REACHED
        cop_end, thief_end = (my_end, their_end) if mine_is_cop else (their_end, my_end)
        if row["result"] == "capture":
            check("a capture is on the board: the cop ends on the thief's cell",
                  cop_end == thief_end, f"cop {cop_end}, thief {thief_end}")
        elif row["result"] == "survival":
            check(f"a survival reaches the threshold ({max_steps} steps)", played >= max_steps,
                  f"played {played}")
            check("the thief was never caught along the way", cop_end != thief_end,
                  f"both ended on {cop_end}")
        print()

    print("BUNDLE PHYSICS OK" if not failures else f"{len(failures)} PHYSICS FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
