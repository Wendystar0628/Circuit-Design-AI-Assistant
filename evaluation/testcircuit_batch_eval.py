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

from domain.simulation.executor.executor_registry import ExecutorRegistry
from domain.simulation.executor.spice_executor import SpiceExecutor
from domain.simulation.spice.analysis_directive_authority import detect_last_analysis_type_from_text
from domain.services.simulation_service import SimulationService
from infrastructure.utils.ngspice_config import configure_ngspice
from evaluation.results_eval_utils import (
    bundle_has_expected_files,
    count_components_in_cir_text,
    count_measure_directives,
    count_signal_entries,
    count_x_axis_points,
    describe_numeric,
    group_from_relative_path,
    has_measure_directive,
    iter_circuit_files,
    load_json,
    metric_rows_to_dict,
    normalize_for_csv,
    subgroup_from_relative_path,
    write_csv,
    write_json,
)

logger = logging.getLogger("evaluation.testcircuit_batch")


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return load_json(path)
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


def _build_record(test_root: Path, circuit_path: Path, service: SimulationService) -> Dict[str, Any]:
    source_text = circuit_path.read_text(encoding="utf-8", errors="ignore")
    relative_path = circuit_path.relative_to(test_root).as_posix()
    has_measure = has_measure_directive(source_text)
    measure_count = count_measure_directives(source_text)
    expected_analysis_type = detect_last_analysis_type_from_text(source_text)
    source_component_count = count_components_in_cir_text(source_text)

    result, result_path = service.run_simulation(
        file_path=str(circuit_path),
        project_root=str(test_root),
    )

    bundle_dir = test_root / Path(result_path).parent if result_path else None
    result_payload = _safe_load_json(bundle_dir / "result.json") if bundle_dir else {}
    manifest_payload = _safe_load_json(bundle_dir / "export_manifest.json") if bundle_dir else {}
    analysis_payload = _safe_load_json(bundle_dir / "analysis_info" / "analysis_info.json") if bundle_dir else {}
    output_log_payload = _safe_load_json(bundle_dir / "output_log" / "output_log.json") if bundle_dir else {}
    metrics_payload = _safe_load_json(bundle_dir / "metrics" / "metrics.json") if bundle_dir else {}

    metric_rows = ((metrics_payload.get("data") or {}).get("rows") or []) if metrics_payload else []
    output_summary = output_log_payload.get("summary") or {}
    manifest_summary = manifest_payload.get("summary") or {}
    analysis_meta = analysis_payload.get("metadata") or {}

    duration_ms = float(result.duration_seconds) * 1000.0
    if analysis_meta.get("duration_seconds") is not None:
        try:
            duration_ms = float(analysis_meta.get("duration_seconds")) * 1000.0
        except (TypeError, ValueError):
            pass

    actual_analysis_type = str(
        analysis_meta.get("analysis_type")
        or result_payload.get("analysis_type")
        or result.analysis_type
        or expected_analysis_type
        or "unknown"
    ).lower()

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
        "simulation_success": bool(result.success),
        "duration_ms": duration_ms,
        "metric_row_count": len(metric_rows),
        "metric_values": metric_rows_to_dict(metrics_payload) if metrics_payload else {},
        "warning_count": int(output_summary.get("warning_count") or 0),
        "error_count": int(output_summary.get("error_count") or 0),
        "first_error": output_summary.get("first_error"),
        "data_point_count": count_x_axis_points(result_payload) if result_payload else 0,
        "signal_count": count_signal_entries(result_payload) if result_payload else 0,
        "artifact_file_count": int(manifest_summary.get("exported_file_count") or 0),
        "bundle_complete": bool(bundle_dir) and bundle_has_expected_files(bundle_dir, has_measure),
        "result_path": result_path,
        "bundle_dir": bundle_dir.as_posix() if bundle_dir else "",
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
    registry = ExecutorRegistry()
    spice_executor = SpiceExecutor()
    if not spice_executor.is_available():
        raise RuntimeError(spice_executor._init_error or "SpiceExecutor is not available")
    registry.register(spice_executor)
    service = SimulationService(registry=registry)

    records: List[Dict[str, Any]] = []
    for index, circuit_path in enumerate(circuit_files, start=1):
        logger.info("[%d/%d] Running %s", index, len(circuit_files), circuit_path.relative_to(root).as_posix())
        records.append(_build_record(root, circuit_path, service))

    successes = [r for r in records if r["simulation_success"]]
    failures = [r for r in records if not r["simulation_success"]]
    measured_circuits = [r for r in records if r["has_measure"]]
    measured_successes = [r for r in measured_circuits if r["simulation_success"]]
    metric_captured = [r for r in measured_successes if r["metric_row_count"] > 0]
    bundle_complete = [r for r in successes if r["bundle_complete"]]

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
            "bundle_complete_rate_pct": (len(bundle_complete) / len(successes) * 100.0) if successes else 0.0,
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
    print(f"Bundle complete rate:  {summary['bundle_complete_rate_pct']:.2f}%")
    metric_capture = summary.get("metric_capture_rate_pct")
    print(f"Metric capture rate:   {metric_capture:.2f}%" if metric_capture is not None else "Metric capture rate:   N/A")
    duration_mean = (summary.get("duration_ms") or {}).get("mean")
    duration_p95 = (summary.get("duration_ms") or {}).get("p95")
    if duration_mean is not None and duration_p95 is not None:
        print(f"Duration mean / p95:   {duration_mean:.3f} ms / {duration_p95:.3f} ms")
    print("=" * 60)


if __name__ == "__main__":
    main()
