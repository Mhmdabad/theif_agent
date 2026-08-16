"""The four submission artifacts, written locally and marked unmistakably uncounted.

The names and the shared ``game_uid`` follow the book's App. F table 20 exactly, because
rehearsing the real thing is the point — you should be able to run ``tools/check_artifacts.py``
over this output and over a counted run and have it say the same thing.

**Five independent layers say "not a league game".** Any one of them would do; five means a human
skimming a directory, a script globbing filenames, and a tool parsing JSON each hit it
independently:

1. the group id is prefixed ``sparring-``, and ``game_id`` is built from the group ids — so the
   prefix is in every filename;
2. every artifact carries a top-level ``league`` block citing App. E rule 52;
3. the run lands in ``runs/sparring_<uid>/`` rather than beside real work;
4. a ``NOT_A_LEAGUE_GAME.txt`` sits in the directory;
5. **the result carries no signature key at all** — only ``"settlement": "not_owed"``.

The fifth is the strongest, and it is the reason the others are not enough on their own: a label
can be edited by anyone who wants to pass this off as a real result, but a *missing preimage*
cannot be emailed. There is nothing to verify, so there is nothing to submit.

Files are written as canonical bytes (SPEC section 2), rehearsing section 6's rule that what you
emit is what you hashed — never a pretty-printed re-serialization.
"""

from __future__ import annotations

from pathlib import Path

from sparring import CODE_VERSION, GROUP_PREFIX, kitref

NOT_A_GAME = """This directory holds a SPARRING run — a practice game, not a league game.

App. E rule 52 permits uncounted warm-ups explicitly. Nothing is owed for a run like this one:
no report is due from either side, and the result artifact here deliberately carries no
consensus signature, so there is nothing in it that could be submitted.

Do not send these files to anyone. Do not let them near a counted series' artifact directory.
"""


def _league_block() -> dict:
    return {
        "counted": False,
        "reason": "sparring",
        "authority": "book App. E rule 52 — uncounted warm-up games are permitted",
        "peer": CODE_VERSION,
        # anrbj666's P5-5: a team templating a COUNTED report from this output must not copy
        # the disarmed values. The counted derivation is SPEC §6.2: winner of a first-meeting
        # counted series → diversity true; counts bumped by the run that is counted.
        "fields_posture": "friendly-disarmed — counts unbumped, diversity all-false REGARDLESS "
                          "of outcome. A counted report derives these instead (SPEC 6.2).",
    }


def _write(path: Path, doc: dict) -> Path:
    path.write_bytes(kitref.canonical_bytes(doc) + b"\n")
    return path


class ArtifactSet:
    """Writes the four artifacts for one sparring series."""

    def __init__(self, root: Path, game_id: str, game_uid: str, mail_scan: str) -> None:
        self.dir = root / f"sparring_{game_uid}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.game_id = game_id
        self.game_uid = game_uid
        self.mail_scan = mail_scan
        (self.dir / "NOT_A_LEAGUE_GAME.txt").write_text(NOT_A_GAME, encoding="utf-8")

    @property
    def links(self) -> dict:
        return {
            "_remark": "match-level files are named <kind>_<game_id>.json; per-sub-game files "
                       "carry _g<NN>. All four share one game_uid, which is what joins them.",
            "declaration": f"declaration_{self.game_id}.json",
            "config": f"config_{self.game_id}_g<NN>.json",
            "log": f"log_{self.game_id}_g<NN>.json",
            "result": f"result_{self.game_id}.json",
        }

    def _base(self) -> dict:
        return {"schema_version": "1.1", "game_id": self.game_id, "game_uid": self.game_uid,
                "links": self.links, "league": _league_block()}

    def declaration(self, groups: list[dict], num_sub_games: int) -> Path:
        doc = {
            **self._base(),
            "declaration_type": "pre_game_declaration",
            "num_sub_games": num_sub_games,
            "max_tokens_per_game": 0,
            "groups": {"group_1": groups[0], "group_2": groups[1]},
            # The peer's own proof, carried by the artifact it produced: the hash over every
            # source file scanned by the mail-absence guard.
            "mail_surface": {"present": False, "scan_sha256": self.mail_scan, "ruleset": "nm-v1"},
        }
        return _write(self.dir / f"declaration_{self.game_id}.json", doc)

    def config(self, sub_game_number: int, terms: dict) -> Path:
        doc = {**self._base(), "sub_game_number": sub_game_number,
               "config_name": f"config_{self.game_id}_g{sub_game_number:02d}.json",
               "terms": terms, "config_sha256": kitref.canonical_hash(terms)}
        return _write(self.dir / f"config_{self.game_id}_g{sub_game_number:02d}.json", doc)

    def log(self, sub_game_number: int, summary: dict, records: list[dict],
            mutual: dict) -> Path:
        doc = {**self._base(), "summary": summary, "records": records,
               "mutual_agreement": mutual}
        return _write(self.dir / f"log_{self.game_id}_g{sub_game_number:02d}.json", doc)

    def result(self, groups: list[dict], sub_games: list[dict], final: dict,
               unclaimed_counts: frozenset[str] = frozenset()) -> Path:
        # The league fields ride in the FRIENDLY posture the playbook's stage 4d prescribes:
        # present (so a team templating from this output does not forget they exist), disarmed
        # (a practice run never bumps a count, never claims a diversity reward — App. E rules
        # 37-38 make an armed field in an uncounted run a false declaration, and that bug class
        # was found in BOTH real implementations on the same day).
        #
        # `unclaimed_counts` (anrbj666's P5-9): a game count is each team's OWN unverifiable
        # claim (SPEC §6.2). Against a real opponent this peer must not fabricate theirs — the
        # first revision stamped a live rival's standing as 0 — so their entry is null:
        # unclaimed, not asserted.
        final = {
            **final,
            "games_played_including_this": {
                g["group_id"]: (None if g["group_id"] in unclaimed_counts else 0)
                for g in groups},
            "first_meeting_between_groups": True,
            "diversity_reward_applied": {g["group_id"]: False for g in groups},
        }
        doc = {
            **self._base(),
            "report_type": "final_game_result",
            # The reference's result carries the two ids flat; identity blocks live in the
            # declaration. The first revision emitted the blocks here too, and nothing noticed
            # because nothing checked the shape (anrbj666's P5-15).
            "groups": [g["group_id"] for g in groups],
            "num_sub_games": len(sub_games),
            "sub_games": sub_games,
            "final_result": final,
            # No consensus signature, by construction. See the module docstring. The counted
            # shape's `mutual_agreement` is demonstrated by examples/pairing-artifacts/ instead —
            # adding a real preimage here would weaken the strongest not-a-league-game layer.
            "settlement": "not_owed",
        }
        # Rule 49: the result carries the repo links. Only groups that actually declared repos
        # appear — a real opponent that sent none is not invented for them.
        github = {g["group_id"]: g["repos"] for g in groups if g.get("repos")}
        if github:
            doc["links"] = {**doc["links"], "github": github}
        return _write(self.dir / f"result_{self.game_id}.json", doc)


def assert_uncounted_group(group_id: str) -> None:
    """A sparring peer's group id must carry the reserved prefix.

    ``game_id`` is built from the two group ids, so this is what puts "sparring" into every
    filename the run produces — the cheapest possible way for a human to tell two directories
    apart at a glance.
    """
    if not group_id.startswith(GROUP_PREFIX):
        raise ValueError(
            f"a sparring peer's group id must start with {GROUP_PREFIX!r} (got {group_id!r}). "
            f"game_id is built from the group ids, so this prefix is what keeps a practice "
            f"artifact from ever being mistaken for a league pairing.")
