from domain.simulation.data.signal_semantics import (
    normalize_simulation_signal_name,
    resolve_signal_type,
    resolve_vector_signal_type,
)
from domain.simulation.executor.ngspice_shared import VectorType
from domain.simulation.executor.spice_executor import SpiceExecutor


def test_normalize_simulation_signal_name_covers_voltage_current_and_branch_formats():
    assert normalize_simulation_signal_name("v(out)", VectorType.SV_VOLTAGE) == "V(out)"
    assert normalize_simulation_signal_name("i(v1)", VectorType.SV_CURRENT) == "I(v1)"
    assert normalize_simulation_signal_name("out", VectorType.SV_VOLTAGE) == "V(out)"
    assert normalize_simulation_signal_name("v1#branch", VectorType.SV_CURRENT) == "I(V1)"


def test_resolve_signal_type_reuses_base_signal_type_for_complex_components():
    assert resolve_signal_type("V(out)_mag", {"V(out)": "voltage"}) == "voltage"
    assert resolve_signal_type("I(R1)_phase", {"I(R1)": "current"}) == "current"
    assert resolve_signal_type("I(R1)") == "current"
    assert resolve_signal_type("V(out)") == "voltage"


def test_resolve_vector_signal_type_uses_noise_analysis_authority():
    assert resolve_vector_signal_type(
        "onoise_spectrum",
        VectorType.SV_OUTPUT_N_DENS,
        analysis_type="noise",
        analysis_command=".noise V(out) Vin dec 10 1 1k",
    ) == "voltage"
    assert resolve_vector_signal_type(
        "inoise_spectrum",
        VectorType.SV_INPUT_N_DENS,
        analysis_type="noise",
        analysis_command=".noise I(Vsense) IIN dec 10 1 1k",
    ) == "current"
    assert resolve_vector_signal_type(
        "r1#branch",
        VectorType.SV_NOTYPE,
        analysis_type="tran",
        analysis_command=".tran 1u 1m",
    ) == "current"


def test_spice_executor_only_injects_savecurrents_when_explicitly_requested():
    executor = SpiceExecutor.__new__(SpiceExecutor)

    netlist = ".title Demo\nR1 in out 1k\n.end\n"
    assert executor._inject_signal_capture_options(netlist) == netlist

    modified = executor._inject_signal_capture_options(netlist, {"capture_currents": True})
    assert modified.count("savecurrents") == 1
    assert ".options savecurrents\n.end" in modified

    existing = ".title Demo\n.options abstol=1e-12 savecurrents\nR1 in out 1k\n.end\n"
    assert executor._inject_signal_capture_options(existing, {"capture_currents": True}) == existing


def test_spice_executor_parses_access_violation_as_critical_ngspice_crash():
    executor = SpiceExecutor.__new__(SpiceExecutor)

    error = executor._parse_ngspice_output(
        "stdout partial\nstderr Using SPARSE 1.3 as Direct Linear Solver\n执行命令 run 失败: exception: access violation reading 0x0000000000000000",
        "demo.cir",
    )

    assert error.code == "E008"
    assert error.type.value == "E008"
    assert error.severity.value == "critical"
    assert "ngspice 原生命令崩溃" in error.message
