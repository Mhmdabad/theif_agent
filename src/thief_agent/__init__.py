"""THIEF agent - Distributed Cops-and-Robbers over a peer-to-peer network.

This package holds the THIEF (גנב) side only. The COP lives in a separate
repository and must run as a completely separate process under its own config
directory; sharing live state between the two disqualifies the solution.
"""

__all__ = ["__version__", "version"]

__version__ = "0.1.0"


def version() -> str:
    """Return the running code version.

    Declared in the Step-0 hardware/code declaration alongside the GitHub
    commit hash, so the grader can reproduce the exact build that competed.
    """
    return __version__
