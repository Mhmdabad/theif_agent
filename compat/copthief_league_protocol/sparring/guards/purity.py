"""Structural checks that keep this peer honest about what it is — stdlib only.

    python -m sparring.guards.purity

Four claims are made elsewhere in words. Here they are made about the source:

* **P-1 — the peer never hand-rolls a hash.** ``hashlib`` appears only in ``kitref.py`` and the
  guards. So "our bytes are the kit's bytes" is a property of the import graph, not a habit.
* **P-2 — no tuned anything, ever.** ``policies/`` may import only a tiny stdlib set plus the
  rules, may not read files, and may not name a weights format. A brain that cannot open a file
  cannot load a trained model.
* **P-3 — one clock.** ``time`` and ``datetime`` live in ``deadlines.py`` alone, which is what
  makes a seeded self-play run reproducible and a fake clock possible in tests.
* **P-4 — the root kit stays dependency-free.** The single pinned dependency may be installed by
  exactly one workflow; if ``verify.yml`` ever grows a ``pip install``, the zero-dependency
  promise on the repository root has quietly ended.

Plus **P-5**: the four kit functions this peer must not reach for (a settlement signature it
cannot need, and three opt-in enhancements nobody signed) appear nowhere under ``sparring/``.

Exit codes:  0 = clean · 3 = violation
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
KIT = PKG.parent
GUARDS = PKG / "guards"

HASH_ALLOWED = {PKG / "kitref.py", GUARDS / "no_mail.py", GUARDS / "purity.py"}
CLOCK_ALLOWED = {PKG / "deadlines.py", GUARDS / "purity.py"}
POLICY_IMPORTS_OK = {"random", "math", "dataclasses", "typing", "enum", "collections",
                     "__future__", "sparring"}
WEIGHT_FILES = re.compile(r"\.(npz|npy|pt|pth|pkl|pickle|h5|onnx|safetensors|ckpt)\b")
FILE_READS = re.compile(r"\b(open|read_text|read_bytes|loadtxt|load)\s*\(")

RULES = {
    "P-1": "imports hashlib outside kitref.py — the peer must never hand-roll a hash",
    "P-2": "policies/ reached outside its allowed surface — no tuned weights, ever",
    "P-3": "imports time/datetime outside deadlines.py — one clock, or self-play is not reproducible",
    "P-4": "verify.yml installs a dependency — the repository root is dependency-free",
    "P-5": "names a kit function this peer must not use",
}


def _sources() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def scan() -> list[tuple[str, Path, int, str]]:
    bad: list[tuple[str, Path, int, str]] = []

    def add(rule: str, path: Path, line: int, what: str) -> None:
        bad.append((rule, path.relative_to(KIT) if path.is_absolute() else path, line, what))

    withheld = _withheld_names()

    for path in _sources():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        in_policies = path.parent.name == "policies"

        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root == "hashlib" and path not in HASH_ALLOWED:
                    add("P-1", path, node.lineno, root)
                if root in ("time", "datetime") and path not in CLOCK_ALLOWED:
                    add("P-3", path, node.lineno, root)
                if in_policies and root not in POLICY_IMPORTS_OK:
                    add("P-2", path, node.lineno, f"import {root}")

        if in_policies:
            for i, line in enumerate(text.splitlines(), start=1):
                if WEIGHT_FILES.search(line):
                    add("P-2", path, i, "a weights-file extension")
                if FILE_READS.search(line):
                    add("P-2", path, i, "a file read")

        # P-5 has two halves. The strong one is structural and applies everywhere including
        # kitref.py: a withheld name may never be *reached for* — no attribute access, no import
        # alias. The weaker one is a text scan that also forbids mentioning them, and it exempts
        # the two files whose job is to name them: kitref.py declares WITHHELD, this file reads it.
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in withheld:
                add("P-5", path, node.lineno, f"reaches for {node.attr}")
            elif isinstance(node, ast.ImportFrom) and node.module and "verify_vectors" in node.module:
                for alias in node.names:
                    if alias.name in withheld:
                        add("P-5", path, node.lineno, f"imports {alias.name}")
        # Text half exempts the declaring files and the tests, for the same reason as NM-2: the
        # structural half above still applies everywhere, so a module that actually *reaches for*
        # a withheld name is caught wherever it lives.
        if path.name not in ("purity.py", "kitref.py") and "tests" not in path.parts:
            for i, line in enumerate(text.splitlines(), start=1):
                for name in withheld:
                    if name in line:
                        add("P-5", path, i, name)

    workflow = KIT / ".github" / "workflows" / "verify.yml"
    if workflow.is_file():
        for i, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"pip\s+install", line):
                add("P-4", workflow, i, line.strip())

    return bad


def _withheld_names() -> tuple[str, ...]:
    """Read the withheld list from kitref rather than restating it, so the two cannot disagree."""
    text = (PKG / "kitref.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "WITHHELD":
                    return tuple(e.value for e in node.value.elts        # type: ignore[attr-defined]
                                 if isinstance(e, ast.Constant))
    raise AssertionError("kitref.WITHHELD is missing — purity cannot check what it does not know")


def assert_pure() -> None:
    bad = scan()
    if bad:
        lines = "\n".join(f"  {r}  {p}:{ln}  {w}   ({RULES[r]})" for r, p, ln, w in bad)
        raise AssertionError(f"PURITY VIOLATION\n{lines}")


def main() -> int:
    try:
        assert_pure()
    except AssertionError as exc:
        print(exc, file=sys.stderr)
        return 3
    print(f"purity: OK  ({len(_sources())} files, {len(RULES)} rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
