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

from evaluation.results_eval_utils import (
    count_signal_entries,
    count_x_axis_points,
    describe_numeric,
    load_json,
    metric_rows_to_dict,
    normalize_for_csv,
    write_csv,
    write_json,
)

logger = logging.getLogger("evaluation.simulation_results_summary")


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return load_json(path)
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


def _summarize_bundle(result_json_path: Path, results_root: Path) -> Dict[str, Any]:
    bundle_dir = result_json_path.parent
    result_payload = _safe_load_json(result_json_path)
    manifest_payload = _safe_load_json(bundle_dir / "export_manifest.json")
    analysis_payload = _safe_load_json(bundle_dir / "analysis_info" / "analysis_info.json")
    metrics_payload = _safe_load_json(bundle_dir / "metrics" / "metrics.json")
    output_log_payload = _safe_load_json(bundle_dir / "output_log" / "output_log.json")

    result_data = result_payload.get("data") or {}
    result_meta = analysis_payload.get("metadata") or {}
    output_summary = output_log_payload.get("summary") or {}
    manifest_summary = manifest_payload.get("summary") or {}
    metric_rows = ((metrics_payload.get("data") or {}).get("rows") or [])

    circuit_name = str(result_meta.get("file_name") or Path(result_payload.get("file_path") or "").name or bundle_dir.parent.name)
    circuit_stem = Path(circuit_name).stem if circuit_name else bundle_dir.parent.name
    duration_ms = None
    try:
        duration_ms = float(result_meta.get("duration_seconds") or result_payload.get("duration_seconds") or 0.0) * 1000.0
    except (TypeError, ValueError):
        duration_ms = None

    return {
        "bundle_rel_path": bundle_dir.relative_to(results_root).as_posix(),
        "bundle_timestamp": bundle_dir.name,
        "circuit_name": circuit_name,
        "circuit_stem": circuit_stem,
        "analysis_type": str(result_meta.get("analysis_type") or result_payload.get("analysis_type") or "unknown").lower(),
        "success": bool(result_payload.get("success")),
        "duration_ms": duration_ms,
        "metric_row_count": len(metric_rows),
        "metric_values": metric_rows_to_dict(metrics_payload) if metrics_payload else {},
        "artifact_file_count": int(manifest_summary.get("exported_file_count") or 0),
        "manifest_error_count": int(manifest_summary.get("error_count") or 0),
        "warning_count": int(output_summary.get("warning_count") or 0),
        "error_count": int(output_summary.get("error_count") or 0),
        "first_error": output_summary.get("first_error"),
        "data_point_count": count_x_axis_points(result_payload),
        "signal_count": count_signal_entries(result_payload),
        "timestamp": str(result_meta.get("timestamp") or result_payload.get("timestamp") or ""),
        "x_axis_kind": str(result_meta.get("x_axis_kind") or ""),
        "analysis_command": str(result_meta.get("analysis_command") or result_payload.get("analysis_command") or ""),
        "result_file_path": str(result_payload.get("file_path") or ""),
        "has_metrics": len(metric_rows) > 0,
    }


def _latest_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest_by_circuit: Dict[str, Dict[str, Any]] = {}
    for record in records:
        key = record["circuit_stem"]
        existing = latest_by_circuit.get(key)
        if existing is None or str(record.get("timestamp") or "") > str(existing.get("timestamp") or ""):
            latest_by_circuit[key] = record
    return sorted(latest_by_circuit.values(), key=lambda item: item["circuit_stem"])


def summarize_simulation_results(results_root: str, output_json: str, output_csv: str) -> Dict[str, Any]:
    root = Path(results_root).expanduser().resolve()
    result_files = sorted(root.rglob("result.json"))
    records = [_summarize_bundle(path, root) for path in result_files]
    latest = _latest_records(records)

    successes = [r for r in records if r["success"]]
    latest_successes = [r for r in latest if r["success"]]
    analysis_counter = Counter(r["analysis_type"] for r in records)

    per_analysis: Dict[str, Dict[str, Any]] = {}
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["analysis_type"]].append(record)
    for analysis_type, group_records in sorted(grouped.items()):
        successful = [r for r in group_records if r["success"]]
        per_analysis[analysis_type] = {
            "bundle_count": len(group_records),
            "success_count": len(successful),
            "success_rate_pct": (len(successful) / len(group_records) * 100.0) if group_records else 0.0,
            "duration_ms": describe_numeric([r["duration_ms"] for r in successful]),
            "data_point_count": describe_numeric([r["data_point_count"] for r in successful]),
        }

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "simulation_results_root": str(root),
        "summary": {
            "total_bundles": len(records),
            "unique_circuits": len({r['circuit_stem'] for r in records}),
            "success_count": len(successes),
            "success_rate_pct": (len(successes) / len(records) * 100.0) if records else 0.0,
            "latest_bundle_count": len(latest),
            "latest_success_rate_pct": (len(latest_successes) / len(latest) * 100.0) if latest else 0.0,
            "total_artifact_files": sum(int(r["artifact_file_count"] or 0) for r in records),
            "bundles_with_metrics": sum(1 for r in records if r["has_metrics"]),
            "warning_free_rate_pct": (sum(1 for r in records if int(r['warning_count']) == 0) / len(records) * 100.0) if records else 0.0,
            "error_free_rate_pct": (sum(1 for r in records if int(r['error_count']) == 0) / len(records) * 100.0) if records else 0.0,
            "analysis_distribution": dict(sorted(analysis_counter.items())),
            "duration_ms": describe_numeric([r["duration_ms"] for r in successes]),
            "data_point_count": describe_numeric([r["data_point_count"] for r in successes]),
            "signal_count": describe_numeric([r["signal_count"] for r in successes]),
            "metric_row_count": describe_numeric([r["metric_row_count"] for r in records if r["metric_row_count"] > 0]),
            "warning_count": describe_numeric([r["warning_count"] for r in records]),
            "error_count": describe_numeric([r["error_count"] for r in records]),
        },
        "per_analysis_type": per_analysis,
        "latest_records": latest,
        "records": records,
    }

    write_json(output_json, payload)
    write_csv(output_csv, [{k: normalize_for_csv(v) for k, v in row.items()} for row in records])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize existing simulation_results bundles for thesis metrics")
    parser.add_argument("--results_root", default=str(_PROJECT_ROOT / "TestCircuit" / "simulation_results"))
    parser.add_argument("--output_json", default=str(_PROJECT_ROOT / "evaluation" / "reports" / "simulation_results_summary.json"))
    parser.add_argument("--output_csv", default=str(_PROJECT_ROOT / "evaluation" / "reports" / "simulation_results_summary.csv"))
    parser.add_argument("--log_level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    payload = summarize_simulation_results(args.results_root, args.output_json, args.output_csv)
    summary = payload["summary"]
    print("=" * 60)
    print("SIMULATION RESULTS SUMMARY")
    print("=" * 60)
    print(f"Total bundles:         {summary['total_bundles']}")
    print(f"Unique circuits:       {summary['unique_circuits']}")
    print(f"Success rate:          {summary['success_rate_pct']:.2f}%")
    print(f"Latest success rate:   {summary['latest_success_rate_pct']:.2f}%")
    duration_mean = (summary.get("duration_ms") or {}).get("mean")
    duration_p95 = (summary.get("duration_ms") or {}).get("p95")
    if duration_mean is not None and duration_p95 is not None:
        print(f"Duration mean / p95:   {duration_mean:.3f} ms / {duration_p95:.3f} ms")
    print("=" * 60)


if __name__ == "__main__":
    main()
