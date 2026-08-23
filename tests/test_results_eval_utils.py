import json
import math
from pathlib import Path

import numpy as np

from domain.simulation.data.simulation_artifact_persistence import (
    simulation_artifact_persistence,
)
from domain.simulation.models.simulation_result import SimulationData, create_success_result
from domain.simulation.spice.source_closure import collect_spice_source_closure
from evaluation.results_eval_utils import (
    count_signal_entries,
    count_measure_directives,
    count_x_axis_points,
    describe_numeric,
    has_measure_directive,
)
from evaluation.simulation_results_summary import _summarize_bundle
from evaluation.testcircuit_batch_eval import _build_record


def test_measure_directive_detection_accepts_official_short_and_long_forms() -> None:
    netlist = """\
* both spellings are accepted by ngspice
.meas tran rise_time TRIG v(out) VAL=1 RISE=1 TARG v(out) VAL=4 RISE=1
.measure ac peak MAX vdb(out)
.measurement tran ignored MAX v(out)
"""

    assert has_measure_directive(netlist)
    assert count_measure_directives(netlist) == 2


def test_result_summary_uses_only_embedded_result_truth(tmp_path) -> None:
    result = create_success_result(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        source_digest="0" * 64,
        analysis_command=".tran 1n 2n",
        raw_output="warning: floating node\nerror: synthetic diagnostic",
        data=SimulationData(
            time=np.asarray([0.0, 2e-9]),
            signals={"V(out)": np.asarray([0.0, 1.0])},
            signal_types={"V(out)": "voltage"},
        ),
    )
    results_root = tmp_path / "simulation_results"
    bundle = results_root / "amp" / "run"
    bundle.mkdir(parents=True)
    result_path = bundle / "result.json"
    result_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

    # A contradictory legacy sidecar must be irrelevant to evaluation.
    legacy_log = bundle / "output_log" / "output_log.json"
    legacy_log.parent.mkdir()
    legacy_log.write_text(
        json.dumps({"summary": {"warning_count": 0, "error_count": 0}}),
        encoding="utf-8",
    )

    record = _summarize_bundle(result_path, results_root)

    assert count_x_axis_points(result) == 2
    assert count_signal_entries(result) == 1
    assert record["warning_count"] == 1
    assert record["error_count"] == 1
    assert record["data_point_count"] == 2
    assert record["signal_count"] == 1
    assert "artifact_file_count" not in record


def test_batch_record_loads_the_path_only_service_result_through_repository(
    tmp_path,
) -> None:
    circuit = tmp_path / "amp.cir"
    circuit.write_text("amp\nV1 out 0 1\n.tran 1n 2n\n.end\n", encoding="utf-8")

    class _PathOnlyService:
        def run_simulation(self, *, file_path: str, project_root: str) -> str:
            result = create_success_result(
                executor="spice",
                file_path=file_path,
                analysis_type="tran",
                source_digest=collect_spice_source_closure(file_path).digest,
                data=SimulationData(
                    time=np.asarray([0.0, 2e-9]),
                    signals={"V(out)": np.asarray([0.0, 1.0])},
                    signal_types={"V(out)": "voltage"},
                ),
                analysis_command=".tran 1n 2n",
            )
            return simulation_artifact_persistence.persist_bundle(
                project_root,
                result,
            ).result_path

    record = _build_record(tmp_path, circuit, _PathOnlyService())

    assert record["simulation_success"] is True
    assert record["result_valid"] is True
    assert record["persistence_error"] == ""
    assert record["source_digest"] == collect_spice_source_closure(circuit).digest
    assert record["actual_analysis_type"] == "tran"
    assert record["result_path"].endswith("/result.json")


def test_batch_record_reports_invalid_authoritative_result_without_sidecar_fallback(
    tmp_path,
) -> None:
    circuit = tmp_path / "broken.cir"
    circuit.write_text("broken\nV1 out 0 1\n.tran 1n 2n\n.end\n", encoding="utf-8")

    class _MissingResultService:
        def run_simulation(self, *, file_path: str, project_root: str) -> str:
            return "simulation_results/broken/run/result.json"

    record = _build_record(tmp_path, circuit, _MissingResultService())

    assert record["result_valid"] is False
    assert record["simulation_success"] is False
    assert record["persistence_error"]
    assert record["source_digest"] is None
    assert record["metric_values"] == {}


def test_numeric_descriptions_drop_nonfinite_values() -> None:
    summary = describe_numeric([1.0, float("nan"), float("inf"), 3.0])

    assert summary["count"] == 2
    assert summary["mean"] == 2.0
    assert all(
        value is None or math.isfinite(value)
        for key, value in summary.items()
        if key != "count"
    )
