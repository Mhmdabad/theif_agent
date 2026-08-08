"""``declaration_<game_id>.json`` — everything that does not change during a match.

The pre-game declaration is the fixed point the rest of the evidence hangs from.
It names who played, which four repositories the code came from, what hardware
and model ran it, and what token ceiling was agreed — all before a single move,
and all under one signature. Anything asserted afterwards that contradicts it is
contradicting a document both sides accepted before either knew the outcome.

**This module builds the file the two teams share.** :mod:`.step_zero` already
produces our own half — hardware, provenance, signature — which is a statement
about *this machine*. The declaration is a statement about *this match*, and it
carries both.

Three decisions worth stating:

**Everything mandatory is required at construction.** FR-7.28 names four
repository links; the rulebook adds teams and members, MCP addresses, the LLM
model, the token ceiling and the times. A declaration missing any of them is not
a weaker declaration, it is a different document — so it cannot be built. The
error then arrives while somebody is looking at the code that omitted the field,
rather than at the moment two agents try to agree.

**The signature covers the content and not itself.** :func:`content` and
:meth:`MatchDeclaration.to_dict` differ by exactly the signature. Keeping them
apart is what stops a document from being signed over a copy of its own
signature — which verifies, and means nothing.

**`ended_at` is deliberately mutable and unsigned at declaration time.** It is
not knowable before the match, and pretending otherwise would either mean
signing a placeholder or delaying the signature until the evidence it fixes has
already been produced. It is recorded by :meth:`MatchDeclaration.concluded`,
which re-signs — so the final file is signed, and the *pre-game* commitment is
still checkable from the fields that were fixed before play.
"""

from .declaration_parties import DeclarationError, Endpoints, Team
from .declaration_record import MatchDeclaration, declare_match
from .step_zero import Hardware, Provenance

__all__ = [
    "DeclarationError",
    "Endpoints",
    "MatchDeclaration",
    "Team",
    "build",
    "declare_match",
]


def build(
    *,
    game_id: str,
    game_uid: str,
    role: str,
    us: Team,
    them: Team,
    endpoints: Endpoints,
    hardware: Hardware,
    provenance: Provenance,
    llm_model: str,
    token_ceiling: int,
    started_at: str,
    key: str | None = None,
) -> MatchDeclaration:
    """Assemble and sign a declaration in one call."""
    return declare_match(
        MatchDeclaration(
            game_id=game_id,
            game_uid=game_uid,
            role=role,
            us=us,
            them=them,
            endpoints=endpoints,
            hardware=hardware,
            provenance=provenance,
            llm_model=llm_model,
            token_ceiling=token_ceiling,
            started_at=started_at,
        ),
        key,
    )
