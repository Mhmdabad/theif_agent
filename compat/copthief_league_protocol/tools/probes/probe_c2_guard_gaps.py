"""PROBE C1/C2 — the no-mail guarantee is lexical, and its two lexical rules have gaps.

Findings (anrbj666 audit, 2026-08-04):
  C1  subprocess/os are neither banned nor network-confined, so an arbitrary HTTPS call can
      leave any module by shelling out; the NM-2 token scan carries no token for that.
  C2  NM-1 inspects only ast.Import / ast.ImportFrom, so a dynamic import is invisible — and
      NM-2 does not backstop it, because the word-boundary pattern \\bsmtp\\b does NOT match
      inside the whole word "smtplib".

Neither is a live escape in the shipped tree (we found no such call). The claim is about the
mechanism, not the current code.

Run:  python probe_c2_guard_gaps.py [path-to-kit-repo]
"""

import ast
import re
import sys
from pathlib import Path

KIT = Path(sys.argv[1] if len(sys.argv) > 1 else
           str(Path(__file__).resolve().parents[2]))  # P5-16: relative default

# The two lexical rules, as the guard states them.
BANNED_TOKEN_RE = re.compile(r"\bsmtp\b", re.IGNORECASE)   # NM-2's shape
DYNAMIC_IMPORT = 'importlib.import_module("smtplib")'
STATIC_IMPORT = "import smtplib"


def probe_word_boundary_trap() -> bool:
    """C2: the token scan cannot see the library it is meant to ban."""
    hits_dynamic = bool(BANNED_TOKEN_RE.search(DYNAMIC_IMPORT))
    hits_url = bool(BANNED_TOKEN_RE.search("smtp://mail.example/send"))
    print(f'  \\bsmtp\\b vs {DYNAMIC_IMPORT!r} -> {hits_dynamic}   (the gap)')
    print(f'  \\bsmtp\\b vs "smtp://…"                        -> {hits_url}   (works)')
    return not hits_dynamic


def probe_ast_blindness() -> bool:
    """C2: an AST walk over Import/ImportFrom does not see a dynamic import Call."""
    def static_imports(source: str) -> list[str]:
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                found += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module)
        return found

    print(f"  AST sees in {STATIC_IMPORT!r}: {static_imports(STATIC_IMPORT)}")
    print(f"  AST sees in {DYNAMIC_IMPORT!r}: {static_imports(DYNAMIC_IMPORT)}")
    return static_imports(DYNAMIC_IMPORT) == []


def probe_subprocess_unconfined() -> bool:
    """C1: is `subprocess` in the guard's banned or network-confined lists at all?"""
    guard = (KIT / "sparring" / "guards" / "no_mail.py")
    if not guard.is_file():
        print(f"  (guard not found at {guard} — skipping C1 source check)")
        return False
    text = guard.read_text(encoding="utf-8")
    mentioned = "subprocess" in text
    print(f"  'subprocess' appears anywhere in no_mail.py: {mentioned}")
    return not mentioned


if __name__ == "__main__":
    print("PROBE C2 — the \\bsmtp\\b word-boundary trap")
    trap = probe_word_boundary_trap()
    print()
    print("PROBE C2 — AST blindness to dynamic imports")
    blind = probe_ast_blindness()
    print()
    print("PROBE C1 — subprocess unconfined")
    unconfined = probe_subprocess_unconfined()
    print()
    reproduced = trap and blind and unconfined
    print("VERDICT: " + ("REPRODUCED — a banned library is reachable past both rules"
                         if reproduced else "one or more gaps are closed"))
    raise SystemExit(0 if not reproduced else 1)
