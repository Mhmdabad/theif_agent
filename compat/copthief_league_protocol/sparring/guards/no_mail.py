"""Prove this peer has no mail surface at all — stdlib only.

    python -m sparring.guards.no_mail [--check-env]

"Disabled" and "absent" are different guarantees. A disabled sender is one flag from sending; an
absent one has nothing to flag. This package takes the second position, and this module is what
makes that a checkable statement about the source rather than a promise in a README.

Why it matters for a *practice* peer specifically: a sparring game is an uncounted warm-up (book
App. E rule 52), so no report is owed by either side. A stray report from a practice run, carrying
a real-looking `game_id`, could collide with a counted report about the same opponent — and under
App. E rule 35 two contradictory reports score **0 for both teams**. The cheapest way to
guarantee that cannot happen is to have no code that could do it.

Seven rules, `NM-1` … `NM-7`. The one that makes "absent" mean absent is **NM-5**: without
confining outbound networking, a package could import no mail library and still open a socket to
port 587.

Exit codes:  0 = no mail surface · 3 = violation
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
KIT = PKG.parent

# NM-1: nothing that speaks mail, and nothing that authorizes speaking it. `subprocess` and
# `importlib` ride the same rule: neither speaks mail itself, but a shell-out reaches any
# binary on the machine and a dynamic import defeats this scan's static premise — anrbj666's
# C1/C2 (2026-08-04) showed both escapes were open. No sparring module needs either.
BANNED_IMPORTS = {
    "smtplib", "imaplib", "poplib", "email", "mailbox", "aiosmtplib", "exchangelib",
    "yagmail", "sendgrid", "mailgun", "googleapiclient", "google", "google_auth_oauthlib",
    "oauth2client", "msal", "O365",
    "subprocess", "importlib",
}
# NM-2: the vocabulary, wherever it hides (a string, a comment, a config key). Library names
# appear beside their bare protocol tokens because \b(smtp)\b does NOT match inside "smtplib" —
# the word-boundary trap anrbj666's C2 probe demonstrated — and os-level shell-outs are named
# here because `os` itself cannot be banned.
BANNED_TOKENS = re.compile(
    r"\b(smtp|smtplib|imap|imaplib|poplib|sendgrid|mailgun|rfc822|sendmail|starttls)\b"
    r"|@gmail\.com|messages\(\)\.send|users\(\)\.drafts"
    r"|os\.system|os\.popen|os\.spawn|os\.exec",
    re.IGNORECASE,
)
# NM-3: the ports. 25 is excluded — too plausible as an ordinary integer to mean anything.
BANNED_PORTS = {465, 587, 993, 995}
# NM-4: names that would house it.
BANNED_FILENAME = re.compile(r"(?i)mail|smtp|report_writer")
BANNED_FUNCS = re.compile(r"^(send_report|email_report|send_mail|deliver_report|draft_.*)$")
# NM-5: outbound networking exists in exactly two modules, and they speak MCP.
NETWORK_MODULES = {"socket", "ssl", "http", "httpx", "requests", "urllib", "aiohttp", "websockets"}
NETWORK_ALLOWED = {
    PKG / "transport" / "server.py",
    PKG / "transport" / "client.py",
    PKG / "guards" / "no_mail.py",   # this file names them in order to ban them
    PKG / "guards" / "purity.py",
}
#: The HTTP test tier exists to exercise the network surface, so it may reach it. The
#: zero-dependency tier may NOT — which is a useful invariant in its own right: it is what
#: guarantees the whole game layer, including a full six-sub-game series, really does run with
#: nothing installed and no socket in sight.
NETWORK_ALLOWED_DIRS = (PKG / "tests" / "http",)
# NM-7: the preflight may assert things about the RULES and nothing about a DELIVERABLE.
PREFLIGHT_BANNED = re.compile(r"(?i)recipient|smtp|gmail|consensus_signature|חתימת|deliverable")

RULES = {
    "NM-1": "imports something that speaks mail or authorizes it",
    "NM-2": "contains mail vocabulary",
    "NM-3": "contains a mail port number",
    "NM-4": "is named for mail, or defines a mail-shaped function",
    "NM-5": "opens outbound networking outside transport/{server,client}.py",
    "NM-6": "declares a dependency other than the single pinned one",
    "NM-7": "lets the preflight demand a deliverable",
}


class Violation(Exception):
    pass


def _sources() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _docstrings(tree: ast.AST) -> set[int]:
    """id() of every node that is a docstring, so prose can be told apart from code."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _report(out: list[tuple[str, Path, int, str]], rule: str, path: Path, line: int, what: str):
    out.append((rule, path, line, what))


def scan(check_env: bool = False) -> list[tuple[str, Path, int, str]]:
    """Return every violation found. Empty list means the mail surface is absent."""
    bad: list[tuple[str, Path, int, str]] = []

    for path in _sources():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(KIT)

        if BANNED_FILENAME.search(path.name) and path.name != "no_mail.py":
            _report(bad, "NM-4", rel, 0, path.name)

        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:                                    # pragma: no cover
            raise Violation(f"{rel}: will not parse — {exc}") from exc

        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in BANNED_IMPORTS:
                    if root == "importlib" and path.name == "no_mail.py":
                        continue  # the env scan itself reads importlib.metadata — the same
                        # self-exemption NM-2 and NM-4 already grant the file that names things
                    _report(bad, "NM-1", rel, node.lineno, root)
                if (root in NETWORK_MODULES and path not in NETWORK_ALLOWED
                        and not any(d in path.parents for d in NETWORK_ALLOWED_DIRS)):
                    _report(bad, "NM-5", rel, node.lineno, root)
            # NM-1 also covers the dynamic forms: `__import__(...)` and `*.import_module(...)`
            # are Calls, not Import nodes, so the static walk above cannot see what they load —
            # which is exactly why their PRESENCE is the violation, regardless of argument
            # (anrbj666's C2: the AST walk returned [] for a dynamic smtplib import).
            if isinstance(node, ast.Call):
                dynamic = (isinstance(node.func, ast.Name) and node.func.id == "__import__") or \
                          (isinstance(node.func, ast.Attribute)
                           and node.func.attr == "import_module")
                if dynamic and path.name != "no_mail.py":
                    _report(bad, "NM-1", rel, node.lineno,
                            "dynamic import — defeats the static scan by construction")
            if isinstance(node, ast.FunctionDef) and BANNED_FUNCS.match(node.name):
                _report(bad, "NM-4", rel, node.lineno, node.name)
            # This file lists the banned ports in order to ban them; every other file may not
            # contain one at all.
            if path.name != "no_mail.py" and isinstance(node, ast.Constant):
                if (isinstance(node.value, int) and not isinstance(node.value, bool)
                        and node.value in BANNED_PORTS):
                    _report(bad, "NM-3", rel, node.lineno, str(node.value))

        # NM-2 is a text scan, so it exempts the files whose job is to *name* the banned things:
        # this module defines them, and the tests feed them in as synthetic violations. The AST
        # rules above still apply to every file including the tests — a real `import smtplib`
        # anywhere is caught; a string mentioning one in a test is not.
        if path.name not in ("no_mail.py", "purity.py") and "tests" not in path.parts:
            for i, line in enumerate(text.splitlines(), start=1):
                m = BANNED_TOKENS.search(line)
                if m:
                    _report(bad, "NM-2", rel, i, m.group(0))

        if path.name == "preflight.py":
            # Deliberately AST-precise rather than a text scan: the rule is that the preflight may
            # not *assert* anything about a deliverable, not that it may not *explain* why. Its
            # docstring says exactly that, and a text scan would fail the file for saying so.
            prose = _docstrings(tree)
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.arg):
                    name = node.arg
                elif isinstance(node, ast.keyword):
                    name = node.arg
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    name = None if id(node) in prose else node.value
                if name and PREFLIGHT_BANNED.search(name):
                    _report(bad, "NM-7", rel, getattr(node, "lineno", 0), name[:40])

    req = PKG / "requirements.txt"
    if req.is_file():
        wants = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        for i, want in enumerate(wants, start=1):
            if not re.match(r"^fastmcp\b", want, re.IGNORECASE):
                _report(bad, "NM-6", req.relative_to(KIT), i, want)

    if check_env:
        bad.extend(_scan_environment())
    return bad


#: Distributions that can actually *send* mail or authorize sending it. Matched as whole names or
#: name prefixes, never as substrings.
#:
#: A substring match on "mail" is the wrong test, and it was the first thing this check got wrong:
#: it failed on `email-validator`, a transitive dependency of the one pinned package that checks
#: the *shape of an address string* and opens no connection to anything. Failing the build over a
#: name collision teaches people to disable the guard, which is worse than not having it.
#:
#: The load-bearing guarantee is NM-5 — outbound networking is confined to the two transport
#: modules in our own source — so nothing installed can be reached for regardless. This scan is a
#: second belt over the environment, and it should be precise rather than eager.
ENV_SENDERS = (
    "smtplib", "aiosmtplib", "sendgrid", "mailgun", "yagmail", "mailjet", "postmarker",
    "sib-api", "sendinblue", "mailchimp", "boto3-ses", "django-anymail", "flask-mail",
    "google-api-python-client", "google-auth-oauthlib", "oauth2client", "msal", "exchangelib",
    "o365", "imapclient",
)
#: Name collisions, with the reason each is harmless. Anything added here needs one.
ENV_ALLOW = {
    "email-validator": "validates the shape of an address string; opens no connection",
}


def _scan_environment() -> list[tuple[str, Path, int, str]]:
    """Also check what is *installed*, so the claim covers the runtime and not only our source."""
    out: list[tuple[str, Path, int, str]] = []
    try:
        from importlib import metadata
    except ImportError:                                              # pragma: no cover
        return out
    for dist in metadata.distributions():
        name = (dist.metadata["Name"] or "").lower()
        if name in ENV_ALLOW:
            continue
        if any(name == sender or name.startswith(f"{sender}-") for sender in ENV_SENDERS):
            out.append(("NM-6", Path("<environment>"), 0, f"{name} can send mail"))
    return out


def manifest_sha256() -> str:
    """A hash over (file, sha256) for every scanned source, plus the rule-set version.

    Written into the declaration artifact, so a run's own artifact carries the evidence that the
    peer which produced it had no mail surface.

    Line endings are normalised before hashing, and paths use forward slashes. Without that the
    manifest identifies a *checkout* rather than the source: the same commit hashes differently on
    a machine that checked out CRLF than on one that checked out LF, which makes the value useless
    for comparing two peers — and made a generated page fail its own drift check.
    """
    h = hashlib.sha256()
    h.update(b"nm-v1\n")
    for path in _sources():
        h.update(str(path.relative_to(KIT)).replace("\\", "/").encode())
        h.update(b"\0")
        normalised = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(hashlib.sha256(normalised).hexdigest().encode())
        h.update(b"\n")
    return h.hexdigest()


def assert_absent(check_env: bool = False) -> str:
    """Raise ``Violation`` if any mail surface exists; otherwise return the manifest hash."""
    bad = scan(check_env)
    if bad:
        lines = "\n".join(
            f"  {rule}  {path}:{line}  {what}   ({RULES[rule]})" for rule, path, line, what in bad)
        raise Violation(f"MAIL-ABSENCE VIOLATION\n{lines}")
    return manifest_sha256()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check-env", action="store_true",
                    help="also check installed distributions, not only this source tree")
    args = ap.parse_args()
    try:
        digest = assert_absent(args.check_env)
    except Violation as exc:
        print(exc, file=sys.stderr)
        return 3
    print(f"mail surface: ABSENT  (scan {digest[:8]}, {len(_sources())} files, {len(RULES)} rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
