"""Everything a match runner holds, and the few facts derived from it.

The fields live here, in a single ``@dataclass``, and the steps inherit them:
:mod:`.match_agreement` and :mod:`.match_play` each extend this class in turn,
and :class:`~.match.MatchRunner` is the last link. One declaration of the state
means one generated ``__init__`` and one place to read what a match is made of.

In particular there is one :attr:`MatchState.peering` attribute, on the runner
itself. Every step reads it off ``self`` at the moment it is used rather than
holding a copy, because a sub-game boundary reassigns it: a value captured
earlier would keep the rest of the series pointing at an address the opponent
has already left, and every test would still pass.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.alternation import role_for
from ..domain.axes import AxisConvention
from ..domain.board import BoardState
from ..domain.lock import ScentAgreement
from ..infra.config_file import LockedConfig, lock
from ..infra.declaration import MatchDeclaration
from ..infra.handshake import Peering
from ..shared.config import series_length
from ..strategy.base import BrainBase
from .match_outcome import SubGameOutcome
from .orchestrator import Orchestrator

__all__ = ["MatchState"]


@dataclass
class MatchState:
    """What a match runner is made of: who it plays, on what, and what it has played."""

    orchestrator: Orchestrator
    declaration: MatchDeclaration
    parameters: dict[str, Any]
    brains: dict[str, BrainBase]
    axes: AxisConvention
    start: BoardState
    max_steps: int
    directory: Path
    now: Callable[[], str] = field(default=lambda: "")
    peering: Peering | None = None
    """The addresses in force, from the opening handshake and re-agreed at each boundary.

    Supplied by the driver rather than negotiated here: trading addresses is
    :meth:`Orchestrator.open_series`, and a runner that opened its own series
    would be a second place the declaration gets written. What the runner owns
    is the *series*, which is why the boundaries between its sub-games are its
    responsibility and this field advances across them.

    ``None`` means no addresses were ever agreed, and :meth:`play_series`
    refuses on it rather than skipping the boundary. Skipping it silently is
    exactly the defect this field exists to close.
    """

    outcomes: list[SubGameOutcome] = field(default_factory=list, init=False)

    scent_lock: ScentAgreement | None = field(default=None, init=False)
    """The pre-series scent model both sides hashed, once :meth:`agree` has run.

    ``None`` until a peer has matched our lock exactly, and not settable from
    outside the runner's construction: a series that never negotiated one has
    nothing to derive its scent rules from, and :meth:`play_sub_game` refuses to
    open on that rather than picking a default. The default is what P1-15 was.
    """

    @property
    def game_id(self) -> str:
        return self.declaration.game_id

    @property
    def sub_games(self) -> int:
        """How long this series is, from the parameters both sides signed.

        Derived rather than accepted, because it used to be accepted: the count
        travelled in from ``--sub-games``, which defaulted to ``1``, and a
        series of one is not a short match — Appendix F table 18 row 1 fixes it
        at six and deviating disqualifies the team. A runner that cannot be
        *told* how long its series is cannot be told wrong.
        """
        return series_length(self.parameters)

    @property
    def role(self) -> str:
        """Our **natural** role: the one played in sub-game 1 and named in the
        declaration. Which role a given sub-game is played in is
        :meth:`role_in` — natural on odd numbers, the opposite on even."""
        return self.orchestrator.role

    def role_in(self, number: int) -> str:
        """The role we play in sub-game ``number``, under the agreed schedule."""
        return role_for(self.role, number)

    def brain_for(self, number: int) -> BrainBase:
        """The brain that plays sub-game ``number`` — chosen by that sub-game's role."""
        return self.brains[self.role_in(number)]

    @property
    def spent_tokens(self) -> int:
        """Rule 54's total: every voice's spend, summed once per distinct voice."""
        voices = {id(brain.voice): brain.voice for brain in self.brains.values()}
        return sum(voice.spent for voice in voices.values())

    def config_for(self, number: int) -> LockedConfig:
        return lock(
            game_id=self.game_id,
            game_uid=self.declaration.game_uid,
            sub_game=number,
            parameters=self.parameters,
            agreed_between=(self.declaration.us.name, self.declaration.them.name),
        )
