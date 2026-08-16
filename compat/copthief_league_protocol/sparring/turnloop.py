"""One sub-game: seal, push, receive, adjudicate.

Two choices in here are worth naming, because a team building its own peer will hit both.

**The timestamp rides on the message but is not inside the sealed payload.** SPEC section 3 is
explicit that the payload schema is not an interop constraint — each side reveals its own records
and the other just re-hashes them — so keeping wall-clock out of the preimage costs nothing and
buys a seeded run that reproduces byte-for-byte. That reproducibility is what makes the golden
test able to detect behavioural drift.

**The thief moves first.** The book does not settle turn order anywhere in its binding table,
but the reference implementation does — its runtime takes the thief's turn before entering the
receive loop, observed live against it — and a peer declaring ``wire_shape: reference-v3`` must
play what it names. (This module shipped police-first, sourced from ``commit_order:
police_first`` — which lives in the *bookletter-v3* registration, a different wire. The
2026-08-04 dogfood run paid for that with a mutual deadlock after a fully successful handshake.)
The order is printed in the banner; a pair that has not stated it explicitly should — the
wire_shape lock does not cover it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from sparring import kitref
from sparring.audit import AuditResult, audit_records, skipped
from sparring.deadlines import Budgets, Clock, DeadlineTracker
from sparring.inbox import Equivocation, Inbox, ProtocolViolation
from sparring.policies.base import Observation
from sparring.policies.hints import TRUTH, TemplateHintProvider
from sparring.proto.messages import AuditPayload, TurnMessage
from sparring.rules.board import Board
from sparring.rules.engine import IllegalMove, SubGameEngine
from sparring.rules.outcome import Outcome, Role
from sparring.state import IllegalTransition, PeerState, PeerStateMachine


@dataclass
class SubGameResult:
    sub_game_number: int
    role: Role
    outcome: Outcome
    steps: int
    records: list[dict] = field(default_factory=list)
    our_audit: AuditResult | None = None
    opponent_records: int = 0
    note: str = ""

    @property
    def final_commit(self) -> str:
        return self.records[-1]["commit"] if self.records else ""


class SubGamePeer:
    """One side of one sub-game. Fresh per sub-game — never carried over."""

    def __init__(self, *, cfg, role: Role, sub_game_number: int, policy, transport,
                 clock: Clock, budgets: Budgets, seed: int) -> None:
        self.cfg = cfg
        self.role = role
        self.n = sub_game_number
        self.policy = policy
        self.transport = transport
        self.budgets = budgets
        self.rng = random.Random(f"{seed}:{sub_game_number}:{role.value}")
        self.machine = PeerStateMachine()
        self.clock = clock
        self.deadline = DeadlineTracker(clock)
        self.inbox = Inbox(window=budgets.inbound_buffer_limit)
        self.hints = TemplateHintProvider(cfg.board_size, cfg.hint_max_words, cfg.hint_lang,
                                          cfg.lie_rate)
        from sparring.rules.scent import Trail
        start = cfg.cop_start if role is Role.POLICE else cfg.thief_start
        self.engine = SubGameEngine(
            board=Board(cfg.board_size), role=role, position=tuple(start),
            trail=Trail(cfg.scent_model, cfg.board_size, field_size=cfg.smell_grid_size,
                        emit_intensity=cfg.emit_intensity, decay_per_step=cfg.decay_per_step,
                        min_center_intensity=cfg.min_center_intensity),
            max_steps=cfg.max_steps, survival_threshold=cfg.survival_threshold,
            barriers_max=cfg.barriers_max)
        self.records: list[dict] = []
        self.step = 0
        self.outcome: Outcome | None = None
        self.last_hint: str | None = None
        self.hint_cap_noted = False
        #: The thief's obligatory answer to a capture claim, waiting to ride the next message
        #: out. It has to actually travel: the cop cannot see the board, so an answer computed
        #: and discarded means the cop can never learn it captured anyone, and the sub-game runs
        #: to the step ceiling and settles as a timeout that nobody caused.
        self.pending_answer: dict | None = None
        #: The cell we last CLAIMED (police only) — what lets a caught=true be classified:
        #: echoing this cell is an ANSWER to our claim; naming any other cell is a CONCESSION
        #: (rules 46/47, a fact only the thief can see). The two settle identically and audit
        #: differently: a concession pays the thief 5 where a zeroed row pays 0, so it is the
        #: half that must be corroborated rather than believed (issue #37 refinement).
        self.last_claim: list | None = None
        #: A concession we settled on, held for the audit to corroborate against our OWN
        #: barrier record and the thief's revealed final position.
        self.conceded: dict | None = None
        #: The cell of an ANSWERED capture we settled on — held for the audit's other half
        #: (imreeyal's F-2): a false answer echoing our own claim pays the thief 5 AND us 20,
        #: so both peers profit and neither can be left to catch it. The audit checks the
        #: thief's revealed trail actually ends where the answer said it was caught.
        self.answered_at: list | None = None

    # --- sealing ---------------------------------------------------------------------------

    def _nonce(self) -> str:
        """Seeded, so self-play reproduces. A peer facing a real opponent uses `secrets`.

        Predictable nonces are fine here and only here: the commitments protect against an
        opponent reverse-engineering a move before it is revealed, and in self-play both sides
        are us. `cli serve` uses random nonces.
        """
        return f"{self.rng.getrandbits(128):032x}"

    def _seal(self, payload: dict) -> dict:
        nonce = self._nonce()
        record = {"payload": payload, "nonce": nonce, "commit": kitref.commit(payload, nonce)}
        self.records.append(record)
        return record

    def seal_step_zero(self, group_name: str) -> dict:
        """The signed declaration the book asks for before the first move (ch.5, rules 24/53)."""
        from sparring import CODE_VERSION
        return self._seal({
            "step": 0, "type": "system_spec", "sub_game_number": self.n,
            "group_name": group_name, "model": "template", "code_version": CODE_VERSION,
            "num_games_declared": 0,
            "spec": {"os": "any", "cpu_type": "unspecified", "cpu_cores": 0, "ram_gb": 0,
                     "gpu_type": "none", "vram_gb": 0},
        })

    # --- one half-turn ---------------------------------------------------------------------

    def take_turn(self) -> TurnMessage:
        self.machine.to(PeerState.COMPUTING_MOVE)
        self.step += 1
        self.engine.step = self.step

        obs = Observation(
            role=self.role.value, step=self.step, self_pos=self.engine.position,
            board_size=self.cfg.board_size, barriers=tuple(self.engine.barriers),
            legal_moves=tuple(self.engine.legal_moves()),
            barrier_targets=tuple(self.engine.barrier_targets()),
            barriers_left=self.cfg.barriers_max - self.engine.barriers_placed,
            steps_left=max(0, self.cfg.max_steps - self.step),
            rival_scent=dict(self.engine.rival_scent), last_hint=self.last_hint)
        action = self.policy.decide(obs, self.rng)

        if action.barrier is not None:
            self.engine.place_own_barrier(tuple(action.barrier))
        self.engine.apply_own_move(action.move)

        intent = self.hints.choose_intent(self.rng)
        hint = self.hints.hint(self.engine.position, intent, self.n, self.rng)
        field_now = self.engine.trail.full_turn(self.engine.position)

        self.machine.to(PeerState.COMMITTING)
        record = self._seal({
            "step": self.step, "role": self.role.value, "sub_game": self.n,
            "state": self.engine.state_string(), "position": list(self.engine.position),
            "move": action.move, "intent": intent, "hint": hint,
            "verdict": "placed_barrier" if action.barrier else "moved",
        })

        claim = list(self.engine.position) if self.role is Role.POLICE else None
        if claim is not None:
            self.last_claim = claim
        message = TurnMessage(
            step=self.step, sender=self.role.value, commit=record["commit"], hint=hint,
            timestamp=self.clock.stamp(),
            smell_grid=field_now,
            barrier_placed=list(action.barrier) if action.barrier else None,
            capture_claim=claim,
            # The answer we owe from their last claim rides out now. Under hidden positions the
            # cop learns the result of its claim only from this field.
            claim_response=self.pending_answer,
            # Survival is *claimed*, not inferred: the cop cannot count our steps for us, so a
            # thief that reaches the threshold and says nothing leaves the cop waiting for a turn
            # that will never come.
            win_claim=({"type": "survival"} if self.engine.survived() else None),
        )
        self.pending_answer = None
        self.machine.to(PeerState.AWAITING_REVEAL)
        return message

    def terminal_message(self) -> TurnMessage | None:
        """One last sealed record carrying whatever we still owe, after the game ended for us.

        Without it a thief that sees its own capture returns immediately and never delivers the
        answer, so the cop — which cannot see the board — waits out its budget and settles a
        sub-game it actually won as a timeout. Both sides then describe the same game
        differently, which is the shape App. E rule 35 zeroes.

        The action is ``STAY``, which is always legal, so the record chain stays consistent and
        the opponent's audit still reproduces every commit.
        """
        concession = None
        if self.engine.self_captured() is not None:
            # Rules 46/47 end the game at a position ONLY WE can see — a barrier on our own
            # cell, or no orthogonal escape — so the final must SAY so or the cop waits out
            # its budget and the two sides settle one game two ways (issue #37: reproduced
            # over live HTTP, deterministic at seeds 4242/777, fork at sub-game 3). The
            # concession is the league's existing vocabulary, not an extension: caught=true
            # naming OUR OWN final cell — distinct from an ANSWER, which echoes the cell the
            # cop claimed. The cop's settlement switch has accepted this form all along
            # (adjudicate below); this peer just never sent it.
            concession = {"claim": [int(self.engine.position[0]),
                                    int(self.engine.position[1])], "caught": True}
        if concession is None and self.pending_answer is None and not self.engine.survived():
            return None
        self.step += 1
        self.engine.step = self.step
        record = self._seal({
            "step": self.step, "role": self.role.value, "sub_game": self.n,
            "state": self.engine.state_string(), "position": list(self.engine.position),
            "move": "STAY", "intent": TRUTH, "hint": "", "verdict": "settled",
        })
        message = TurnMessage(
            step=self.step, sender=self.role.value, commit=record["commit"], hint="",
            timestamp=self.clock.stamp(),
            # The terminal step is a real turn (STAY), so the field advances with it — the
            # reference's own send path does the same on a caught final. Sending {} here
            # reads, to a strict physics checker, as a scent field that vanished for one
            # step (dogfood finding 4); {} is the not-transmitted convention, not "done".
            smell_grid=self.engine.trail.full_turn(self.engine.position),
            # The concession supersedes a stale answer: both are caught-verdicts, but only the
            # concession is true of the position this final seals — and it is the one worth
            # five points, so it is the one the audit corroborates (audit.py).
            claim_response=concession or self.pending_answer,
            win_claim=({"type": "survival"} if self.engine.survived() else None))
        self.pending_answer = None
        return message

    def receive(self, raw: dict) -> list[TurnMessage]:
        """Hand an inbound message to the receiver contract; get back what is ready to apply."""
        ready = self.inbox.offer(raw)
        applied: list[TurnMessage] = []
        for message in ready:
            msg = TurnMessage.from_wire(message)
            if msg.barrier_placed is not None and msg.sender != Role.POLICE.value:
                # Only the cop places barriers (book ch.3). A thief-sent barrier entering our
                # physics would corrupt the shared board — anrbj666's A3; refuse it loudly.
                raise ProtocolViolation(
                    f"a barrier arrived from sender {msg.sender!r} — only the cop places "
                    f"barriers, so this message is not a legal turn of either role")
            self.engine.observe_barrier(msg.barrier_placed)
            self.engine.observe_scent(msg.smell_grid)
            if (msg.hint and len(msg.hint.split()) > self.cfg.hint_max_words
                    and not self.hint_cap_noted):
                # The cap is the SENDER's rule (book ch.6); the receiver records the breach as
                # evidence rather than ending an honest game over prose (anrbj666's E14). Once
                # per sub-game — a chatty opponent should not flood our own console.
                self.hint_cap_noted = True
                print(f"  note: opponent hint exceeds the signed cap "
                      f"({len(msg.hint.split())} words > {self.cfg.hint_max_words}) — recorded, "
                      f"not enforced; their rule to keep")
            self.last_hint = msg.hint
            applied.append(msg)
        return applied

    def answer(self, msg: TurnMessage) -> dict | None:
        """Compute the honest answer AND queue it for the wire.

        Answering truthfully is required (App. E rules 21-22) and is also the cheapest move
        available: the sealed ``state`` string in our own records carries our position, so a
        denial is contradicted by our own revealed log at the audit.
        """
        answer = self.engine.answer_capture_claim(msg.capture_claim)
        if answer is not None:
            self.pending_answer = answer
        return answer

    def adjudicate(self, incoming: TurnMessage, answer: dict | None) -> Outcome | None:
        """Decide only from what this side is entitled to know.

        Note how little that is for the cop: it cannot see the thief, so every terminal condition
        reaches it as something the thief *said* — an answered capture claim, or a survival claim.
        The thief, by contrast, sees its own capture directly (a barrier on its cell, or no legal
        move) because those are facts about its own position.
        """
        self_caught = self.engine.self_captured()
        if self_caught is not None:
            return self_caught
        if answer is not None and answer.get("caught"):
            return Outcome.CAPTURE
        if incoming.claim_response is not None and incoming.claim_response.get("caught"):
            # ANSWER or CONCESSION? An answer echoes the cell WE claimed; a concession names
            # the thief's own cell (rules 46/47 — an ending only it can see). Both settle
            # CAPTURE now, exactly as before — and BOTH are held for the audit, because both
            # pay: a false concession is worth 5 over the zeroed row (imreeyal's refinement),
            # and a false answer is worth 5 to them AND 20 to us (their F-2 — echoing our own
            # claimed cell was the way around the concession check, and it is the lie both
            # peers profit from). The settle stays fast; the checking is structural.
            if self.role is Role.POLICE:
                if incoming.claim_response.get("claim") != self.last_claim:
                    self.conceded = dict(incoming.claim_response)
                else:
                    self.answered_at = list(self.last_claim or [])
            return Outcome.CAPTURE
        if incoming.win_claim and incoming.win_claim.get("type") == "survival":
            return Outcome.SURVIVAL
        if self.engine.survived():
            return Outcome.SURVIVAL
        if self.step >= self.cfg.max_steps and self.role is Role.THIEF:
            return Outcome.SURVIVAL
        return None

    # --- settlement ------------------------------------------------------------------------

    def send_audit(self, result_claim: str) -> AuditPayload:
        """Reveal our records and nonces. Split from verification on purpose.

        The audit is a genuine *exchange*: both sides must have revealed before either can
        verify. Doing send-then-poll in one call means whoever goes first polls an empty inbox
        and records a skipped audit — a peer that then reports "verified" for its own side and
        nothing for the other looks, from the artifacts, exactly like a peer whose opponent went
        silent.
        """
        mine = AuditPayload(sender=self.role.value, records=self.records,
                            result_claim=result_claim)
        self.transport.send_audit(mine.to_wire())
        return mine

    def _audit(self, theirs: dict) -> AuditResult:
        """The armed form: integrity + binding against what we actually received in play +
        physics under the signed terms (SPEC §3; anrbj666's A1-A3) — and, when we settled on
        a rule-46/47 concession, corroboration of that concession against our OWN barrier
        record and the position trail the thief itself revealed."""
        return audit_records(AuditPayload.from_wire(theirs).records,
                             played=self.inbox.played,
                             board_size=self.cfg.board_size,
                             barriers_max=self.cfg.barriers_max,
                             max_steps=self.cfg.max_steps,
                             concession=self.conceded,
                             answered_at=self.answered_at,
                             own_barriers=[list(b) for b in self.engine.barriers])

    def verify_audit(self) -> AuditResult:
        """Re-hash whatever the opponent revealed, with OUR serializer."""
        theirs = self.transport.poll_audit()
        if theirs is None:
            return skipped()
        return self._audit(theirs)

    def verify_audit_if_ready(self) -> AuditResult | None:
        """Poll-friendly form: None while the opponent has not revealed yet.

        Against a live peer the reveal arrives when it arrives, so the caller waits on its own
        budget rather than recording a skipped audit the moment the inbox happens to be empty.
        """
        theirs = self.transport.poll_audit()
        if theirs is None:
            return None
        return self._audit(theirs)

    def fail(self, note: str) -> Outcome:
        self.machine.fail()
        self.outcome = Outcome.TECHNICAL_LOSS
        return self.outcome


__all__ = ["SubGamePeer", "SubGameResult", "Equivocation", "ProtocolViolation", "IllegalMove",
           "IllegalTransition", "TRUTH"]
