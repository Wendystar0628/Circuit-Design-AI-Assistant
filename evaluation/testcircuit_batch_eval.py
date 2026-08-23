from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from domain.simulation.executor.spice_executor import SpiceExecutor  # noqa: E402
from domain.simulation.data.simulation_output_reader import simulation_output_reader  # noqa: E402
from domain.simulation.measure.measure_result import MeasureStatus  # noqa: E402
from domain.simulation.spice.source_closure import collect_spice_source_closure  # noqa: E402
from domain.simulation.service.simulation_result_repository import simulation_result_repository  # noqa: E402
from domain.services.simulation_service import SimulationService  # noqa: E402
from infrastructure.utils.ngspice_config import configure_ngspice  # noqa: E402
from evaluation.results_eval_utils import (  # noqa: E402
    count_components_in_cir_text,
    count_measure_directives,
    count_signal_entries,
    count_x_axis_points,
    describe_numeric,
    group_from_relative_path,
    has_measure_directive,
    iter_circuit_files,
    normalize_for_csv,
    subgroup_from_relative_path,
    write_csv,
    write_json,
)

logger = logging.getLogger("evaluation.testcircuit_batch")


def _build_record(test_root: Path, circuit_path: Path, service: SimulationService) -> Dict[str, Any]:
    source_text = circuit_path.read_text(encoding="utf-8", errors="ignore")
    relative_path = circuit_path.relative_to(test_root).as_posix()
    has_measure = has_measure_directive(source_text)
    measure_count = count_measure_directives(source_text)
    analysis_commands = collect_spice_source_closure(
        circuit_path
    ).main_analysis_commands
    expected_analysis_type = (
        analysis_commands[0].analysis_type
        if len(analysis_commands) == 1
        else "unknown"
    )
    source_component_count = count_components_in_cir_text(source_text)

    result_path = ""
    try:
        result_path = service.run_simulation(
            file_path=str(circuit_path),
            project_root=str(test_root),
        )
        loaded = simulation_result_repository.load(str(test_root), result_path)
        if not loaded.success or loaded.data is None:
            raise RuntimeError(
                loaded.error_message
                or f"Simulation result could not be loaded: {result_path}"
            )
    except Exception as exc:
        persistence_error = str(exc) or type(exc).__name__
        return {
            "circuit_rel_path": relative_path,
            "circuit_name": circuit_path.name,
            "circuit_stem": circuit_path.stem,
            "group": group_from_relative_path(relative_path),
            "subgroup": subgroup_from_relative_path(relative_path),
            "expected_analysis_type": expected_analysis_type,
            "actual_analysis_type": str(expected_analysis_type or "unknown").lower(),
            "component_count": source_component_count,
            "measure_directive_count": measure_count,
            "has_measure": has_measure,
            "result_valid": False,
            "persistence_error": persistence_error,
            "source_digest": None,
            "simulation_success": False,
            "duration_ms": None,
            "metric_row_count": 0,
            "metric_values": {},
            "warning_count": 0,
            "error_count": 0,
            "first_error": persistence_error,
            "data_point_count": 0,
            "signal_count": 0,
            "result_path": str(result_path or ""),
            "bundle_dir": "",
        }
    authoritative = loaded.data
    bundle_dir = test_root / Path(result_path).parent
    metric_values = {
        measurement.name: float(measurement.value)
        for measurement in (authoritative.measurements or [])
        if measurement.status is MeasureStatus.OK
        and measurement.is_valid
        and measurement.value is not None
    }
    output_summary = simulation_output_reader.summarize_text(
        authoritative.raw_output or ""
    )
    duration_ms = float(authoritative.duration_seconds) * 1000.0
    actual_analysis_type = str(
        authoritative.analysis_type or expected_analysis_type or "unknown"
    ).lower()
    first_error = output_summary.first_error
    if not first_error and authoritative.error is not None:
        first_error = str(
            getattr(authoritative.error, "message", authoritative.error)
        )

    record = {
        "circuit_rel_path": relative_path,
        "circuit_name": circuit_path.name,
        "circuit_stem": circuit_path.stem,
        "group": group_from_relative_path(relative_path),
        "subgroup": subgroup_from_relative_path(relative_path),
        "expected_analysis_type": expected_analysis_type,
        "actual_analysis_type": actual_analysis_type,
        "component_count": source_component_count,
        "measure_directive_count": measure_count,
        "has_measure": has_measure,
        "result_valid": True,
        "persistence_error": "",
        "source_digest": authoritative.source_digest,
        "simulation_success": bool(authoritative.success),
        "duration_ms": duration_ms,
        "metric_row_count": len(metric_values),
        "metric_values": metric_values,
        "warning_count": output_summary.warning_count,
        "error_count": output_summary.error_count,
        "first_error": first_error,
        "data_point_count": count_x_axis_points(authoritative),
        "signal_count": count_signal_entries(authoritative),
        "result_path": result_path,
        "bundle_dir": bundle_dir.as_posix(),
    }
    return record


def _build_group_summary(records: List[Dict[str, Any]], key_name: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key_name) or "unknown")].append(record)

    summary: Dict[str, Dict[str, Any]] = {}
    for key, group_records in sorted(grouped.items()):
        successes = [r for r in group_records if r["simulation_success"]]
        measured_successes = [r for r in group_records if r["has_measure"] and r["simulation_success"]]
        metric_captured = [r for r in measured_successes if r["metric_row_count"] > 0]
        summary[key] = {
            "count": len(group_records),
            "success_count": len(successes),
            "success_rate_pct": (len(successes) / len(group_records) * 100.0) if group_records else 0.0,
            "mean_duration_ms": describe_numeric([r["duration_ms"] for r in successes]).get("mean"),
            "p95_duration_ms": describe_numeric([r["duration_ms"] for r in successes]).get("p95"),
            "mean_component_count": describe_numeric([r["component_count"] for r in group_records]).get("mean"),
            "measured_circuit_count": sum(1 for r in group_records if r["has_measure"]),
            "metric_capture_rate_pct": (len(metric_captured) / len(measured_successes) * 100.0) if measured_successes else None,
        }
    return summary


def run_batch(test_root: str, output_json: str, output_csv: str) -> Dict[str, Any]:
    root = Path(test_root).expanduser().resolve()
    circuit_files = iter_circuit_files(root)

    configure_ngspice()
    spice_executor = SpiceExecutor()
    if not spice_executor.is_available():
        raise RuntimeError(spice_executor._init_error or "SpiceExecutor is not available")
    service = SimulationService(executor=spice_executor)

    records: List[Dict[str, Any]] = []
    for index, circuit_path in enumerate(circuit_files, start=1):
        logger.info("[%d/%d] Running %s", index, len(circuit_files), circuit_path.relative_to(root).as_posix())
        records.append(_build_record(root, circuit_path, service))

    successes = [r for r in records if r["simulation_success"]]
    failures = [r for r in records if not r["simulation_success"]]
    valid_results = [r for r in records if r["result_valid"]]
    invalid_results = [r for r in records if not r["result_valid"]]
    measured_circuits = [r for r in records if r["has_measure"]]
    measured_successes = [r for r in measured_circuits if r["simulation_success"]]
    metric_captured = [r for r in measured_successes if r["metric_row_count"] > 0]
    analysis_counter = Counter(r["actual_analysis_type"] for r in records)
    group_counter = Counter(r["group"] for r in records)
    subgroup_counter = Counter(r["subgroup"] for r in records)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_root": str(root),
        "summary": {
            "total_circuits": len(records),
            "topology_group_count": len(group_counter),
            "topology_subgroup_count": len(subgroup_counter),
            "success_count": len(successes),
            "failure_count": len(failures),
            "success_rate_pct": (len(successes) / len(records) * 100.0) if records else 0.0,
            "result_valid_count": len(valid_results),
            "result_invalid_count": len(invalid_results),
            "result_valid_rate_pct": (len(valid_results) / len(records) * 100.0) if records else 0.0,
            "measured_circuit_count": len(measured_circuits),
            "metric_capture_rate_pct": (len(metric_captured) / len(measured_successes) * 100.0) if measured_successes else None,
            "analysis_type_distribution": dict(sorted(analysis_counter.items())),
            "group_distribution": dict(sorted(group_counter.items())),
            "subgroup_distribution": dict(sorted(subgroup_counter.items())),
            "duration_ms": describe_numeric([r["duration_ms"] for r in successes]),
            "component_count": describe_numeric([r["component_count"] for r in records]),
            "data_point_count": describe_numeric([r["data_point_count"] for r in successes]),
            "signal_count": describe_numeric([r["signal_count"] for r in successes]),
            "warning_count": describe_numeric([r["warning_count"] for r in records]),
            "error_count": describe_numeric([r["error_count"] for r in records]),
        },
        "per_group": _build_group_summary(records, "group"),
        "per_subgroup": _build_group_summary(records, "subgroup"),
        "per_analysis_type": _build_group_summary(records, "actual_analysis_type"),
        "failures": [
            {
                "circuit_rel_path": r["circuit_rel_path"],
                "actual_analysis_type": r["actual_analysis_type"],
                "first_error": r["first_error"],
                "error_count": r["error_count"],
                "result_valid": r["result_valid"],
                "persistence_error": r["persistence_error"],
            }
            for r in failures
        ],
        "records": records,
    }

    write_json(output_json, payload)
    write_csv(output_csv, [{k: normalize_for_csv(v) for k, v in row.items()} for row in records])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch rerun TestCircuit and collect thesis-ready metrics")
    parser.add_argument("--test_root", default=str(_PROJECT_ROOT / "TestCircuit"))
    parser.add_argument("--output_json", default=str(_PROJECT_ROOT / "evaluation" / "reports" / "testcircuit_batch_eval.json"))
    parser.add_argument("--output_csv", default=str(_PROJECT_ROOT / "evaluation" / "reports" / "testcircuit_batch_eval.csv"))
    parser.add_argument("--log_level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    payload = run_batch(args.test_root, args.output_json, args.output_csv)
    summary = payload["summary"]
    print("=" * 60)
    print("TESTCIRCUIT BATCH EVAL")
    print("=" * 60)
    print(f"Total circuits:        {summary['total_circuits']}")
    print(f"Success count:         {summary['success_count']}")
    print(f"Success rate:          {summary['success_rate_pct']:.2f}%")
    metric_capture = summary.get("metric_capture_rate_pct")
    print(f"Metric capture rate:   {metric_capture:.2f}%" if metric_capture is not None else "Metric capture rate:   N/A")
    duration_mean = (summary.get("duration_ms") or {}).get("mean")
    duration_p95 = (summary.get("duration_ms") or {}).get("p95")
    if duration_mean is not None and duration_p95 is not None:
        print(f"Duration mean / p95:   {duration_mean:.3f} ms / {duration_p95:.3f} ms")
    print("=" * 60)


if __name__ == "__main__":
    main()
