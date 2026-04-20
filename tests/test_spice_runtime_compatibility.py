import logging
from pathlib import Path

from domain.simulation.service.bundled_spice_library_injector import BundledSpiceLibraryInjector
from domain.simulation.spice.runtime_compatibility import (
    NetlistRuntimeCompatibilityNormalizer,
    analyze_spice_library_file,
)


def test_library_compatibility_rejects_ltspice_only_behavioral_tokens(tmp_path: Path) -> None:
    lib_path = tmp_path / "lt_only.lib"
    lib_path.write_text(
        ".subckt LT1001 1 2 3 4 5\n"
        "A1 0 0 0 0 0 0 0 0 OTA g=1\n"
        ".ends LT1001\n",
        encoding="utf-8",
    )

    compatibility = analyze_spice_library_file(lib_path)

    assert compatibility.is_compatible is False
    assert "lt1001" in compatibility.subckt_names
    assert "OTA" in compatibility.incompatible_reasons


def test_runtime_normalizer_drops_incompatible_include_and_replaces_lt1001(tmp_path: Path) -> None:
    lib_path = tmp_path / "lt_only.lib"
    lib_path.write_text(
        ".subckt LT1001 1 2 3 4 5\n"
        "A1 0 0 0 0 0 0 0 0 OTA g=1\n"
        ".ends LT1001\n",
        encoding="utf-8",
    )
    circuit_path = tmp_path / "amp.cir"
    circuit_text = (
        f'.include "{lib_path.as_posix()}"\n'
        "XU1 0 inv out vcc vee LT1001\n"
        "R1 out inv 10k\n"
        ".tran 1u 1m\n"
        ".end\n"
    )
    circuit_path.write_text(circuit_text, encoding="utf-8")

    normalized = NetlistRuntimeCompatibilityNormalizer().normalize(circuit_text, source_file=str(circuit_path))

    assert ".include" not in normalized.netlist_text.lower()
    assert "CAI_COMPAT_OPAMP_5" in normalized.netlist_text
    assert " LT1001" not in normalized.netlist_text
    assert normalized.degraded is True
    assert normalized.warnings


def test_runtime_normalizer_degrades_three_node_mos_to_body_tied_source(tmp_path: Path) -> None:
    circuit_path = tmp_path / "diff_amp.cir"
    circuit_text = (
        ".title differential_amplifier\n"
        "M1 N004 N003 N007 2N7002\n"
        "M2 N005 N006 N007 2N7002\n"
        ".tran 20m\n"
        ".end\n"
    )
    circuit_path.write_text(circuit_text, encoding="utf-8")

    normalized = NetlistRuntimeCompatibilityNormalizer().normalize(circuit_text, source_file=str(circuit_path))

    assert "M1 N004 N003 N007 N007 2N7002" in normalized.netlist_text
    assert "M2 N005 N006 N007 N007 2N7002" in normalized.netlist_text
    assert normalized.degraded is True
    assert any("body 节点" in warning for warning in normalized.warnings)


def test_bundled_model_injector_resolves_2n7002_after_mos_runtime_degradation(tmp_path: Path) -> None:
    circuit_text = (
        ".title differential_amplifier\n"
        "M1 N004 N003 N007 2N7002\n"
        ".tran 20m\n"
        ".end\n"
    )
    normalized = NetlistRuntimeCompatibilityNormalizer().normalize(circuit_text, source_file=str(tmp_path / "diff_amp.cir"))

    injected = BundledSpiceLibraryInjector(logging.getLogger(__name__)).inject(normalized.netlist_text, tmp_path)

    assert ".model 2N7002" in injected or ".model 2n7002" in injected
