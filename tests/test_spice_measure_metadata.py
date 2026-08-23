import numpy as np

from domain.simulation.measure.measure_metadata import (
    MeasureMetadataResolver,
)
from domain.simulation.measure.measure_result import MeasureResult, MeasureStatus
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from domain.simulation.service.display_metric_builder import DisplayMetricBuilder


def test_units_follow_the_measure_operation_and_ngspice_phase_semantics():
    resolver = MeasureMetadataResolver()

    phase = resolver.resolve(
        "phase_at_unity",
        statement=".measure ac phase_at_unity FIND VP(out) WHEN VDB(out)=0",
    )
    max_time = resolver.resolve(
        "peak_location",
        statement=".measure tran peak_location MAX_AT V(out)",
    )
    integral = resolver.resolve(
        "area",
        statement=".measure tran area INTEG V(out) FROM=0 TO=1m",
    )
    derivative = resolver.resolve(
        "slope",
        statement=".measure tran slope DERIV I(Vsense) AT=1m",
    )
    trig_targ = resolver.resolve(
        "edge_delta",
        statement=(
            ".measure tran edge_delta TRIG V(in) VAL=0.5 RISE=1 "
            "TARG V(out) VAL=0.5 RISE=1"
        ),
    )
    dc_derivative = resolver.resolve(
        "dc_slope",
        statement=".measure dc dc_slope DERIV V(out) AT=0.5",
    )

    assert (phase.quantity_kind, phase.unit) == ("phase", "rad")
    assert (max_time.quantity_kind, max_time.unit) == ("time", "s")
    assert integral.unit == "V·s"
    assert derivative.unit == "A/s"
    assert (trig_targ.quantity_kind, trig_targ.unit) == ("time", "s")
    assert dc_derivative.unit == ""


def test_physical_units_are_not_guessed_from_result_names():
    metadata = MeasureMetadataResolver().resolve("input_voltage")

    assert metadata.quantity_kind == "unknown"
    assert metadata.unit == ""


def test_units_are_derived_only_from_authoritative_measure_statements():
    resolver = MeasureMetadataResolver()

    assert resolver.resolve(
        "v_at_resonance",
        statement=".measure ac v_at_resonance FIND VDB(out) AT=5k",
    ).unit == "dB"
    assert resolver.resolve(
        "v_buf_out_pp",
        statement=".measure tran v_buf_out_pp PP V(buf_out) FROM=0 TO=1m",
    ).unit == "V"
    assert resolver.resolve(
        "custom_ratio",
        statement=".measure ac custom_ratio PARAM='v(out)/v(in)'",
    ).unit == ""
    assert resolver.resolve(
        "dc_slope",
        statement=".measure dc dc_slope DERIV V(out) AT=0.5",
    ).unit == ""


def test_failed_measurements_remain_visible_without_a_fake_value():
    result = SimulationResult(
        executor="spice",
        file_path="circuits/metrics.cir",
        analysis_type="ac",
        success=True,
        source_digest="0" * 64,
        data=SimulationData(
            frequency=np.array([10.0, 100.0, 1000.0]),
            signals={"V(out)": np.array([1.0, 0.5, 0.1])},
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac dec 1 10 1k",
        measurements=[
            MeasureResult(
                name="gain_db",
                value=20.0,
                status=MeasureStatus.OK,
                statement=".measure ac gain_db FIND VDB(out) AT=1k",
            ),
            MeasureResult(
                name="f_3db",
                value=None,
                status=MeasureStatus.FAILED,
                statement=".measure ac f_3db WHEN VDB(out)=-3",
                error_message="Error: out of interval",
            ),
        ],
    )

    rows = DisplayMetricBuilder().build(result, {})

    assert len(rows) == 2
    assert (rows[0].status, rows[0].value, rows[0].unit) == (
        "OK",
        "20 dB",
        "dB",
    )
    assert rows[1].status == "FAILED"
    assert rows[1].value == ""
    assert rows[1].raw_value is None
    assert rows[1].unit == "Hz"
    assert rows[1].error_message == "Error: out of interval"
    assert result.success is True
