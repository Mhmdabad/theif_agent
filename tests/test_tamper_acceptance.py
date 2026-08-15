"""Evidence that the verification runs, rather than always returning green.

A detector nobody has fooled on purpose is a detector nobody has tested. The
whole of the Replay App's authority is one comparison, and a comparison that
had been broken — the wrong field hashed, a canonical form that quietly agreed
with everything, a ``verified=True`` left in after a refactor — would look
exactly like a correct one on every honest log ever produced.

So this file attacks the log. It takes a real one, built by the real writer,
alters **one field at a time by hand**, and requires ``TAMPERED`` every time.
The sweep is exhaustive over the record's fields rather than a spot check,
because "we changed the move and it noticed" leaves open that only the move is
hashed — which is precisely the mistake the illustrative snippet in FR-7.12
would lead someone into.

Two controls stop the sweep from being vacuous:

* :class:`TestTheDetectorIsNotSimplyAlwaysRed` — the untouched log stamps
  ``Verified OK`` through this same harness. Without it, a detector that
  refused everything would pass every test below.
* :class:`TestItJudgesContentNotBytes` — a log rewritten with different JSON
  formatting still stamps clean. Without it, the sweep would also pass for a
  detector that merely noticed the file had been rewritten.

:class:`TestWhatOneSidedVerificationCannotSee` records the limit honestly.
"""

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.infra.match_log import MatchLog
from thief_agent.ui.replay import load
from thief_agent.ui.verdict import Stamp, walk

STEPS = 4

Edit = Callable[[dict[str, Any]], None]


def honest_log(tmp_path: Path, steps: int = STEPS) -> Path:
    """A log the way a real match leaves one: sealed records, real digests."""
    log = MatchLog(game_id="uoh26-s82kma9e", sub_game=2, role="thief")
    for step in range(1, steps + 1):
        board = BoardState(
            grid_size=8,
            cop=(1, step),
            thief=(6, 5),
            barriers=frozenset({(3, 3)}) if step > 1 else frozenset(),
            step=step,
        )
        record = step_record(board, "thief", "N", "truth", f"step {step}")
        secret = f"{step:032x}"
        log.commit(step, commit_of(record, secret))
        log.reveal(step, record)
        log.disclose(step, secret)
    return log.write(tmp_path)


def by_hand(path: Path, edit: Edit) -> Path:
    """Open the file, change something, save. What a text editor would leave."""
    body = json.loads(path.read_text())
    edit(body)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    return path


def stamp_after(tmp_path: Path, edit: Edit) -> Stamp:
    return walk(load(by_hand(honest_log(tmp_path), edit))).stamp


def swapped(value: object) -> object:
    """A different value of the same JSON type, so the edit stays well-formed.

    A change that also broke the *shape* would be caught by the loader, and
    then the test would prove the loader works rather than the digest.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, list):
        return [*value, 0] if value else [0]
    if isinstance(value, dict):
        return {**value, "added": 0}
    if value is None:
        return 0
    raise AssertionError(f"no swap defined for {type(value).__name__}")


class TestTheDetectorIsNotSimplyAlwaysRed:
    """The control. Every test below is meaningless without this one."""

    def test_an_untouched_log_stamps_verified_ok(self, tmp_path: Path) -> None:
        result = walk(load(honest_log(tmp_path)))
        assert result.stamp is Stamp.VERIFIED_OK
        assert result.verified == STEPS

    def test_a_log_rewritten_without_changes_still_stamps_clean(self, tmp_path: Path) -> None:
        """The harness itself re-serialises the file, so it must not be the trigger."""
        assert stamp_after(tmp_path, lambda body: None) is Stamp.VERIFIED_OK


class TestEveryFieldOfTheRecordIsCovered:
    """One field at a time, over the whole record and every step."""

    @pytest.mark.parametrize("field", ["state", "role", "move", "intent", "hint", "barrier_placed"])
    @pytest.mark.parametrize("index", range(STEPS))
    def test_altering_one_field_of_one_step_is_caught(
        self, tmp_path: Path, field: str, index: int
    ) -> None:
        def edit(body: dict[str, Any]) -> None:
            row = body["records"][index]["payload"]
            row[field] = swapped(row[field])

        result = walk(load(by_hand(honest_log(tmp_path), edit)))
        assert result.stamp is Stamp.TAMPERED
        assert result.at_step == index + 1

    @pytest.mark.parametrize("field", ["grid_size", "step", "self", "barriers"])
    def test_altering_one_field_inside_the_board_is_caught(
        self, tmp_path: Path, field: str
    ) -> None:
        """``state`` is nested, so a shallow hash would miss everything in here."""

        def edit(body: dict[str, Any]) -> None:
            board = body["records"][0]["payload"]["state"]
            board[field] = swapped(board[field])

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_adding_a_field_the_committer_never_wrote_is_caught(self, tmp_path: Path) -> None:
        """An addition changes the digest as surely as an alteration does."""

        def edit(body: dict[str, Any]) -> None:
            body["records"][0]["payload"]["note"] = "added later"

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_removing_a_field_is_caught(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            del body["records"][0]["payload"]["hint"]

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED


class TestTheSmallestPossibleAlterations:
    """'Any alteration, however small.' SHA-256 has no near-miss."""

    def test_one_flipped_character_in_a_commitment(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            digest = body["records"][0]["commit"]
            body["records"][0]["commit"] = ("0" if digest[0] != "0" else "1") + digest[1:]

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_one_flipped_character_in_a_nonce(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            secret = body["records"][0]["nonce"]
            body["records"][0]["nonce"] = ("0" if secret[0] != "0" else "1") + secret[1:]

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_one_trailing_space_in_a_hint(self, tmp_path: Path) -> None:
        """The kind of edit somebody could make without noticing they made it."""

        def edit(body: dict[str, Any]) -> None:
            body["records"][0]["payload"]["hint"] += " "

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_one_cell_of_the_barrier_set_moved_by_one(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            body["records"][1]["payload"]["state"]["barriers"][0][0] += 1

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED


class TestRearrangingRatherThanEditing:
    """Moving honest material between steps is still forgery."""

    def test_swapping_two_commitments(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            first, second = body["records"][0], body["records"][1]
            first["commit"], second["commit"] = second["commit"], first["commit"]

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_swapping_two_nonces(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            first, second = body["records"][0], body["records"][1]
            first["nonce"], second["nonce"] = second["nonce"], first["nonce"]

        assert stamp_after(tmp_path, edit) is Stamp.TAMPERED

    def test_replaying_a_whole_earlier_step_under_a_later_number(self, tmp_path: Path) -> None:
        """This is why ``state`` carries the step number: anti-replay.

        The copied row is internally consistent — commitment, record and nonce
        all belong together — so it re-derives perfectly and the digest alone
        has no objection. A detector that stopped at the digest would clear it.
        What gives it away is that the sealed record says step 1 while the log
        files it as step 3.
        """

        def edit(body: dict[str, Any]) -> None:
            copied = deepcopy(body["records"][0])
            copied["step"] = 3
            body["records"][2] = copied

        result = walk(load(by_hand(honest_log(tmp_path), edit)))
        assert result.stamp is Stamp.TAMPERED
        assert result.at_step == 3
        assert "seals step 1" in result.reason

    def test_the_copied_row_re_derives_on_its_own(self, tmp_path: Path) -> None:
        """The point above only means something if the digest really does agree."""

        def edit(body: dict[str, Any]) -> None:
            copied = deepcopy(body["records"][0])
            copied["step"] = 3
            body["records"][2] = copied

        row = load(by_hand(honest_log(tmp_path), edit)).seek(3)
        assert row.reveal is not None and row.nonce is not None
        assert commit_of(row.reveal, row.nonce) == row.commit


class TestItJudgesContentNotBytes:
    """The second control: clean must survive re-formatting."""

    def test_reindented_json_still_stamps_clean(self, tmp_path: Path) -> None:
        path = honest_log(tmp_path)
        path.write_text(json.dumps(json.loads(path.read_text())))
        assert walk(load(path)).stamp is Stamp.VERIFIED_OK

    def test_reordered_keys_still_stamp_clean(self, tmp_path: Path) -> None:
        """JSON objects are unordered; the canonical form sorts before hashing."""
        path = honest_log(tmp_path)
        body = json.loads(path.read_text())
        for row in body["records"]:
            row["payload"] = dict(reversed(list(row["payload"].items())))
        path.write_text(json.dumps(body))
        assert walk(load(path)).stamp is Stamp.VERIFIED_OK


class TestWhatOneSidedVerificationCannotSee:
    """The limit, recorded rather than discovered at an audit.

    Each commitment binds one step to itself. Nothing chains step to step, so
    **removal** is the one edit the arithmetic cannot object to: the steps that
    remain are all genuine and all re-derive.

    Two cases, and they are not equally invisible. A step removed from the
    *middle* leaves a hole in the numbering that a reader can see. A truncated
    *tail* leaves a log indistinguishable from a sub-game that ended early —
    which is a real thing that happens, so it cannot be refused either.

    The defence is not here. It is the two-sided audit: both peers keep their
    own log of the same sub-game, and the opponent still holds the steps that
    went missing from this one. Verification proves a log was not *rewritten*;
    agreement between two logs is what proves one was not *shortened*.
    """

    def test_a_truncated_tail_still_stamps_verified_ok(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            body["records"] = body["records"][:2]

        assert stamp_after(tmp_path, edit) is Stamp.VERIFIED_OK

    def test_it_is_indistinguishable_from_a_short_match(self, tmp_path: Path) -> None:
        """Which is why refusing it is not an option either."""
        path = honest_log(tmp_path)
        truncated = json.loads(path.read_text())
        truncated["records"] = truncated["records"][:2]
        short = json.loads(honest_log(tmp_path / "short", steps=2).read_text())
        assert truncated["records"] == short["records"]

    def test_a_step_removed_from_the_middle_leaves_a_visible_gap(self, tmp_path: Path) -> None:
        """Not caught by the digest, but not silent either."""

        def edit(body: dict[str, Any]) -> None:
            del body["records"][1]

        path = by_hand(honest_log(tmp_path), edit)
        replay = load(path)
        assert walk(replay).stamp is Stamp.VERIFIED_OK
        assert replay.numbers() == [1, 3, 4], "the missing number is on the record"
