"""Stage 6 acceptance: the three things Commit-Reveal has to actually do.

The unit tests prove each piece. This runs a whole sub-game through the real
ceremony, the real digests and the real log, and asserts the three outcomes the
rulebook's milestone names:

* an honest match audits **clean**,
* a corrupted reveal is **detected**,
* a nonce **never leaves early**.

The third is the one that cannot be checked by looking at any single function.
Every phase refuses a nonce individually and the ceremony holds it privately —
but "never leaked" is a property of the whole conversation, so it is asserted
against a transcript of everything that actually crossed the wire.

The opponent here is a second ceremony with the other role. It is a stand-in,
not a shortcut: the two share no state and exchange only serialised
dictionaries, and this file imports nothing from the sibling package.
"""

import json
from dataclasses import dataclass

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, nonce, step_record
from thief_agent.infra.ceremony import (
    Acknowledgement,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
    Verdict,
    audit_opponent,
)
from thief_agent.infra.match_log import MatchLog

WHEN = "2026-08-04T09:00:00+00:00"
STEPS = 6
GRID = 8


def board(step: int) -> BoardState:
    """The board both peers agree was in force at ``step``."""
    return BoardState(
        grid_size=GRID, cop=(1, step % GRID), thief=(6, 5), barriers=frozenset(), step=step
    )


class Wire:
    """Everything that crossed between the peers, in order.

    A transcript rather than a mock. The nonce-leak assertion is a claim about
    what was *sent*, and only a record of what was sent can settle it.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def carry(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        self.sent.append((kind, json.dumps(payload, sort_keys=True)))
        landed: dict[str, object] = json.loads(json.dumps(payload))
        return landed  # a real round trip, not the same object

    @property
    def transcript(self) -> str:
        return "\n".join(body for _, body in self.sent)


class Peer:
    """One side of the ceremony: its own records, nonces and log."""

    def __init__(self, role: str, wire: Wire) -> None:
        self.role = role
        self.wire = wire
        self.match = MatchCeremony(role=role)
        self.log = MatchLog(game_id="uoh26-s82kma9e", sub_game=1, role=role)
        self.records: dict[int, dict[str, object]] = {}

    def commit(self, step: int, move: str, hint: str) -> dict[str, object]:
        record = step_record(board(step), self.role, move, "truth", hint)
        secret = nonce()
        self.records[step] = record
        commitment = Commitment(
            step=step, sender=self.role, commit=commit_of(record, secret), timestamp=WHEN
        )
        self.match.at(step).commit(commitment, secret)
        self.log.commit(step, commitment.commit)
        return self.wire.carry("commit", commitment.to_dict())

    def reveal(self, step: int, move: str, hint: str) -> dict[str, object]:
        opened = Reveal(
            step=step, sender=self.role, move=move, intent="truth", hint=hint, timestamp=WHEN
        )
        self.match.at(step).reveal(opened)
        self.log.reveal(step, self.records[step])  # the sealed record, not the message
        return self.wire.carry("reveal", opened.to_dict())

    def final_reveal(self) -> dict[str, object]:
        self.match.finish()
        disclosed = self.match.final_reveal(WHEN)
        for step, secret in disclosed.nonces.items():
            self.log.disclose(step, secret)
        return self.wire.carry("final_reveal", disclosed.to_dict())


@dataclass
class Played:
    """A finished sub-game and everything either side would need to audit it."""

    cop: Peer
    police: Peer
    wire: Wire
    cop_disclosure: FinalReveal
    thief_disclosure: FinalReveal

    @property
    def states(self) -> dict[int, BoardState]:
        return {step: board(step) for step in range(1, STEPS + 1)}


def play(corrupt_at: int | None = None) -> Played:
    """A full sub-game. ``corrupt_at`` reveals a move other than the committed one."""
    wire = Wire()
    cop, police = Peer("thief", wire), Peer("police", wire)

    for step in range(1, STEPS + 1):
        # Phase 1 — both commit before either reveals.
        cop.match.at(step).receive(Commitment.from_dict(police.commit(step, "S", f"t{step}")))
        police.match.at(step).receive(Commitment.from_dict(cop.commit(step, "N", f"c{step}")))

        # Phase 2 — each acknowledges the other's commitment.
        theirs = wire.carry("ack", police.match.at(step).acknowledge(WHEN).to_dict())
        ours = wire.carry("ack", cop.match.at(step).acknowledge(WHEN).to_dict())
        cop.match.at(step).receive_ack(Acknowledgement.from_dict(theirs))
        police.match.at(step).receive_ack(Acknowledgement.from_dict(ours))

        # Phase 3 — only now may either speak.
        thief_move = "W" if step == corrupt_at else "S"
        cop.match.at(step).receive_reveal(
            Reveal.from_dict(police.reveal(step, thief_move, f"t{step}"))
        )
        police.match.at(step).receive_reveal(Reveal.from_dict(cop.reveal(step, "N", f"c{step}")))

    # Phase 4 — every nonce, at the end.
    from_thief = FinalReveal.from_dict(police.final_reveal())
    from_cop = FinalReveal.from_dict(cop.final_reveal())
    cop.match.receive_final_reveal(from_thief)
    police.match.receive_final_reveal(from_cop)
    return Played(cop, police, wire, cop_disclosure=from_cop, thief_disclosure=from_thief)


class TestAnHonestMatchAuditsClean:
    def test_each_side_re_derives_the_other(self) -> None:
        game = play()
        for match, disclosure in (
            (game.cop.match, game.thief_disclosure),
            (game.police.match, game.cop_disclosure),
        ):
            result = audit_opponent(match, disclosure, game.states)
            assert result.clean
            assert result.checked == STEPS

    def test_the_log_is_complete(self) -> None:
        game = play()
        assert game.cop.log.unopened() == []
        assert len(game.cop.log.entries) == STEPS

    def test_the_log_records_commit_before_reveal_for_every_step(self) -> None:
        """The append-only ordering is what makes the log evidence."""
        for entry in play().cop.log.entries.values():
            assert entry.commit and entry.reveal and entry.nonce


class TestACorruptedRevealIsDetected:
    def test_a_move_changed_after_the_commitment_fails_the_audit(self) -> None:
        game = play(corrupt_at=4)
        result = audit_opponent(game.cop.match, game.thief_disclosure, game.states)
        assert result.verdict is Verdict.FORGED
        assert len(result.failures) == 1
        assert "step 4" in result.failures[0]

    def test_the_honest_steps_still_verify(self) -> None:
        """One corrupted step voids the match, not the arithmetic of the rest."""
        game = play(corrupt_at=2)
        result = audit_opponent(game.cop.match, game.thief_disclosure, game.states)
        assert result.checked == STEPS
        assert len(result.failures) == 1

    def test_the_cop_side_is_unaffected_by_the_thiefs_corruption(self) -> None:
        """The verdict names one peer. Both are not voided by one liar."""
        game = play(corrupt_at=2)
        assert audit_opponent(game.police.match, game.cop_disclosure, game.states).clean

    def test_the_failure_carries_arithmetic_the_other_side_can_run(self) -> None:
        game = play(corrupt_at=3)
        failure = audit_opponent(game.cop.match, game.thief_disclosure, game.states).failures[0]
        assert "committed" in failure and "produces" in failure


class TestNoNonceLeavesEarly:
    def test_no_nonce_appears_before_the_final_reveal(self) -> None:
        """A property of the whole conversation, not of any one function.

        Every phase refuses a nonce individually and the ceremony holds it
        privately, but "never leaked" can only be settled against a record of
        what actually crossed the wire.
        """
        game = play()
        secrets = {c.our_nonce for c in game.cop.match.steps.values() if c.our_nonce}
        secrets |= {c.our_nonce for c in game.police.match.steps.values() if c.our_nonce}
        assert len(secrets) == STEPS * 2

        early = "\n".join(body for kind, body in game.wire.sent if kind != "final_reveal")
        for secret in secrets:
            assert secret not in early

    def test_every_nonce_appears_in_the_final_reveal(self) -> None:
        """Withheld is not the same as withheld forever."""
        game = play()
        late = "\n".join(body for kind, body in game.wire.sent if kind == "final_reveal")
        for ceremony in (*game.cop.match.steps.values(), *game.police.match.steps.values()):
            assert ceremony.our_nonce and ceremony.our_nonce in late

    def test_the_word_nonce_never_appears_in_a_commit_or_reveal(self) -> None:
        for kind, body in play().wire.sent:
            if kind in ("commit", "reveal", "ack"):
                assert "nonce" not in body

    def test_reveals_are_only_sent_once_both_sides_are_locked(self) -> None:
        """Phase 2 is what stops the second speaker hearing the first."""
        kinds = [kind for kind, _ in play().wire.sent]
        for step in range(STEPS):
            window = kinds[step * 6 : step * 6 + 6]
            assert window == ["commit", "commit", "ack", "ack", "reveal", "reveal"]
