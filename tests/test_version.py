"""Smoke tests for the package version reported in Step-0 declarations."""

from thief_agent import __version__, version


def test_version_matches_dunder() -> None:
    assert version() == __version__


def test_version_is_semver_triple() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
