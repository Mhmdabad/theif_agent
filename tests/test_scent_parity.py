"""The two agents must emit, decay, seal and audit scent *identically*.

The cop and the thief may not share a live-state module — doing so disqualifies
the solution — so the pheromone layer is deliberately duplicated in both
repositories and kept in lockstep by hand. ``scripts/check_shared_drift.py``
enforces that in CI against the sibling on GitHub; this enforces it against the
sibling **on disk**, which is the copy actually being edited.

The distinction matters for exactly this feature. A scent change touches seven
shared modules at once, and a change that lands in one repository and not the
other produces two agents that disagree about the field — which surfaces as a
mutual forgery verdict in a counted match, the one failure mode with no appeal
and no partial credit. CI would catch it a push later. This catches it now.

Skipped rather than failed when the sibling is not checked out beside us, so a
clone of one repository alone still has a green suite.
"""

import re
from pathlib import Path

import pytest

SCENT_MODULES = (
    "domain/scent.py",
    "domain/trail.py",
    "domain/memory.py",
    "domain/fixture.py",
    "domain/lock.py",
    "domain/scent_audit.py",
    "domain/belief.py",
    "domain/inference.py",
    "domain/crypto.py",
    "infra/ceremony.py",
    "infra/validation.py",
    "runtime/subgame.py",
)
"""Every module the verified-scent feature reads or writes.

Listed explicitly rather than globbed. A glob would silently start covering
whatever was added next, and the point of the list is that somebody decided
each entry belongs to the shared physics rather than to one side's strategy.
"""

PACKAGE = re.compile(r"\b(thief_agent|cop_agent)\b")

HERE = Path(__file__).resolve().parents[1]
OURS = HERE / "src" / "thief_agent"


def sibling() -> Path | None:
    """The other agent's package, if it is checked out beside this repository."""
    candidate = HERE.parent / "police_agent" / "src" / "cop_agent"
    return candidate if candidate.is_dir() else None


def normalised(path: Path) -> str:
    """The file with the one difference we expect erased: the package name."""
    return PACKAGE.sub("AGENT", path.read_text())


@pytest.fixture(scope="module")
def theirs() -> Path:
    found = sibling()
    if found is None:  # pragma: no cover - only when checked out alone
        pytest.skip("sibling repository not checked out beside this one")
    return found


@pytest.mark.parametrize("module", SCENT_MODULES)
class TestThePheromoneLayerIsIdenticalInBothAgents:
    def test_the_sibling_has_it(self, module: str, theirs: Path) -> None:
        assert (theirs / module).exists(), f"{module} is missing from the sibling"

    def test_it_has_not_drifted(self, module: str, theirs: Path) -> None:
        """Byte-identical once the package name is normalised.

        A drifted scent module is not a cosmetic difference: two peers running
        different physics both audit the other as a forger, and the match is
        void for both sides.
        """
        assert normalised(OURS / module) == normalised(theirs / module), (
            f"{module} differs between the two agents; a shared change has to land in both"
        )


class TestTheDriftManifestKnowsAboutTheNewModule:
    """A module in neither list is unchecked, and unchecked is how drift gets in."""

    def manifest(self) -> str:
        return (HERE / "scripts" / "check_shared_drift.py").read_text()

    def test_the_auditor_is_declared_shared(self) -> None:
        assert '"domain/scent_audit.py"' in self.manifest()

    def test_every_scent_module_is_declared_shared(self) -> None:
        text = self.manifest()
        assert all(f'"{module}"' in text for module in SCENT_MODULES)


class TestTheAgreedFixtureIsTheSameOnBothSides:
    """What the two agents would propose at the pre-series lock must agree.

    Byte-identical source is the cause; an identical hashed agreement is the
    consequence, and it is the consequence a real opponent observes. Recomputed
    here from the sibling's own modules rather than assumed to follow.
    """

    def test_the_binding_term_matches(self, theirs: Path) -> None:
        ours = (OURS / "domain" / "fixture.py").read_text()
        assert 'BINDING = "commit-bound-reveal-v1"' in ours
        sibling_fixture = (theirs / "domain" / "fixture.py").read_text()
        assert 'BINDING = "commit-bound-reveal-v1"' in sibling_fixture

    def test_the_decay_and_centre_come_from_appendix_f_on_both_sides(self, theirs: Path) -> None:
        """A *fixed* parameter drifting is a disqualification found at audit.

        Both sides must read the value from Appendix F rather than repeat it,
        which is the third drift this project has already had: the accessor
        landed on one side only, leaving book values hard-coded on the other.
        """
        for package in (OURS, theirs):
            emission = (package / "domain" / "scent.py").read_text()
            assert '"pheromones", "pheromone_center_intensity"' in emission
            assert '"pheromones", "pheromone_grid_size"' in emission
            assert (
                '"pheromones", "pheromone_decay"' in (package / "domain" / "trail.py").read_text()
            )
