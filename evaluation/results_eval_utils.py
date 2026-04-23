from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


_COMPONENT_LINE_RE = re.compile(r"^\s*[A-Z]", re.IGNORECASE)
_DIRECTIVE_LINE_RE = re.compile(r"^\s*\.", re.IGNORECASE)
_COMMENT_LINE_RE = re.compile(r"^\s*\*")
_BLANK_LINE_RE = re.compile(r"^\s*$")
_SYMBOL_LINE_RE = re.compile(r"^\s*SYMBOL\b", re.IGNORECASE)
_MEASURE_LINE_RE = re.compile(r"^\s*\.measure\b", re.IGNORECASE | re.MULTILINE)


def load_json(file_path: str | Path) -> Dict[str, Any]:
    path = Path(file_path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(file_path: str | Path, payload: Dict[str, Any]) -> Path:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_csv(file_path: str | Path, rows: Sequence[Dict[str, Any]]) -> Path:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    numeric = sorted(float(v) for v in values if v is not None)
    if not numeric:
        return None
    if len(numeric) == 1:
        return numeric[0]
    if p <= 0:
        return numeric[0]
    if p >= 100:
        return numeric[-1]
    rank = (len(numeric) - 1) * (p / 100.0)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return numeric[lower]
    weight = rank - lower
    return numeric[lower] * (1.0 - weight) + numeric[upper] * weight


def describe_numeric(values: Sequence[float]) -> Dict[str, Optional[float]]:
    numeric = [float(v) for v in values if v is not None]
    if not numeric:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(numeric),
        "mean": sum(numeric) / len(numeric),
        "median": percentile(numeric, 50.0),
        "p95": percentile(numeric, 95.0),
        "min": min(numeric),
        "max": max(numeric),
    }


def count_components_in_cir_text(cir_text: str) -> int:
    count = 0
    for line in str(cir_text or "").splitlines():
        if _BLANK_LINE_RE.match(line):
            continue
        if _COMMENT_LINE_RE.match(line):
            continue
        if _DIRECTIVE_LINE_RE.match(line):
            continue
        if _COMPONENT_LINE_RE.match(line):
            count += 1
    return count


def count_symbols_in_asc_text(asc_text: str) -> int:
    count = 0
    for line in str(asc_text or "").splitlines():
        if _SYMBOL_LINE_RE.match(line):
            count += 1
    return count


def has_measure_directive(netlist_text: str) -> bool:
    return bool(_MEASURE_LINE_RE.search(str(netlist_text or "")))


def count_measure_directives(netlist_text: str) -> int:
    return len(_MEASURE_LINE_RE.findall(str(netlist_text or "")))


def count_x_axis_points(result_payload: Dict[str, Any]) -> int:
    data = result_payload.get("data") or {}
    for axis_name in ("frequency", "time", "sweep"):
        values = data.get(axis_name)
        if isinstance(values, list):
            return len(values)
    return 0


def count_signal_entries(result_payload: Dict[str, Any]) -> int:
    data = result_payload.get("data") or {}
    signals = data.get("signals") or {}
    return len(signals) if isinstance(signals, dict) else 0


def metric_rows_to_dict(metrics_payload: Dict[str, Any]) -> Dict[str, Any]:
    rows = ((metrics_payload.get("data") or {}).get("rows") or [])
    metrics: Dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("display_name") or "").strip()
        if not name:
            continue
        metrics[name] = row.get("raw_value", row.get("value"))
    return metrics


def bundle_has_expected_files(bundle_dir: str | Path, expects_metrics: bool) -> bool:
    root = Path(bundle_dir)
    required_files = [
        root / "result.json",
        root / "export_manifest.json",
        root / "analysis_info" / "analysis_info.json",
        root / "output_log" / "output_log.json",
        root / "raw_data" / "raw_data.json",
    ]
    if expects_metrics:
        required_files.append(root / "metrics" / "metrics.json")
    return all(path.is_file() for path in required_files)


def iter_circuit_files(test_root: str | Path) -> List[Path]:
    root = Path(test_root)
    files: List[Path] = []
    for path in root.rglob("*.cir"):
        lowered_parts = {part.lower() for part in path.parts}
        if "simulation_results" in lowered_parts:
            continue
        if ".circuit_ai" in lowered_parts:
            continue
        files.append(path)
    return sorted(files)


def iter_asc_files(asc_root: str | Path) -> List[Path]:
    root = Path(asc_root)
    return sorted(path for path in root.rglob("*.asc") if path.is_file())


def group_from_relative_path(relative_path: str | Path) -> str:
    rel = Path(relative_path)
    if not rel.parts:
        return "root"
    return rel.parts[0]


def subgroup_from_relative_path(relative_path: str | Path) -> str:
    rel = Path(relative_path)
    if len(rel.parts) >= 2 and rel.parts[0].lower() == "by_device":
        return "/".join(rel.parts[:2])
    if rel.parts:
        return rel.parts[0]
    return "root"


def normalize_for_csv(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


__all__ = [
    "bundle_has_expected_files",
    "count_components_in_cir_text",
    "count_measure_directives",
    "count_signal_entries",
    "count_symbols_in_asc_text",
    "count_x_axis_points",
    "describe_numeric",
    "group_from_relative_path",
    "has_measure_directive",
    "iter_asc_files",
    "iter_circuit_files",
    "load_json",
    "metric_rows_to_dict",
    "normalize_for_csv",
    "percentile",
    "subgroup_from_relative_path",
    "write_csv",
    "write_json",
]
