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

from .step_zero_hardware import (
    CPU_MAX_FREQ,
    GPU_ENV,
    VRAM_ENV,
    Hardware,
    _cpu_max_mhz,
    _positive_int,
    _ram_mb,
    collect,
)
from .step_zero_provenance import Provenance, provenance
from .step_zero_signing import (
    UNSIGNED,
    Declaration,
    sign,
    statement,
    verify_signature,
)

__all__ = [
    "CPU_MAX_FREQ",
    "GPU_ENV",
    "SIGNING_KEY_ENV",
    "UNSIGNED",
    "VRAM_ENV",
    "Declaration",
    "Hardware",
    "Provenance",
    "_cpu_max_mhz",
    "_positive_int",
    "_ram_mb",
    "collect",
    "declare",
    "provenance",
    "sign",
    "statement",
    "verify_signature",
]

SIGNING_KEY_ENV = "STEP0_SIGNING_KEY"
"""Where the pre-supplied signing key is read from. **Never a file in this repo.**

The rulebook says the declaration is signed with a key supplied in advance. A
key committed alongside the thing it signs is not a key — anyone with the
repository can forge the signature, which is every team in the cohort, since
these repositories are public. Appendix C also makes "nothing sensitive
anywhere in Git history" a submission gate, and a leaked key is permanent.
"""


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
