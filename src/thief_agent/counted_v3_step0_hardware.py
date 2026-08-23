"""Step-0 V2 hardware wire values and authenticated-domain decoding."""

from __future__ import annotations

import os
import platform
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CPU_FREQ = Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")


def decode_frequency(value: object) -> int | float:
    try:
        frequency = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Step-0 cpu_freq_ghz must decode as Decimal") from None
    if not frequency.is_finite() or frequency <= 0:
        raise ValueError("Step-0 cpu_freq_ghz must be finite and positive")
    if frequency == frequency.to_integral():
        return int(frequency)
    return float(frequency)


def _frequency_wire() -> str:
    raw = os.getenv("COUNTED_CPU_FREQ_GHZ")
    if raw is None:
        try:
            raw = str(Decimal(CPU_FREQ.read_text()) / 1_000_000)
        except (OSError, InvalidOperation):
            raise RuntimeError("COUNTED_CPU_FREQ_GHZ is required on this platform") from None
    decode_frequency(raw)
    return format(Decimal(raw).normalize(), "f")


def collect_hardware() -> dict[str, Any]:
    pages = os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else 0
    size = os.sysconf("SC_PAGE_SIZE") if pages else 0
    return {
        "os": platform.system() or "unknown",
        "cpu_cores": os.cpu_count() or 1,
        "cpu_freq_ghz": _frequency_wire(),
        "ram_gb": round(pages * size / 1024**3) if pages else 0,
        "gpu": False,
    }
