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

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
