"""Step-0 hardware: true, or explicitly unknown, but never plausibly wrong."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.step_zero import (
    GPU_ENV,
    SIGNING_KEY_ENV,
    UNSIGNED,
    VRAM_ENV,
    Declaration,
    Hardware,
    _cpu_max_mhz,
    _positive_int,
    _ram_mb,
    collect,
    declare,
    provenance,
    sign,
    statement,
    verify_signature,
)
from thief_agent.shared.config import canonical_bytes


class TestUnknownIsDeclaredAsUnknown:
    def test_an_undetected_gpu_is_null_and_not_zero(self) -> None:
        """A signed declaration reading 0 VRAM is a false statement.

        The document's entire purpose is to be true, and the score is
        normalised against it — so a plausible zero understates our hardware
        and inflates our own result.
        """
        hardware = collect("claude-haiku-4-5", environ={})
        assert hardware.gpu is None
        assert hardware.vram_mb is None
        assert hardware.to_dict()["vram_mb"] is None

    def test_a_supplied_gpu_is_declared(self) -> None:
        hardware = collect("m", environ={GPU_ENV: "RTX 4070", VRAM_ENV: "8192"})
        assert (hardware.gpu, hardware.vram_mb) == ("RTX 4070", 8192)

    @pytest.mark.parametrize("raw", ["", "  ", "lots", "-1", "0", "8gb", None])
    def test_a_malformed_vram_figure_is_absent_rather_than_fatal(self, raw: str | None) -> None:
        """The operator mistyping a figure should not stop a match.

        Unknown is already an accepted state, so falling back to it costs
        nothing and refusing to start costs a sub-game.
        """
        assert _positive_int(raw) is None

    def test_an_empty_gpu_name_is_absent_rather_than_empty(self) -> None:
        assert collect("m", environ={GPU_ENV: ""}).gpu is None

    def test_it_reports_which_fields_need_an_operator(self) -> None:
        hardware = collect("claude-haiku-4-5", environ={})
        assert "gpu" in hardware.undetected
        assert "vram_mb" in hardware.undetected
        assert "os" not in hardware.undetected


class TestFieldsAreNamedForWhatTheyActuallyMeasure:
    def test_cores_are_named_logical_because_that_is_what_is_counted(self) -> None:
        """``os.cpu_count()`` counts hyperthreads.

        Calling it ``cpu_cores`` would be a number that quietly means
        something different on two machines being compared for fairness.
        """
        assert "logical_cores" in collect("m", environ={}).to_dict()
        assert "cpu_cores" not in collect("m", environ={}).to_dict()

    def test_the_declared_model_comes_from_config_not_from_the_environment(self) -> None:
        """It must be the model actually configured, not whichever is installed."""
        assert collect("claude-haiku-4-5", environ={}).llm_model == "claude-haiku-4-5"


class TestReadingTheCpuFrequency:
    def test_it_converts_khz_to_mhz(self, tmp_path: Path) -> None:
        path = tmp_path / "cpuinfo_max_freq"
        path.write_text("3600000\n")
        assert _cpu_max_mhz(path) == 3600.0

    def test_an_absent_file_is_unknown_rather_than_an_error(self, tmp_path: Path) -> None:
        """Readable on Linux, not portably anywhere else."""
        assert _cpu_max_mhz(tmp_path / "nope") is None

    def test_unreadable_contents_are_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "cpuinfo_max_freq"
        path.write_text("not a number")
        assert _cpu_max_mhz(path) is None


class TestTheDeclarationFragment:
    def test_it_names_every_field_the_rulebook_asks_for(self) -> None:
        fields = set(collect("m", environ={}).to_dict())
        assert fields == {
            "os",
            "logical_cores",
            "cpu_max_mhz",
            "ram_mb",
            "gpu",
            "vram_mb",
            "llm_model",
        }

    def test_it_survives_json_because_it_is_going_into_a_signed_file(self) -> None:
        fragment = collect("m", environ={GPU_ENV: "RTX 4070", VRAM_ENV: "8192"}).to_dict()
        assert json.loads(json.dumps(fragment)) == fragment

    def test_it_describes_the_machine_it_is_running_on(self) -> None:
        hardware = collect("m", environ={})
        assert hardware.os_name
        assert hardware.logical_cores is None or hardware.logical_cores >= 1

    def test_it_is_frozen_so_a_declared_machine_cannot_change(self) -> None:
        with pytest.raises(AttributeError):
            collect("m", environ={}).llm_model = "something-else"  # type: ignore[misc]

    def test_nothing_is_probed_at_import_time(self) -> None:
        """A module that probed on import would put CI's machine in the file.

        It would also run the probe during every test collection, which is a
        side effect nobody asked for.
        """
        source = (Path(__file__).parents[1] / "src/thief_agent/infra/step_zero.py").read_text()
        module = ast.parse(source)
        calls = [
            node
            for node in module.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        ]
        assert calls == []


class TestReadingTheMemorySize:
    def test_a_platform_without_sysconf_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows has no ``sysconf``; the field is absent rather than invented."""

        def missing(_: str) -> int:
            raise ValueError("unrecognised configuration name")

        monkeypatch.setattr(os, "sysconf", missing)
        assert _ram_mb() is None

    def test_it_reports_megabytes_where_it_can(self) -> None:
        size = _ram_mb()
        assert size is None or size > 0


class TestHardwareDirectly:
    def test_undetected_is_computed_from_the_fragment(self) -> None:
        bare = Hardware(
            os_name="Linux",
            logical_cores=None,
            cpu_max_mhz=None,
            ram_mb=None,
            gpu=None,
            vram_mb=None,
            llm_model="template",
        )
        assert set(bare.undetected) == {"logical_cores", "cpu_max_mhz", "ram_mb", "gpu", "vram_mb"}

    def test_a_fully_known_machine_has_nothing_undetected(self) -> None:
        full = Hardware("Linux", 8, 3600.0, 16384, "RTX 4070", 8192, "claude-haiku-4-5")
        assert full.undetected == ()


def repo(tmp_path: Path, commit: bool = True, dirty: bool = False) -> Path:
    """A real git repository, because the thing under test shells out to git."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "agent.py").write_text("print('hello')\n")
    if commit:
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "first"], cwd=tmp_path, check=True)
    if dirty:
        (tmp_path / "agent.py").write_text("print('changed after the commit')\n")
    return tmp_path


class TestTheCommitMustDescribeWhatRan:
    def test_a_clean_tree_is_reproducible(self, tmp_path: Path) -> None:
        found = provenance("0.1.0", "s82kma9e", 3, repo=repo(tmp_path))
        assert found.reproducible
        assert found.github_commit is not None
        assert not found.dirty
        assert "sub-game 3 at" in str(found)

    def test_uncommitted_changes_make_it_unreproducible(self, tmp_path: Path) -> None:
        """``git rev-parse HEAD`` answers happily with a dirty tree.

        The answer is then a commit that is *not* the code being executed — a
        declaration nobody can verify, and the easy mistake to make five
        minutes before a match.
        """
        found = provenance("0.1.0", "s82kma9e", 3, repo=repo(tmp_path, dirty=True))
        assert found.github_commit is not None
        assert found.dirty
        assert not found.reproducible
        assert "uncommitted changes" in str(found)

    def test_untracked_output_does_not_make_it_unreproducible(self, tmp_path: Path) -> None:
        """A match writes artefacts into its own tree, and rule 4 wants them kept.

        Counting those made the flag self-inflicting: step 0 runs at the start
        of a series, so every match after the first saw the previous one's
        output and declared unreproducible a commit an examiner could check out
        and run exactly. Nothing tracked had changed.
        """
        where = repo(tmp_path)
        (where / "artefacts").mkdir()
        (where / "artefacts" / "result_uoh26-x.json").write_text("{}\n")
        (where / ".quota_cop.json").write_text('{"day": "2026-08-11", "used": 1}\n')
        found = provenance("0.1.0", "s82kma9e", 3, repo=where)
        assert not found.dirty
        assert found.reproducible

    def test_a_tracked_change_is_still_dirty_even_beside_untracked_output(
        self, tmp_path: Path
    ) -> None:
        """The exemption is for output, not a licence to edit code uncommitted."""
        where = repo(tmp_path, dirty=True)
        (where / "artefacts").mkdir()
        (where / "artefacts" / "result_uoh26-x.json").write_text("{}\n")
        assert provenance("0.1.0", "s82kma9e", 3, repo=where).dirty

    def test_the_declaration_records_the_dirty_flag_rather_than_hiding_it(
        self, tmp_path: Path
    ) -> None:
        found = provenance("0.1.0", "s82kma9e", 1, repo=repo(tmp_path, dirty=True))
        assert found.to_dict()["working_tree_dirty"] is True

    def test_no_repository_is_a_real_state_not_a_failure(self, tmp_path: Path) -> None:
        """A submitted tarball has no ``.git``.

        An agent that refused to start there would be unrunnable exactly where
        the examiner runs it.
        """
        found = provenance("0.1.0", "s82kma9e", 1, repo=tmp_path)
        assert found.github_commit is None
        assert not found.reproducible
        assert "no commit hash available" in str(found)

    def test_it_finds_this_repository_by_default(self) -> None:
        assert provenance("0.1.0", "s82kma9e", 1).github_commit is not None


class TestTheProvenanceFragment:
    def test_it_names_every_field_the_rulebook_asks_for(self, tmp_path: Path) -> None:
        fragment = provenance("0.1.0", "s82kma9e", 2, repo=repo(tmp_path)).to_dict()
        assert set(fragment) == {
            "code_version",
            "group_name",
            "sub_game",
            "github_commit",
            "working_tree_dirty",
        }

    def test_it_survives_json(self, tmp_path: Path) -> None:
        fragment = provenance("0.1.0", "s82kma9e", 2, repo=repo(tmp_path)).to_dict()
        assert json.loads(json.dumps(fragment)) == fragment

    def test_it_is_frozen(self, tmp_path: Path) -> None:
        with pytest.raises(AttributeError):
            provenance("0.1.0", "s82kma9e", 1, repo=repo(tmp_path)).sub_game = 9  # type: ignore[misc]


KEY = "a-key-the-course-supplies"


def declaration(tmp_path: Path, key: str | None = KEY) -> Declaration:
    return declare(
        collect("claude-haiku-4-5", environ={}),
        provenance("0.1.0", "s82kma9e", 1, repo=repo(tmp_path)),
        environ={SIGNING_KEY_ENV: key} if key else {},
    )


class TestSigning:
    def test_a_key_produces_a_verifiable_signature(self, tmp_path: Path) -> None:
        declared = declaration(tmp_path)
        assert declared.signed
        assert verify_signature(declared.to_dict(), KEY)

    def test_the_wrong_key_does_not_verify(self, tmp_path: Path) -> None:
        assert not verify_signature(declaration(tmp_path).to_dict(), "someone-elses-key")

    def test_editing_any_declared_field_breaks_the_signature(self, tmp_path: Path) -> None:
        tampered = declaration(tmp_path).to_dict()
        tampered["hardware"] = {**tampered["hardware"], "logical_cores": 256}
        assert not verify_signature(tampered, KEY)

    def test_it_is_an_hmac_rather_than_a_bare_hash(self) -> None:
        """A sha256 of a public document is something anybody can compute.

        It would authenticate nothing while looking exactly like a signature.
        """
        content: dict[str, Any] = {"hardware": {}, "provenance": {}}
        assert sign(content, KEY) != hashlib.sha256(canonical_bytes(content)).hexdigest()

    def test_it_signs_canonical_bytes(self) -> None:
        """A signature over ``str(dict)`` verifies only against the same Python.

        That is a compatibility bug wearing the costume of a forgery.
        """
        content: dict[str, Any] = {"hardware": {"b": 1, "a": 2}, "provenance": {}}
        reordered: dict[str, Any] = {"hardware": {"a": 2, "b": 1}, "provenance": {}}
        assert sign(content, KEY) == sign(reordered, KEY)


class TestWithoutTheKey:
    def test_no_key_declares_itself_unsigned(self, tmp_path: Path) -> None:
        """Not an empty string and not a signature over an empty key.

        Both of those *verify*, and a declaration that verifies against a key
        nobody holds is worse than one that says plainly it was never signed.
        """
        declared = declaration(tmp_path, key=None)
        assert not declared.signed
        assert declared.to_dict()["signature"] == UNSIGNED

    def test_an_unsigned_declaration_never_verifies(self, tmp_path: Path) -> None:
        assert not verify_signature(declaration(tmp_path, key=None).to_dict(), KEY)

    @pytest.mark.parametrize("claimed", [None, 42, "", UNSIGNED])
    def test_a_missing_or_unsigned_claim_is_refused(self, claimed: object) -> None:
        assert not verify_signature({"hardware": {}, "provenance": {}, "signature": claimed}, KEY)


class TestWhatIsSignedIsNotWhatIsSent:
    def test_the_statement_excludes_the_signature(self, tmp_path: Path) -> None:
        """A function returning both would eventually sign a document
        containing its own signature."""
        declared = declaration(tmp_path)
        content = statement(declared.hardware, declared.provenance)
        assert "signature" not in content
        assert set(declared.to_dict()) == {"hardware", "provenance", "signature"}

    def test_the_key_is_never_read_from_a_file_in_this_repository(self) -> None:
        """A key committed beside the thing it signs is not a key.

        These repositories are public, so anyone in the cohort could forge the
        signature — and Appendix C makes a leaked secret a submission gate.
        """
        source = (Path(__file__).parents[1] / "src/thief_agent/infra/step_zero.py").read_text()
        assert "environ.get(SIGNING_KEY_ENV)" in source.replace("source.", "environ.")
        assert "open(" not in source
        for tracked in (Path(__file__).parents[1] / "config").rglob("*"):
            if tracked.is_file():
                assert SIGNING_KEY_ENV not in tracked.read_text()
