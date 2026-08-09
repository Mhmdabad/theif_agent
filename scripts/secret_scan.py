#!/usr/bin/env python3
"""Fail if any git-tracked file looks like it carries a credential (task 0.11).

docs/SECRETS.md and .gitignore keep secrets out of the tree, but neither can
prove a secret was not committed anyway. This gate is that proof: it walks
``git ls-files`` (never the working tree, so local scratch files cannot fail
the build) and rejects both credential-shaped *filenames* and high-signal
secret *content* — OAuth client secrets, private key blocks, AWS access keys,
Google bearer tokens, ngrok authtokens, and hard-coded password assignments.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

# Filename globs mirroring the SECRETS block of .gitignore: a file matching one
# of these has no business being tracked at all, whatever its content.
FORBIDDEN_NAMES: tuple[str, ...] = (
    "credentials.json",
    "token*.json",
    "client_secret*.json",
    "*.pem",
    "*.key",
    ".env",
    "*.env",
    "secrets*",
)

# Content patterns are deliberately high-signal: each requires the shape of a
# real credential value, not just a suspicious word, so prose about secrets
# (docs/SECRETS.md, comments) passes while an actual leak fails. The boolean
# marks patterns loose enough that a placeholder value could trip them; only
# those consult the placeholder allowlist below.
CONTENT_PATTERNS: tuple[tuple[re.Pattern[str], str, bool], ...] = (
    (
        re.compile(r'"client_secret"\s*:\s*"[^"]+"'),
        "Google OAuth client secret (client_secret value)",
        True,
    ),
    (
        re.compile(r"GOCSPX-[0-9A-Za-z_-]{10,}"),
        "Google OAuth client secret (GOCSPX token)",
        True,
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "private key block",
        False,
    ),
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "AWS access key id",
        False,
    ),
    (
        re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"),
        "Google OAuth bearer/refresh token (ya29.)",
        False,
    ),
    (
        re.compile(r"authtoken\S*\s+[0-9a-zA-Z]{20,}_[0-9a-zA-Z]{20,}"),
        "ngrok authtoken",
        False,
    ),
    (
        re.compile(r"""(?i)\b(api_key|apikey|password|passwd|secret)\s*[:=]\s*['"][^'"]{8,}['"]"""),
        "hard-coded credential assignment",
        True,
    ),
)

# Values that look like assignments but are clearly not live secrets: docs and
# tests legitimately show the *shape* of a credential with a placeholder value.
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "example",
    "placeholder",
    "dummy",
    "fake",
    "not-real",
    "not-a-real",
    "your-",
    "your_",
    "<",
    "{",
    "$",
    "...",
)


def tracked_files() -> list[Path]:
    """Paths git considers tracked, so untracked local scratch never fails CI."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True, text=True
    ).stdout
    return [Path(name) for name in out.split("\0") if name]


def name_findings(path: Path) -> list[str]:
    return [
        f"{path.as_posix()}:1: forbidden credential filename (matches {pattern})"
        for pattern in FORBIDDEN_NAMES
        if fnmatch.fnmatch(path.name, pattern)
    ]


def is_placeholder(line: str) -> bool:
    """True when a matched assignment is clearly illustrative, not a live value."""
    lowered = line.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def content_findings(path: Path) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:8192]:  # binary; content patterns are text-only
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern, reason, allow_placeholder in CONTENT_PATTERNS:
            if pattern.search(line) and not (allow_placeholder and is_placeholder(line)):
                findings.append(f"{path.as_posix()}:{number}: {reason}")
    return findings


def main() -> int:
    findings: list[str] = []
    checked = 0
    for path in tracked_files():
        checked += 1
        findings.extend(name_findings(path))
        findings.extend(content_findings(path))

    if findings:
        print(f"{len(findings)} secret finding(s) — rotate anything real, then purge:")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print(f"{checked} tracked files free of credential names and secret content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
