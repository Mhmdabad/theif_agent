"""Who this peer is: the package it runs as, its role, and its private config.

The three facts that differ between this repository and the sibling one, kept
in one place so the divergence is a statement rather than a scattering.
"""

from pathlib import Path

PACKAGE = "thief_agent"
ROLE = "thief"
CONFIG = Path("config/thief/game.toml")
