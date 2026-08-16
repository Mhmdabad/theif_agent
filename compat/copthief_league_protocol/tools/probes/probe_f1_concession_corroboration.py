"""PROBE F1/F2 — the `caught: true` that settles a game is corroborated, and degrades.

Findings (imreeyal, reviewing anrbj666's issue-#37 fix, 2026-08-05). The construction that stops
a rule-46/47 ending forking the game is a thief-sent `caught: true` final, and the cop must check
it rather than believe it — a capture pays the thief 5 where the zeroed row it replaces pays 0.
Two ways that check went wrong, and one way its fix could:

  F-1  The corroboration read the revealed POSITION trail, and a peer whose payloads seal
       action+state only (a legal schema — SPEC section 3: the payload schema is not an interop
       constraint) has no trail. Every honest rule-46/47 ending of such a peer settled
       `tamper_forfeit`. That is the K-1 mistake — our own payload schema treated as everyone's.

  F-2  A `caught: true` echoing the cop's own claimed cell was classified as an ANSWER and
       skipped corroboration entirely. The cop TRANSMITS that cell every turn as `capture_claim`,
       so the bypass is available to any thief that wants it — and a false answer is the worse
       lie, because it pays the thief 5 AND the cop 20, so both peers profit and neither has an
       incentive to look.

  The third case is the one that guards the fix itself: a degradation must NARROW the check, not
  switch it off. A position-less concession over a cell our barriers never touched must still
  fail, or F-1's fix has quietly repealed F-2's.

Run:  python probe_f1_concession_corroboration.py [path-to-kit-repo]
"""

import sys
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else
           str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(KIT))

from sparring import kitref                                    # noqa: E402
from sparring.audit import audit_records                       # noqa: E402

_TOKEN = {(-1, 0): "MOVE:N", (1, 0): "MOVE:S", (0, 1): "MOVE:E", (0, -1): "MOVE:W",
          (0, 0): "STAY"}


def sealed(cells: list[list[int]], *, with_position: bool = True) -> list[dict]:
    """An honestly sealed thief trail whose move tokens AGREE with the deltas its positions
    show — otherwise the physics layer's own cross-check fires and this probe measures its
    fixture instead of the thing it is pinning."""
    out, prev = [], None
    for step, pos in enumerate(cells, start=1):
        move = "STAY" if prev is None else _TOKEN[(pos[0] - prev[0], pos[1] - prev[1])]
        prev = pos
        payload = {"step": step, "role": "thief", "sub_game": 1, "move": move,
                   "intent": "truth", "hint": "", "verdict": "settled",
                   "state": f"grid=7x7;self={pos};barriers=[]"}
        if with_position:
            payload["position"] = pos
        nonce = f"{step:032x}"
        out.append({"payload": payload, "nonce": nonce,
                    "commit": kitref.commit(payload, nonce)})
    return out


CASES = [
    # (label, want_passed, kwargs)
    ("F-1  an honest concession, reveal carries positions",
     True, dict(records=sealed([[4, 6], [4, 5]]),
                concession={"claim": [4, 5], "caught": True}, own_barriers=[[4, 5]])),
    ("F-1  the same, reveal carries NO position -> degrades, never accuses",
     True, dict(records=sealed([[4, 6], [4, 5]], with_position=False),
                concession={"claim": [4, 5], "caught": True}, own_barriers=[[4, 5]])),
    ("F-1  position-less AND not captured under our barriers -> STILL refused",
     False, dict(records=sealed([[4, 6], [4, 5]], with_position=False),
                 concession={"claim": [2, 2], "caught": True}, own_barriers=[[4, 5]])),
    ("     a concession over a cell our barriers never touched",
     False, dict(records=sealed([[2, 3], [2, 2]]),
                 concession={"claim": [2, 2], "caught": True}, own_barriers=[[4, 5]])),
    ("     a concession the revealed trail never reached",
     False, dict(records=sealed([[4, 6], [4, 5]]),
                 concession={"claim": [6, 6], "caught": True},
                 own_barriers=[[5, 6], [6, 5]])),
    ("F-2  a FALSE answer echoing our claimed cell -> refused, not believed",
     False, dict(records=sealed([[2, 3], [2, 2]]), answered_at=[4, 6])),
    ("F-2  a TRUE answer, trail ends where the answer said",
     True, dict(records=sealed([[4, 5], [4, 6]]), answered_at=[4, 6])),
    ("F-2  a position-less answer degrades rather than accusing",
     True, dict(records=sealed([[4, 5], [4, 6]], with_position=False), answered_at=[4, 6])),
]


def main() -> int:
    import inspect

    params = inspect.signature(audit_records).parameters
    missing = [k for k in ("concession", "own_barriers", "answered_at") if k not in params]
    if missing:
        print(f"  FAIL  audit_records lost {missing} — the corroboration layer is gone")
        return 1

    bad = 0
    for label, want, kwargs in CASES:
        result = audit_records(board_size=7, **kwargs)
        ok = result.passed is want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}\n"
              f"        passed={result.passed} (want {want})")
        if not ok and result.detail:
            print(f"        {result.detail.strip().splitlines()[0][:120]}")

    print(f"\n{'PROBE F1/F2 GREEN' if not bad else f'{bad} CASE(S) REGRESSED'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
