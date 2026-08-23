from domain.simulation.data.signal_semantics import (
    normalize_simulation_signal_name,
    parse_device_parameter_signal_name,
    parse_nested_dc_sweep,
    resolve_signal_type,
    resolve_vector_signal_type,
)
from domain.simulation.executor.ngspice_shared import VectorType
from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.models.simulation_result import SimulationResult


def test_normalize_simulation_signal_name_covers_voltage_current_and_branch_formats():
    assert normalize_simulation_signal_name("v(out)", VectorType.SV_VOLTAGE) == "V(out)"
    assert normalize_simulation_signal_name("i(v1)", VectorType.SV_CURRENT) == "I(v1)"
    assert normalize_simulation_signal_name("out", VectorType.SV_VOLTAGE) == "V(out)"
    assert (
        normalize_simulation_signal_name("v1#branch", VectorType.SV_CURRENT) == "I(V1)"
    )


def test_device_parameter_syntax_wins_over_broad_ngspice_vector_type():
    cases = (
        ("@m1[id]", VectorType.SV_CURRENT, ("m1", "id"), "current"),
        ("@m1[gm]", VectorType.SV_PHASE, ("m1", "gm"), "other"),
        ("@m1[vgs]", VectorType.SV_VOLTAGE, ("m1", "vgs"), "voltage"),
        (
            "@xamp.m1[vds]",
            VectorType.SV_VOLTAGE,
            ("xamp.m1", "vds"),
            "voltage",
        ),
    )
    for vector_name, vector_type, identity, signal_type in cases:
        assert parse_device_parameter_signal_name(vector_name) == identity
        assert normalize_simulation_signal_name(vector_name, vector_type) == vector_name
        assert resolve_signal_type(vector_name) == signal_type
        assert resolve_signal_type(vector_name, {vector_name: "current"}) == signal_type
        assert (
            resolve_vector_signal_type(
                vector_name,
                vector_type,
                analysis_type="op",
                analysis_command=".op",
            )
            == signal_type
        )


def test_resolve_signal_type_reuses_base_signal_type_for_complex_components():
    assert resolve_signal_type("V(out)_mag", {"V(out)": "voltage"}) == "voltage"
    assert resolve_signal_type("I(R1)_phase", {"I(R1)": "current"}) == "current"
    assert resolve_signal_type("I(R1)") == "current"
    assert resolve_signal_type("V(out)") == "voltage"


def test_resolve_vector_signal_type_uses_noise_analysis_authority():
    assert (
        resolve_vector_signal_type(
            "onoise_spectrum",
            VectorType.SV_OUTPUT_N_DENS,
            analysis_type="noise",
            analysis_command=".noise V(out) Vin dec 10 1 1k",
        )
        == "voltage"
    )
    assert (
        resolve_vector_signal_type(
            "inoise_spectrum",
            VectorType.SV_INPUT_N_DENS,
            analysis_type="noise",
            analysis_command=".noise V(out) IIN dec 10 1 1k",
        )
        == "current"
    )


def test_noise_operands_use_structural_directive_tokenization():
    assert (
        resolve_vector_signal_type(
            "onoise_spectrum",
            VectorType.SV_OUTPUT_N_DENS,
            analysis_type="noise",
            analysis_command=(
                ".noise V(out, 0) Vin dec 10 1 1k "
                "; V(fake) in a top-level comment"
            ),
        )
        == "voltage"
    )
    assert (
        resolve_vector_signal_type(
            "onoise_spectrum",
            VectorType.SV_OUTPUT_N_DENS,
            analysis_type="noise",
            analysis_command=".noise I(Vsense ) IIN dec 10 1 1k $ comment",
        )
        == "other"
    )


def test_dc_sweep_units_cover_temperature_and_resistors_without_guessing():
    labels = {
        ".dc TEMP 20 30 10": "TEMP (°C)",
        ".dc Rload 1k 2k 1k": "Rload (Ω)",
        ".dc Xcontrol 0 1 0.1": "Xcontrol",
    }
    for command, expected_label in labels.items():
        result = SimulationResult(
            executor="spice",
            file_path="circuits/dc.cir",
            analysis_type="dc",
            success=False,
            analysis_command=command,
        )
        assert result.get_x_axis_label() == expected_label

    temperature_outer = parse_nested_dc_sweep(
        "dc", ".dc V1 0 1 0.5 TEMP 20 30 10"
    )
    resistor_outer = parse_nested_dc_sweep(
        "dc", ".dc V1 0 1 0.5 Rload 1k 2k 1k"
    )
    unknown_outer = parse_nested_dc_sweep(
        "dc", ".dc V1 0 1 0.5 Xcontrol 0 1 0.5"
    )

    assert temperature_outer is not None
    assert temperature_outer.secondary_column_label == "Outer sweep TEMP (°C)"
    assert resistor_outer is not None
    assert resistor_outer.secondary_column_label == "Outer sweep Rload (Ω)"
    assert unknown_outer is not None
    assert unknown_outer.secondary_column_label == "Outer sweep Xcontrol"
    assert (
        resolve_vector_signal_type(
            "r1#branch",
            VectorType.SV_NOTYPE,
            analysis_type="tran",
            analysis_command=".tran 1u 1m",
        )
        == "current"
    )


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
