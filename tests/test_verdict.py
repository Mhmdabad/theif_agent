"""The stamp, and the walk that earns it."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.infra.match_log import MatchLog
from thief_agent.ui.replay import check_step, load
from thief_agent.ui.verdict import Attestation, Stamp, walk


def sealed_log(
    tmp_path: Path, steps: int = 4, corrupt: int | None = None, unopened: int = 0
) -> Path:
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
        if step <= steps - unopened:
            log.disclose(step, secret)
    return log.write(tmp_path)


def hand_edited(path: Path, change: Callable[[dict[str, Any]], None]) -> Path:
    """The log as a text editor would leave it after somebody went in."""
    body = json.loads(path.read_text())
    change(body)
    path.write_text(json.dumps(body))
    return path


class TestACleanLogIsStamped:
    def test_it_stamps_verified_ok(self, tmp_path: Path) -> None:
        result = walk(load(sealed_log(tmp_path)))
        assert result.stamp is Stamp.VERIFIED_OK
        assert result.stamp.text == "Verified OK"
        assert result.clean and not result.void

    def test_it_reports_every_step_as_re_derived(self, tmp_path: Path) -> None:
        result = walk(load(sealed_log(tmp_path, steps=6)))
        assert (result.verified, result.total) == (6, 6)
        assert result.at_step is None

    def test_the_stamp_is_green(self, tmp_path: Path) -> None:
        """The rulebook asks for a colour, so the model carries one."""
        assert walk(load(sealed_log(tmp_path))).stamp.value == "green"

    def test_it_reads_as_a_sentence(self, tmp_path: Path) -> None:
        assert str(walk(load(sealed_log(tmp_path)))) == "Verified OK — 4 steps re-derived"


class TestAnAlterationHoweverSmall:
    def test_a_changed_move_is_tampered(self, tmp_path: Path) -> None:
        result = walk(load(sealed_log(tmp_path, corrupt=2)))
        assert result.stamp is Stamp.TAMPERED
        assert result.stamp.text == "TAMPERED"
        assert result.stamp.value == "red"

    def test_one_tampered_step_voids_the_match(self, tmp_path: Path) -> None:
        """There is no appeal and no retroactive fix — that is the point of it."""
        assert walk(load(sealed_log(tmp_path, corrupt=3))).void

    def test_a_single_flipped_character_in_a_digest_is_enough(self, tmp_path: Path) -> None:
        """'Any alteration, however small.' SHA-256 has no near-miss."""
        path = sealed_log(tmp_path)
        original = json.loads(path.read_text())["records"][1]["commit"]
        flipped = ("0" if original[0] != "0" else "1") + original[1:]

        def edit(body: dict[str, Any]) -> None:
            body["records"][1]["commit"] = flipped

        result = walk(load(hand_edited(path, edit)))
        assert result.stamp is Stamp.TAMPERED
        assert result.at_step == 2

    def test_a_swapped_nonce_is_tampered(self, tmp_path: Path) -> None:
        def edit(body: dict[str, Any]) -> None:
            body["records"][0]["nonce"] = f"{99:032x}"

        result = walk(load(hand_edited(sealed_log(tmp_path), edit)))
        assert result.stamp is Stamp.TAMPERED

    def test_a_hint_reworded_after_the_fact_is_tampered(self, tmp_path: Path) -> None:
        """The commitment covers the whole record, not only the move."""

        def edit(body: dict[str, Any]) -> None:
            body["records"][0]["payload"]["hint"] = "step one"

        assert walk(load(hand_edited(sealed_log(tmp_path), edit))).void

    def test_the_finding_is_one_the_other_team_can_check(self, tmp_path: Path) -> None:
        """'You cheated' is not a claim anyone concedes; arithmetic is."""
        result = walk(load(sealed_log(tmp_path, corrupt=2)))
        assert result.at_step == 2
        assert "produces" in result.reason
        assert "TAMPERED at step 2" in str(result)


class TestItAbortsOnFirstFailure:
    def test_the_walk_stops_rather_than_gathering_a_list(self, tmp_path: Path) -> None:
        """Once one step fails the match is void; the rest is not evidence."""
        result = walk(load(sealed_log(tmp_path, steps=6, corrupt=2)))
        assert result.verified == 1
        assert result.total == 6
        assert result.at_step == 2

    def test_it_stops_at_the_earliest_failure_not_the_worst(self, tmp_path: Path) -> None:
        path = sealed_log(tmp_path, steps=6, corrupt=5)

        def edit(body: dict[str, Any]) -> None:
            body["records"][2]["nonce"] = f"{77:032x}"

        assert walk(load(hand_edited(path, edit))).at_step == 3

    def test_it_walks_the_log_not_the_cursor(self, tmp_path: Path) -> None:
        """A verdict that depended on where the reader was looking would be no verdict."""
        replay = load(sealed_log(tmp_path, corrupt=2))
        replay.seek(4)
        assert walk(replay).at_step == 2
        assert replay.current.step == 4, "the walk reports; seeking is the viewer's move"


class TestUnverifiableIsNotAnAccusation:
    def test_a_log_with_no_nonces_yet_is_incomplete(self, tmp_path: Path) -> None:
        """Nonces land only when the match ends. A copy taken mid-match is not fraud."""
        result = walk(load(sealed_log(tmp_path, unopened=4)))
        assert result.stamp is Stamp.INCOMPLETE
        assert result.stamp.text == "INCOMPLETE"
        assert not result.void

    def test_it_names_the_step_it_could_not_open(self, tmp_path: Path) -> None:
        result = walk(load(sealed_log(tmp_path, unopened=2)))
        assert (result.verified, result.at_step) == (2, 3)
        assert "cannot be opened (no nonce)" in result.reason

    def test_incomplete_is_not_an_acquittal(self, tmp_path: Path) -> None:
        """Deleting a nonce to hide a forgery still fails to earn the only clean stamp."""
        path = sealed_log(tmp_path, corrupt=2)

        def edit(body: dict[str, Any]) -> None:
            body["records"][1]["nonce"] = None

        result = walk(load(hand_edited(path, edit)))
        assert result.stamp is Stamp.INCOMPLETE
        assert not result.clean

    def test_a_gap_does_not_shield_a_later_forgery(self, tmp_path: Path) -> None:
        """Stopping at the gap would make 'delete an early nonce' a way to hide."""
        path = sealed_log(tmp_path, steps=6, corrupt=5)

        def edit(body: dict[str, Any]) -> None:
            body["records"][1]["nonce"] = None

        result = walk(load(hand_edited(path, edit)))
        assert result.stamp is Stamp.TAMPERED
        assert result.at_step == 5
        assert result.unopened == (2,), "the gap is reported, not treated as the verdict"

    def test_tampering_outranks_a_gap_whichever_comes_first(self, tmp_path: Path) -> None:
        """A proven forgery is a harder fact than an unverifiable step."""
        path = sealed_log(tmp_path, steps=6, corrupt=2, unopened=3)
        assert walk(load(path)).stamp is Stamp.TAMPERED

    def test_the_three_stamps_are_distinguishable_to_a_reader(self, tmp_path: Path) -> None:
        clean = walk(load(sealed_log(tmp_path)))
        forged = walk(load(sealed_log(tmp_path / "b", corrupt=1)))
        partial = walk(load(sealed_log(tmp_path / "c", unopened=1)))
        assert len({clean.stamp, forged.stamp, partial.stamp}) == 3
        assert len({str(clean), str(forged), str(partial)}) == 3


class TestTheVerdictDoesNotReadEnglish:
    def test_a_nonce_injected_into_the_record_is_tampered(self, tmp_path: Path) -> None:
        """A 'nonce' inside the record is a shape our sealer never produces.

        The wire form hashes it without complaint — the reference's would too —
        so the edit is caught the way every edit is caught: the digest no
        longer matches. What matters is that the viewer answers with a verdict
        rather than crashing, since a crash on a hand-edited log would report
        the edit as our own bug.
        """
        path = sealed_log(tmp_path)

        def edit(body: dict[str, Any]) -> None:
            body["records"][0]["payload"]["nonce"] = "deadbeef"

        result = walk(load(hand_edited(path, edit)))
        assert result.stamp is Stamp.TAMPERED
        assert result.at_step == 1
        assert "produces" in result.reason

    def test_a_book_form_log_is_genuine_not_tampered(self, tmp_path: Path) -> None:
        """Liberal-in extends to the Replay App.

        A log this team sealed before the wire flip — or an opponent's log
        sealed by a literal implementation of the book — re-derives under the
        book's convention. Its dialect is not evidence of fraud, and a viewer
        that stamped it TAMPERED would void an honest match at the archive.
        """
        from thief_agent.domain.crypto import book_commit_of

        path = sealed_log(tmp_path)

        def reseal(body: dict[str, Any]) -> None:
            for step in body["records"]:
                if step.get("payload") is not None and step.get("nonce"):
                    step["commit"] = book_commit_of(step["payload"], step["nonce"])

        result = walk(load(hand_edited(path, reseal)))
        assert result.stamp is not Stamp.TAMPERED

    def test_check_step_answers_rather_than_raising(self, tmp_path: Path) -> None:
        path = sealed_log(tmp_path)

        def edit(body: dict[str, Any]) -> None:
            body["records"][0]["payload"]["nonce"] = "deadbeef"

        checked = check_step(load(hand_edited(path, edit)).current)
        assert not checked.verified

    def test_the_split_is_openable_not_the_wording_of_a_reason(self, tmp_path: Path) -> None:
        """Both failures carry prose; only one of them is an accusation."""
        forged = walk(load(sealed_log(tmp_path, corrupt=1)))
        partial = walk(load(sealed_log(tmp_path / "b", unopened=4)))
        assert forged.reason and partial.reason
        assert forged.void and not partial.void


class TestAttestationOnItsOwn:
    def test_a_clean_attestation_is_clean_and_not_void(self) -> None:
        result = Attestation(Stamp.VERIFIED_OK, verified=9, total=9)
        assert result.clean and not result.void

    def test_only_tampered_voids(self) -> None:
        assert not Attestation(Stamp.INCOMPLETE, 0, 3, at_step=1, reason="x").void
