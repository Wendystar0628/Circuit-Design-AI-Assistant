from __future__ import annotations

import re
from pathlib import Path

from domain.simulation.spice.include_parser import IncludeParser
from domain.simulation.spice.runtime_compatibility import analyze_spice_library_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = PROJECT_ROOT / "TestCircuit"
DISCRETE_LIBRARY = (
    PROJECT_ROOT / "resources" / "models" / "ngspice" / "testcircuit_discrete.lib"
)
_DISCRETE_MODEL = re.compile(
    r"\b(?:2N3904|2N3906|1N4148|2N3819|2N5460|BSS123|BSS84)\b",
    re.IGNORECASE,
)
_RETIRED_DEMOS = (
    "01_lt1001_voltage_follower",
    "03_lt6201_non_inverting_amplifier",
    "04_ltc6247_active_lowpass_amplifier",
    "05_lt1001_two_stage_amplifier",
)


def test_executor_has_no_implicit_bundled_model_path() -> None:
    executor_source = (
        PROJECT_ROOT / "domain" / "simulation" / "executor" / "spice_executor.py"
    ).read_text(encoding="utf-8")

    assert "BundledSpiceLibraryInjector" not in executor_source
    assert "_inject_model_libraries" not in executor_source
    assert "_bundled_model_injector" not in executor_source


def test_testcircuit_model_dependencies_are_explicit_and_resolvable() -> None:
    parser = IncludeParser()
    circuits = sorted(
        path
        for path in TEST_ROOT.rglob("*.cir")
        if ".circuit_ai" not in path.parts
        and "simulation_results" not in path.parts
    )

    assert len(circuits) == 43
    assert sum(
        "testcircuit_discrete.lib" in path.read_text(encoding="utf-8")
        for path in circuits
    ) == 29

    for circuit in circuits:
        source = circuit.read_text(encoding="utf-8")
        if _DISCRETE_MODEL.search(source):
            assert "testcircuit_discrete.lib" in source, circuit
        if re.search(r"\bLM741\b", source, re.IGNORECASE):
            assert "LM741.lib" in source, circuit

        for include in parser.parse_content(source):
            candidate = Path(include.raw_path)
            resolved = (
                candidate.resolve()
                if candidate.is_absolute()
                else (circuit.parent / candidate).resolve()
            )
            assert resolved.is_file(), f"{circuit}: {include.raw_path}"


def test_curated_discrete_library_contains_only_the_corpus_models() -> None:
    compatibility = analyze_spice_library_file(DISCRETE_LIBRARY)

    assert compatibility.is_compatible is True
    assert set(compatibility.model_names) == {
        "1n4148",
        "2n3819",
        "2n3904",
        "2n3906",
        "2n5460",
        "bss123",
        "bss84",
    }


def test_unparseable_vendor_demos_and_stale_results_are_physically_removed() -> None:
    for stem in _RETIRED_DEMOS:
        assert not (TEST_ROOT / "opamp_circuits" / f"{stem}.cir").exists()
        assert not (TEST_ROOT / "simulation_results" / stem).exists()

    assert not (TEST_ROOT / "transcribed_circuits").exists()
