"""Resolve and validate the two role repositories used by counted play."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .reference_v3_commits import SHA_PATTERN


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def role_roots() -> dict[str, Path]:
    root = _root()
    project = root.parent
    return {
        role: root if root.name == f"{role}_agent" else project / f"{role}_agent"
        for role in ("police", "thief")
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False, text=True
    )


def role_commits() -> dict[str, str]:
    commits: dict[str, str] = {}
    for role, root in role_roots().items():
        if not root.is_dir():
            raise RuntimeError(f"missing {role} repository beside the current checkout: {root}")
        if (
            _git(root, "diff", "--quiet").returncode
            or _git(root, "diff", "--cached", "--quiet").returncode
        ):
            raise RuntimeError(f"counted play requires a clean tracked {role} checkout")
        commit = _git(root, "rev-parse", "HEAD").stdout.strip().lower()
        if not SHA_PATTERN.fullmatch(commit):
            raise RuntimeError(f"cannot resolve the {role} repository commit")
        commits[role] = commit
    return commits
