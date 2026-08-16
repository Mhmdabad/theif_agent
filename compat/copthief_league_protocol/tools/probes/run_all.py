"""Run anrbj666's audit probes against this checkout — all must exit 0.

    python tools/probes/run_all.py [path-to-kit-repo]

The four probes were written by Alon Engel & Renat Karimov (anrbj666) for their 2026-08-04
four-pass audit, designed to exit non-zero WHILE their finding reproduces and to flip green
when the fix lands. Committed here as living regressions, run by CI: a probe going red again
means an audit finding has been reintroduced. See each probe's own docstring for what it
demonstrates; `probe_a1_audit_chain.py` carries a dated adaptation note, the other three are
verbatim.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    kit = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parent.parent)
    # The probes print the non-ASCII characters they are ABOUT; a cp1252 console (Windows
    # default) would crash the print, not the finding. Forced UTF-8 keeps them verbatim.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    bad = 0
    for probe in sorted(HERE.glob("probe_*.py")):
        proc = subprocess.run([sys.executable, str(probe), kit],
                              capture_output=True, text=True, encoding="utf-8", env=env)
        ok = proc.returncode == 0
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {probe.name} -> exit {proc.returncode}")
        if not ok:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
    print(f"\n{'ALL PROBES GREEN' if bad == 0 else f'{bad} PROBE(S) RED — a fixed finding has regressed'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
