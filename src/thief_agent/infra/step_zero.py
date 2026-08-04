"""Step-0: what this agent is running on, declared before the first move.

The rulebook's question is one of fairness. Should an agent on a modest laptop
face one on a machine that can run a deep tree search or a heavy language
model on the same terms? The lecturer's answer is a normalisation formula that
**rewards doing well on less**, so the hardware declaration is not paperwork —
it is an input to the score, and understating it would inflate our own result.

That cuts the other way too, and decides the whole design of this module:
**an undetected value is declared as unknown, never as zero.** Python's standard
library cannot see VRAM, and no dependency is worth adding for it. A signed
declaration reading ``"vram_mb": 0`` is a false statement in a document whose
entire purpose is to be true; ``null`` with a stated reason is an honest one.
The same applies to CPU frequency, which is readable on Linux and not portably
anywhere else.

Where the library reports something it cannot really know, the field says so in
its own name. :attr:`Hardware.logical_cores` is ``os.cpu_count()``, which counts
hyperthreads — calling it ``cpu_cores`` would be a number that quietly means
something different on two machines being compared.

Nothing here is collected at import time. Probing hardware is a side effect,
and a module that did it on import would run it during every test collection
and put whatever CI happens to be running on into the declaration.
"""

import hashlib
import hmac
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..shared.config import canonical_bytes

CPU_MAX_FREQ = Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
"""Linux only, in kHz. Absent on macOS and Windows, which is reported as unknown."""

VRAM_ENV = "GPU_VRAM_MB"
"""Supplied by the operator, because the standard library cannot see a GPU.

An environment variable rather than a probe: ``nvidia-smi`` is a dependency on
a vendor and a binary, and being wrong about this field is worse than being
silent about it.
"""

GPU_ENV = "GPU_NAME"


@dataclass(frozen=True, slots=True)
class Hardware:
    """The machine, as far as it can honestly be established.

    Every optional field means *not detected*, and the declaration says so
    rather than filling the gap with a plausible zero.
    """

    os_name: str
    logical_cores: int | None
    cpu_max_mhz: float | None
    ram_mb: int | None
    gpu: str | None
    vram_mb: int | None
    llm_model: str

    def to_dict(self) -> dict[str, Any]:
        """The declaration fragment. Unknowns travel as ``null``."""
        return {
            "os": self.os_name,
            "logical_cores": self.logical_cores,
            "cpu_max_mhz": self.cpu_max_mhz,
            "ram_mb": self.ram_mb,
            "gpu": self.gpu,
            "vram_mb": self.vram_mb,
            "llm_model": self.llm_model,
        }

    @property
    def undetected(self) -> tuple[str, ...]:
        """Which fields could not be established, for the operator to fill in."""
        return tuple(name for name, value in sorted(self.to_dict().items()) if value is None)


def _cpu_max_mhz(path: Path = CPU_MAX_FREQ) -> float | None:
    """Peak CPU frequency in MHz, or ``None`` where it cannot be read."""
    try:
        return int(path.read_text().strip()) / 1000
    except (OSError, ValueError):
        return None


def _ram_mb() -> int | None:
    """Physical memory in MB, or ``None`` on a platform without ``sysconf``."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (AttributeError, ValueError, OSError):
        return None


def _positive_int(raw: str | None) -> int | None:
    """A count from the environment, or ``None`` if it is not one.

    A malformed value is treated as absent rather than raising. The operator
    mistyping a VRAM figure should not stop a match, and an unknown here is
    already an accepted state.
    """
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def collect(llm_model: str, environ: dict[str, str] | None = None) -> Hardware:
    """Probe the machine. Called explicitly, never at import.

    ``llm_model`` is passed in rather than detected: it comes from the private
    config, and the declared model must be the one actually configured rather
    than whichever library happens to be installed.
    """
    source = os.environ if environ is None else environ
    return Hardware(
        os_name=f"{platform.system()} {platform.release()} ({platform.machine()})",
        logical_cores=os.cpu_count(),
        cpu_max_mhz=_cpu_max_mhz(),
        ram_mb=_ram_mb(),
        gpu=source.get(GPU_ENV) or None,
        vram_mb=_positive_int(source.get(VRAM_ENV)),
        llm_model=llm_model,
    )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which code played, for which team, in which sub-game.

    The rulebook's reason for the commit hash is reconstruction: teams may
    change their code between matches, so every match declares the exact commit
    it ran, and the examiner can check out that commit and replay. A hash that
    does not describe what actually ran defeats the whole clause.

    Which is why :attr:`dirty` exists. ``git rev-parse HEAD`` answers happily
    while the working tree has uncommitted changes, and the answer is then a
    commit that is **not** the code being executed. That is not a small
    inaccuracy in a signed document — it is a declaration nobody can verify,
    and it is the easy mistake to make five minutes before a match.
    """

    code_version: str
    group_name: str
    sub_game: int
    github_commit: str | None
    dirty: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_version": self.code_version,
            "group_name": self.group_name,
            "sub_game": self.sub_game,
            "github_commit": self.github_commit,
            "working_tree_dirty": self.dirty,
        }

    @property
    def reproducible(self) -> bool:
        """Whether the examiner could check this commit out and get this code."""
        return self.github_commit is not None and not self.dirty

    def __str__(self) -> str:
        if self.reproducible and self.github_commit:
            return f"{self.group_name} sub-game {self.sub_game} at {self.github_commit[:12]}"
        reason = "uncommitted changes" if self.dirty else "no commit hash available"
        return (
            f"{self.group_name} sub-game {self.sub_game}: NOT REPRODUCIBLE ({reason}); "
            "the declared commit does not describe the code that ran"
        )


def _git(*args: str, repo: Path | None = None) -> str | None:
    """Run a git command, or ``None`` if git or the repository is absent.

    Absent is a real state: a submitted tarball has no ``.git``, and an agent
    that refused to start there would be unrunnable exactly where the examiner
    runs it.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def provenance(
    code_version: str,
    group_name: str,
    sub_game: int,
    repo: Path | None = None,
) -> Provenance:
    """Establish which code is running, and whether that can be proven.

    ``dirty`` is determined by ``git status --porcelain`` rather than inferred.
    An empty result means the tree matches the commit; anything else means the
    hash describes something other than what is executing.
    """
    commit = _git("rev-parse", "HEAD", repo=repo)
    status = _git("status", "--porcelain", repo=repo)
    return Provenance(
        code_version=code_version,
        group_name=group_name,
        sub_game=sub_game,
        github_commit=commit,
        dirty=bool(status),
    )


SIGNING_KEY_ENV = "STEP0_SIGNING_KEY"
"""Where the pre-supplied signing key is read from. **Never a file in this repo.**

The rulebook says the declaration is signed with a key supplied in advance. A
key committed alongside the thing it signs is not a key — anyone with the
repository can forge the signature, which is every team in the cohort, since
these repositories are public. Appendix C also makes "nothing sensitive
anywhere in Git history" a submission gate, and a leaked key is permanent.
"""

UNSIGNED = "unsigned"
"""What a declaration says when no key was available. Not an empty signature."""


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole Step-0 statement, and its signature.

    Signed over the **canonical bytes** of the declaration, using the same
    serialisation as every other digest in the system. A signature over
    ``str(dict)`` would verify only against a peer running the same Python
    version, which is a compatibility bug that looks like a forgery.
    """

    hardware: Hardware
    provenance: Provenance
    signature: str

    @property
    def signed(self) -> bool:
        """Whether this declaration can actually be checked by anyone."""
        return self.signature != UNSIGNED

    def to_dict(self) -> dict[str, Any]:
        return {**statement(self.hardware, self.provenance), "signature": self.signature}


def statement(hardware: Hardware, provenance: Provenance) -> dict[str, Any]:
    """The declaration's content — everything the signature covers.

    Separate from :meth:`Declaration.to_dict` on purpose: what is signed and
    what is sent differ by exactly the signature, and a function that returned
    both would eventually be used to sign a document containing its own
    signature.
    """
    return {"hardware": hardware.to_dict(), "provenance": provenance.to_dict()}


def sign(content: dict[str, Any], key: str | None) -> str:
    """HMAC-SHA256 over the canonical bytes, or :data:`UNSIGNED`.

    HMAC rather than a bare hash: a plain ``sha256`` of a public document is
    something anybody can compute, so it would authenticate nothing while
    looking exactly like a signature.

    A missing key yields :data:`UNSIGNED` rather than an empty string or a
    signature over an empty key. Both of those are values that *verify*, and a
    declaration that verifies against a key nobody holds is worse than one that
    says plainly it was never signed.
    """
    if not key:
        return UNSIGNED
    return hmac.new(key.encode("utf-8"), canonical_bytes(content), hashlib.sha256).hexdigest()


def declare(
    hardware: Hardware, provenance: Provenance, environ: dict[str, str] | None = None
) -> Declaration:
    """Assemble and sign the Step-0 declaration."""
    source = os.environ if environ is None else environ
    content = statement(hardware, provenance)
    return Declaration(
        hardware=hardware,
        provenance=provenance,
        signature=sign(content, source.get(SIGNING_KEY_ENV)),
    )


def verify_signature(declared: dict[str, Any], key: str | None) -> bool:
    """Re-derive a declaration's signature and compare in constant time.

    Used against the **opponent's** declaration, where the timing channel is
    real: their signature is a secret-keyed value we are comparing against one
    we computed, and that is exactly the comparison ``==`` should never make.
    """
    claimed = declared.get("signature")
    if not isinstance(claimed, str) or claimed == UNSIGNED:
        return False
    content = {name: declared.get(name) for name in ("hardware", "provenance")}
    return hmac.compare_digest(sign(content, key), claimed)
