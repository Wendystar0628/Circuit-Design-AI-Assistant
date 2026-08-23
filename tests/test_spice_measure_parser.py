from domain.simulation.measure.measure_parser import MeasureParser
from domain.simulation.measure.measure_result import MeasureStatus


def test_parses_real_shared_library_output_and_surfaces_failed_measurements():
    output = """
stdout Doing analysis at TEMP = 27.000000 and TNOM = 27.000000
stdout Measurements for Transient Analysis
stdout vmax                =  7.179484e-01 at=  3.001000e-06
stderr out of interval
stderr .measure tran never when v(out)=2 rise=1 failed!
stdout product             =  3.931626e-01
"""

    results = MeasureParser().parse_measure_output(output)

    assert [(result.name, result.status) for result in results] == [
        ("vmax", MeasureStatus.OK),
        ("never", MeasureStatus.FAILED),
        ("product", MeasureStatus.OK),
    ]
    assert results[0].value == 0.7179484
    assert results[0].statement == ""
    assert results[1].value is None
    assert results[1].error_message == "out of interval"


def test_ignores_assignment_shaped_output_outside_measurement_sections():
    output = """
stdout temperature = 27
stdout arbitrary = 123
stdout No. of Data Rows : 2
"""

    assert MeasureParser().parse_measure_output(output) == []


def test_non_finite_results_are_failures_not_json_nan_values():
    output = """
stdout Measurements for AC Analysis
stdout unstable = -nan
stdout overflow = inf
"""

    results = MeasureParser().parse_measure_output(output)

    assert [result.status for result in results] == [
        MeasureStatus.FAILED,
        MeasureStatus.FAILED,
    ]
    assert [result.value for result in results] == [None, None]


def test_latest_outcome_wins_when_ngspice_reuses_a_result_name():
    output = """
stdout Measurements for Transient Analysis
stdout peak = 1.0
stdout Measurements for Transient Analysis
stdout PEAK = 2.0
"""

    results = MeasureParser().parse_measure_output(output)

    assert len(results) == 1
    assert results[0].name == "PEAK"
    assert results[0].value == 2.0


def test_final_analysis_filter_prevents_cross_plot_measurement_leakage():
    output = """
    stdout Measurements for Transient Analysis
    stdout hidden = 9.0
    stdout Measurements for AC Analysis
    stdout gain = 2.0
    """

    results = MeasureParser().parse_measure_output(
        output,
        analysis_type="ac",
        expected_names=["gain"],
    )

    assert [(result.name, result.value, result.status) for result in results] == [
        ("gain", 2.0, MeasureStatus.OK)
    ]


def test_missing_requested_measurement_becomes_a_structured_failure():
    output = """
    stdout Measurements for AC Analysis
    stdout unrelated = 123
    """

    results = MeasureParser().parse_measure_output(
        output,
        analysis_type="ac",
        expected_names=["gain"],
    )

    assert len(results) == 1
    assert results[0].name == "gain"
    assert results[0].status is MeasureStatus.FAILED
    assert results[0].value is None
    assert "did not emit an outcome" in results[0].error_message


def test_empty_authoritative_request_set_filters_include_owned_metrics():
    output = """
    stdout Measurements for AC Analysis
    stdout hidden_from_library = 123
    """

    assert MeasureParser().parse_measure_output(
        output,
        analysis_type="ac",
        expected_names=[],
    ) == []
