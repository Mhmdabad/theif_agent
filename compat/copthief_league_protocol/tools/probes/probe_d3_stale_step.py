"""PROBE D3 — the delivery contract leaves stale steps unpinned (fourth probe, bonus).

Finding (anrbj666 audit, 2026-08-04): ref_delivery_decision computes `step - next` and treats
"within the reorder window" as the buffer condition. For a step BELOW `next` that is absent from
`played`, the difference is NEGATIVE, which is always <= window, so the decision is "buffer" —
and a buffer entry below `next` can never drain, because draining only ever looks for `next`.
No fixture row covers this state, so two conformant receivers may disagree while both pass.

The fixture's own state invites it: played={1,2}, next=3 leaves step 0 unaccounted for.

Run:  python probe_d3_stale_step.py [path-to-kit-repo]
"""

import sys
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else
           str(Path(__file__).resolve().parents[2]))  # P5-16: relative default
sys.path.insert(0, str(KIT))

import verify_vectors as ref                                   # noqa: E402


def main() -> int:
    state = {"played": {"1": "aa" * 32, "2": "bb" * 32}, "next": 3, "window": 4}
    stale = {"step": 0, "commit": "cc" * 32}

    decision = ref.ref_delivery_decision(state, stale)
    print(f"  receiver state: played={sorted(state['played'])} next={state['next']} "
          f"window={state['window']}")
    print(f"  arrival:        step {stale['step']} (below next, never played)")
    print(f"  decision:       {decision!r}")
    print()
    print("  a step-0 entry buffered against next=3 can never drain: draining looks for `next`,")
    print("  and `next` only ever increases. The buffer slot is occupied forever.")
    print()
    unpinned = decision == "buffer"
    print("VERDICT: " + ("REPRODUCED — stale steps decide 'buffer'; one decision-table row "
                         "(discard) closes it" if unpinned else f"decides {decision!r} — pinned"))
    return 0 if not unpinned else 1


if __name__ == "__main__":
    raise SystemExit(main())
