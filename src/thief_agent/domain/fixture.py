"""The scent fixture: one worked example, used three ways.

The rulebook requires both teams to exchange the emission and decay model
*with a concrete numeric example* before a series opens. This module builds
that example once and it serves three purposes that must not be allowed to
drift apart:

* it is the regression fixture our own tests pin the engine against;
* it is the artefact transmitted at negotiation;
* it is the payload hashed into the pre-series lock.

Generating it from the live engine rather than transcribing it is deliberate,
and it is the opposite of the choice made in the tests. A *test* fixture must
be independent of the implementation or it proves nothing — the book's printed
figures are typed in by hand for exactly that reason. An *exchanged* fixture
must be identical to the implementation, or we hash-lock a promise we do not
keep and are caught at audit by our own opponent. The two roles want opposite
things, so the tests check this artefact against the book's numbers, and the
negotiation sends whatever the engine actually does.

Every value is rounded to the wire's precision. A fixture carrying more
digits than the protocol can transmit would fail comparison against a peer who
implemented the model correctly.
"""

from dataclasses import dataclass

from .board import Position
from .scent import (
    CENTRE_INTENSITY,
    DEFAULT_FALLOFF,
    GRID_SIZE,
    MODELS,
    PRECISION,
    Falloff,
    emission,
)
from .trail import DECAY, Trail

FIXTURE_CENTRE: Position = (2, 2)
"""Centre of the worked example, on a 5x5 board.

Chosen so the emission is not clipped: a fixture whose field is cut off by an
edge would agree with a peer for the wrong reason, since both sides would be
comparing absences rather than values.
"""

FIXTURE_BOARD = 5
FIXTURE_TURNS = 3
"""Turns of decay shown. Enough to distinguish a multiplicative rule from a
subtractive one several times over: 0.81, 0.729, 0.656 against 0.80, 0.70,
0.60."""


@dataclass(frozen=True, slots=True)
class ScentFixture:
    """A worked emission and its decay, as both sides must compute it."""

    model: str
    centre: Position
    board_size: int
    centre_intensity: float
    grid_size: int
    decay_rate: float
    emission: dict[str, float]
    decay_series: tuple[float, ...]

    def as_terms(self) -> dict[str, object]:
        """Flat, JSON-safe form for the negotiation payload."""
        return {
            "model": self.model,
            "centre": list(self.centre),
            "board_size": self.board_size,
            "centre_intensity": self.centre_intensity,
            "grid_size": self.grid_size,
            "decay_rate": self.decay_rate,
            "emission": self.emission,
            "decay_series": list(self.decay_series),
        }


def build(falloff: Falloff = DEFAULT_FALLOFF) -> ScentFixture:
    """Compute the worked example from the live engine.

    Whatever this returns is what we will actually do in a match, which is the
    only property that makes hashing it meaningful.
    """
    name = next((key for key, model in MODELS.items() if model is falloff), "custom")
    field_laid = emission(FIXTURE_CENTRE, FIXTURE_BOARD, falloff=falloff)
    trail = Trail()
    trail.deposit(field_laid)
    series = []
    for _ in range(FIXTURE_TURNS):
        trail.decay()
        series.append(round(trail.intensity_at(FIXTURE_CENTRE), PRECISION))
    return ScentFixture(
        model=name,
        centre=FIXTURE_CENTRE,
        board_size=FIXTURE_BOARD,
        centre_intensity=CENTRE_INTENSITY,
        grid_size=GRID_SIZE,
        decay_rate=DECAY,
        emission={f"{r},{c}": v for (r, c), v in sorted(field_laid.items())},
        decay_series=tuple(series),
    )
