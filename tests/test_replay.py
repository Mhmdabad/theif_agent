"""Loading a recorded sub-game, which is where the log stops being trusted."""

import json
from pathlib import Path

import pytest

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.infra.match_log import MatchLog
from thief_agent.ui.replay import Replay, ReplayError, check_step, load

OPENED = {"move": "N", "intent": "lie", "hint": "heading uptown", "barrier_placed": None}


def written(tmp_path: Path, steps: int = 4, unopened: int = 0) -> Path:
    """A real log, produced by the writer the reader has to agree with."""
    log = MatchLog(game_id="uoh26-s82kma9e", sub_game=2, role="thief")
    for step in range(1, steps + 1):
        log.commit(step, f"{step:064x}")
        log.reveal(step, OPENED)
        if step <= steps - unopened:
            log.disclose(step, f"{step:032x}")
    return log.write(tmp_path)


def edited(tmp_path: Path, change: object) -> Path:
    """A log hand-edited after it was written, as a text editor would leave it."""
    path = written(tmp_path)
    body = json.loads(path.read_text())
    if callable(change):
        change(body)
    path.write_text(json.dumps(body))
    return path


class TestItLoadsWhatTheWriterWrote:
    def test_a_real_log_round_trips(self, tmp_path: Path) -> None:
        """The reader and the writer must agree, or neither is worth having."""
        replay = load(written(tmp_path))
        assert replay.numbers() == [1, 2, 3, 4]
        assert replay.game_id == "uoh26-s82kma9e"
        assert replay.sub_game == 2
        assert replay.role == "thief"

    def test_each_step_carries_its_three_slots(self, tmp_path: Path) -> None:
        first = load(written(tmp_path)).current
        assert first.step == 1
        assert first.commit == f"{1:064x}"
        assert first.reveal == OPENED
        assert first.openable

    def test_a_step_with_no_nonce_is_loaded_and_flagged(self, tmp_path: Path) -> None:
        """A mid-match log is a real thing to open, not an error."""
        replay = load(written(tmp_path, unopened=2))
        assert replay.seek(4).nonce is None
        assert not replay.seek(4).openable
        assert replay.seek(1).openable


class TestNavigation:
    def test_it_starts_at_the_first_step(self, tmp_path: Path) -> None:
        replay = load(written(tmp_path))
        assert replay.current.step == 1
        assert replay.at_start and not replay.at_end

    def test_forward_and_back(self, tmp_path: Path) -> None:
        replay = load(written(tmp_path))
        assert replay.forward().step == 2
        assert replay.forward().step == 3
        assert replay.back().step == 2

    def test_it_clamps_at_the_end_rather_than_wrapping(self, tmp_path: Path) -> None:
        """A reader holding a key down wants to stay, not be thrown to the start."""
        replay = load(written(tmp_path))
        for _ in range(20):
            replay.forward()
        assert replay.current.step == 4
        assert replay.at_end

    def test_it_clamps_at_the_start(self, tmp_path: Path) -> None:
        replay = load(written(tmp_path))
        for _ in range(20):
            replay.back()
        assert replay.current.step == 1

    def test_seeking_a_step_that_exists(self, tmp_path: Path) -> None:
        assert load(written(tmp_path)).seek(3).step == 3

    def test_seeking_a_step_that_does_not_is_named_not_clamped(self, tmp_path: Path) -> None:
        """A reader asking for step 12 of a four-step game has misread something."""
        with pytest.raises(ReplayError, match=r"step 12 is not in this log"):
            load(written(tmp_path)).seek(12)


class TestItRefusesWhatItCannotVouchFor:
    def test_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ReplayError, match="cannot read"):
            load(tmp_path / "absent.json")

    def test_a_file_that_is_not_json(self, tmp_path: Path) -> None:
        path = tmp_path / "log_g_g01.json"
        path.write_text("{ not json")
        with pytest.raises(ReplayError, match="is not JSON"):
            load(path)

    def test_a_json_document_that_is_not_a_log(self, tmp_path: Path) -> None:
        path = tmp_path / "log_g_g01.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(ReplayError, match="not a match log object"):
            load(path)

    def test_a_log_with_no_steps_list(self, tmp_path: Path) -> None:
        path = tmp_path / "log_g_g01.json"
        path.write_text('{"game_id": "g"}')
        with pytest.raises(ReplayError, match="no 'steps' list"):
            load(path)

    def test_an_empty_sub_game(self, tmp_path: Path) -> None:
        path = tmp_path / "log_g_g01.json"
        path.write_text('{"game_id": "g", "steps": []}')
        with pytest.raises(ReplayError, match="no steps cannot be replayed"):
            load(path)

    def test_a_step_missing_a_slot(self, tmp_path: Path) -> None:
        """A silently skipped step would let Verified OK be stamped on a hole."""
        path = edited(tmp_path, lambda body: body["steps"][2].pop("commit"))
        with pytest.raises(ReplayError, match=r"missing \['commit'\]"):
            load(path)

    def test_a_deleted_step_leaves_a_gap_that_is_allowed_but_visible(self, tmp_path: Path) -> None:
        """Numbering is checked for order and repeats, not for completeness.

        A gap is a real possibility in a match that ended early, so it loads —
        and the step numbers are on the record for a reader to notice.
        """
        path = edited(tmp_path, lambda body: body["steps"].pop(1))
        assert load(path).numbers() == [1, 3, 4]

    def test_steps_out_of_order(self, tmp_path: Path) -> None:
        path = edited(tmp_path, lambda body: body["steps"].reverse())
        with pytest.raises(ReplayError, match="out of order"):
            load(path)

    def test_a_repeated_step_number(self, tmp_path: Path) -> None:
        path = edited(tmp_path, lambda body: body["steps"].append(dict(body["steps"][0])))
        with pytest.raises(ReplayError, match="repeats a step number"):
            load(path)

    def test_a_non_integer_step_number(self, tmp_path: Path) -> None:
        path = edited(tmp_path, lambda body: body["steps"][0].update(step="one"))
        with pytest.raises(ReplayError, match="non-integer step number"):
            load(path)

    def test_a_step_that_is_not_an_object(self, tmp_path: Path) -> None:
        path = edited(tmp_path, lambda body: body["steps"].__setitem__(0, "nope"))
        with pytest.raises(ReplayError, match="is not an object"):
            load(path)

    def test_a_commitment_that_is_not_a_string(self, tmp_path: Path) -> None:
        path = edited(tmp_path, lambda body: body["steps"][0].update(commit=42))
        with pytest.raises(ReplayError, match="has no commitment"):
            load(path)


class TestStructureIsNotHonesty:
    def test_a_tampered_but_well_formed_log_loads_fine(self, tmp_path: Path) -> None:
        """Separating the two questions is what lets the verdict mean something.

        A file that will not load is broken; a file that loads and fails
        verification is tampered. Collapsing them would report somebody's disk
        error as somebody's fraud.
        """
        path = edited(tmp_path, lambda body: body["steps"][1].update(commit="f" * 64))
        replay = load(path)
        assert replay.numbers() == [1, 2, 3, 4]
        assert replay.seek(2).commit == "f" * 64

    def test_loading_says_nothing_about_verification(self, tmp_path: Path) -> None:
        assert not hasattr(load(written(tmp_path)), "verdict")


class TestTheReplayObject:
    def test_a_replay_with_no_steps_is_refused_at_construction(self) -> None:
        with pytest.raises(ReplayError, match="no steps cannot be replayed"):
            Replay(game_id="g", sub_game=1, role="thief", steps=())


def sealed_log(tmp_path: Path, steps: int = 3, corrupt: int | None = None) -> Path:
    """A log built the way a real match builds one: sealed records, real digests."""
    log = MatchLog(game_id="uoh26-s82kma9e", sub_game=2, role="thief")
    for step in range(1, steps + 1):
        board = BoardState(
            grid_size=8, cop=(1, step), thief=(6, 5), barriers=frozenset(), step=step
        )
        record = step_record(board, "thief", "N", "truth", f"step {step}")
        secret = f"{step:032x}"
        log.commit(step, commit_of(record, secret))
        log.reveal(step, {**record, "move": "S"} if step == corrupt else record)
        log.disclose(step, secret)
    return log.write(tmp_path)


class TestTheLogCanVerifyItself:
    def test_an_honest_step_re_derives(self, tmp_path: Path) -> None:
        """The whole authority of the Replay App is this arithmetic."""
        replay = load(sealed_log(tmp_path))
        assert check_step(replay.current).verified

    def test_the_log_stores_what_was_sealed_not_what_was_sent(self, tmp_path: Path) -> None:
        """A wire Reveal carries sender/step/timestamp; the digest covers
        state/role/move/intent/hint/barrier_placed. Storing the message would
        make every honest step recompute to a different digest."""
        stored = load(sealed_log(tmp_path)).current.reveal
        assert stored is not None
        assert set(stored) == {"state", "role", "move", "intent", "hint", "barrier_placed"}
        assert "timestamp" not in stored

    def test_every_step_of_an_honest_log_verifies(self, tmp_path: Path) -> None:
        replay = load(sealed_log(tmp_path, steps=5))
        assert all(check_step(step).verified for step in replay.steps)

    def test_an_edited_record_cannot_be_made_to_agree(self, tmp_path: Path) -> None:
        replay = load(sealed_log(tmp_path, corrupt=2))
        checked = check_step(replay.seek(2))
        assert not checked.verified
        assert "produces" in checked.reason

    def test_an_edited_digest_is_caught_too(self, tmp_path: Path) -> None:
        path = sealed_log(tmp_path)
        body = json.loads(path.read_text())
        body["steps"][0]["commit"] = "f" * 64
        path.write_text(json.dumps(body))
        assert not check_step(load(path).current).verified

    def test_a_swapped_nonce_is_caught(self, tmp_path: Path) -> None:
        path = sealed_log(tmp_path)
        body = json.loads(path.read_text())
        body["steps"][0]["nonce"] = f"{99:032x}"
        path.write_text(json.dumps(body))
        assert not check_step(load(path).current).verified


class TestUnopenableIsNotTampered:
    def test_a_step_with_no_nonce_is_unverifiable_rather_than_failed(self, tmp_path: Path) -> None:
        """A sub-game that ended early has steps with no nonce.

        Calling those tampered would accuse an honest team of fraud for
        stopping.
        """
        checked = check_step(load(written(tmp_path, unopened=1)).seek(4))
        assert not checked.verified
        assert "cannot be opened (no nonce)" in checked.reason

    def test_a_step_with_no_reveal_says_so(self, tmp_path: Path) -> None:
        path = written(tmp_path)
        body = json.loads(path.read_text())
        body["steps"][0]["reveal"] = None
        path.write_text(json.dumps(body))
        checked = check_step(load(path).current)
        assert "cannot be opened (no reveal)" in checked.reason

    def test_the_two_reasons_read_differently(self, tmp_path: Path) -> None:
        """An auditor needs to tell a gap from a forgery at a glance."""
        gap = check_step(load(written(tmp_path, unopened=1)).seek(4))
        forged = check_step(load(sealed_log(tmp_path, corrupt=1)).seek(1))
        assert "cannot be opened" in gap.reason
        assert "cannot be opened" not in forged.reason
        assert str(gap) != str(forged)
