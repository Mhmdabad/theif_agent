"""Step-0 hardware: true, or explicitly unknown, but never plausibly wrong."""

import ast
import json
import os
from pathlib import Path

import pytest

from thief_agent.infra.step_zero import (
    GPU_ENV,
    VRAM_ENV,
    Hardware,
    _cpu_max_mhz,
    _positive_int,
    _ram_mb,
    collect,
)


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
