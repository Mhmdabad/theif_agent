"""Everything one sub-game holds, and nothing it does.

The fields live here, in a single ``@dataclass``, and the phases inherit them:
:mod:`.subgame_moves`, :mod:`.subgame_scent`, :mod:`.subgame_commit` and
:mod:`.subgame_audit` each extend this class in turn, and
:class:`~.subgame.SubGame` is the last link. One declaration of the state means
one generated ``__init__``, one ``__eq__`` and one place to read what a
sub-game is made of — the belief in particular stays the single object the
policy targets and the GUI paints.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.actions import Action
from ..domain.axes import AxisConvention
from ..domain.belief import Belief
from ..domain.board import Agent, BoardState
from ..domain.credibility import Credibility
from ..domain.memory import ScentMemory
from ..domain.rules import position_of
from ..infra.ceremony import FinalReveal, MatchCeremony, Reveal
from ..infra.match_log import MatchLog
from ..strategy.base import BrainBase
from .subgame_types import OPPONENT_OF, Peer, Played


@dataclass
class SubGameState:
    """The state of one sub-game: what was agreed, what is held, what was learnt."""

    role: str
    brain: BrainBase
    peer: Peer
    log: MatchLog
    state: BoardState
    axes: AxisConvention
    max_steps: int
    hint_max_words: int = 15
    ceremony: MatchCeremony = field(init=False)
    now: Callable[[], str] = field(default=lambda: "")
    sealed_states: dict[int, BoardState] = field(default_factory=dict, init=False)
    """The board each step was sealed against, kept for the audit.

    Recorded when the step opens, before either side's move is applied. That is
    the state both peers hashed into their commitments, and without it their
    reveals cannot be re-derived from anything — the nonces would arrive and
    prove nothing.
    """

    their_final: FinalReveal | None = field(default=None, init=False)
    received_hints: dict[int, str] = field(default_factory=dict, init=False)
    """Opponent language, retained verbatim and separate from verified scent."""

    credibility: Credibility = field(default_factory=Credibility, init=False)
    """What the opponent's word is currently worth, across this sub-game.

    Held for the sub-game rather than rebuilt per turn, because remembering is
    the whole point: a reliability that reset every step could not remember a
    lie, and an opponent caught once would be trusted again on its next
    sentence. Not an ``init`` argument for the same reason the ceremony is not
    — a caller supplying one would be supplying an opinion about a peer nobody
    has heard from yet.
    """

    require_bound_scent: bool = True
    """Whether a peer must disclose a scent field bound to its commitment.

    **Fail-closed, and the default is the closed side.** Unverifiable scent is
    not weaker evidence than verified scent — it is no evidence wearing the
    appearance of some, and absorbing it would let an opponent steer our belief
    by simply declining to bind what it sends. So a peer that discloses nothing
    checkable fails the audit rather than being quietly excused.

    **Supplied by the caller, from a negotiation.**
    :meth:`~.match.MatchRunner.play_sub_game` reads it off
    :attr:`~..domain.lock.ScentAgreement.require_bound_scent` — the ``binding``
    term of a lock the opponent matched exactly — and refuses to open a sub-game
    at all when no lock was agreed. The default here is what a sub-game
    constructed directly by a test gets, and it is the closed side for the same
    reason the rest of this docstring gives; it is no longer how a match decides.

    Setting this false is the *negotiated* downgrade, and it downgrades to
    **no scent at all** rather than to unverified scent: the reference dialect
    ships its field in the phase-1 turn message, unbound and alongside the
    commitment it would otherwise conceal, and there is no reading of that we
    can accept without giving up both the secrecy of our position and the one
    witness the rulebook calls unfalsifiable. Playing an opponent who speaks
    only that dialect therefore costs the pheromone layer, explicitly, and is
    agreed before the series rather than discovered inside it — which is why the
    lock refuses any other ``binding`` outright rather than accommodating it.
    """

    start: BoardState = field(init=False)
    """The board this sub-game opened on, kept for the scent reconstruction.

    ``state`` moves; the audit needs the position both sides agreed to start
    from, because the whole point of re-deriving the opponent's trail is to do
    it from terms that were fixed before anybody played.
    """

    scent: ScentMemory = field(default_factory=ScentMemory, init=False)
    """What we have emitted, and what we have absorbed — never pooled."""

    belief: Belief = field(init=False)
    """The distribution the policy targets and the live GUI paints.

    One object, not two. A display-only copy would let the picture we show
    diverge from the reasoning we did, which is the one thing the screenshot
    requirement exists to demonstrate.
    """

    play_result: Played | None = field(default=None, init=False)
    """How this sub-game ended, kept so a caller can ask again later.

    ``play()`` returns it too. Keeping it as well means a match runner that
    assembles artefacts after the fact does not have to have held on to the
    return value through a handshake, an audit and a file write.
    """

    def __post_init__(self) -> None:
        self.ceremony = MatchCeremony(role=self.role)
        self.start = self.state
        self.belief = Belief.uniform(self.state)
        self.belief.exclude(position_of(self.state, self._agent(self.role)))

    @property
    def opponent(self) -> str:
        return OPPONENT_OF[self.role]

    _peer_reveals: dict[int, Reveal] = field(default_factory=dict, init=False)
    _our_actions: dict[int, Action] = field(default_factory=dict, init=False)
    """What we actually did each step, kept so the audit can replay the board.

    The opponent's trail is only checkable against a board, and the board only
    exists if *both* histories are known — our barrier at step 4 is what makes
    their move at step 5 legal or not.
    """

    @staticmethod
    def _agent(role: str) -> Agent:
        return "cop" if role == "police" else "thief"
