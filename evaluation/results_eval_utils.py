from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from domain.simulation.models.simulation_result import SimulationResult


_COMPONENT_LINE_RE = re.compile(r"^\s*[A-Z]", re.IGNORECASE)
_DIRECTIVE_LINE_RE = re.compile(r"^\s*\.", re.IGNORECASE)
_COMMENT_LINE_RE = re.compile(r"^\s*\*")
_BLANK_LINE_RE = re.compile(r"^\s*$")
_SYMBOL_LINE_RE = re.compile(r"^\s*SYMBOL\b", re.IGNORECASE)
_MEASURE_LINE_RE = re.compile(
    r"^\s*\.meas(?:ure)?\b",
    re.IGNORECASE | re.MULTILINE,
)


def load_json(file_path: str | Path) -> Dict[str, Any]:
    path = Path(file_path)
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_nonstandard_json_constant,
    )


def _reject_nonstandard_json_constant(token: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant is forbidden: {token}")


def write_json(file_path: str | Path, payload: Dict[str, Any]) -> Path:
    path = Path(file_path)
    _atomic_write_text(
        path,
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    return path


def write_csv(file_path: str | Path, rows: Sequence[Dict[str, Any]]) -> Path:
    path = Path(file_path)
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    _atomic_write_text(path, buffer.getvalue(), encoding="utf-8-sig")
    return path


def _atomic_write_text(path: Path, content: str, *, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding=encoding,
            newline="",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    numeric = sorted(
        number
        for value in values
        if value is not None
        for number in (float(value),)
        if math.isfinite(number)
    )
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
    numeric = [
        number
        for value in values
        if value is not None
        for number in (float(value),)
        if math.isfinite(number)
    ]
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


def load_simulation_result(file_path: str | Path) -> SimulationResult:
    """Strictly load the authoritative document of one result bundle."""
    payload = load_json(file_path)
    return SimulationResult.from_dict(payload)


def count_x_axis_points(result: SimulationResult) -> int:
    data = result.data
    if data is None:
        return 0
    for values in (data.frequency, data.time, data.sweep):
        if values is not None:
            return len(values)
    return 0


def count_signal_entries(result: SimulationResult) -> int:
    return len(result.data.signals) if result.data is not None else 0


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
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value


__all__ = [
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
    "load_simulation_result",
    "normalize_for_csv",
    "percentile",
    "subgroup_from_relative_path",
    "write_csv",
    "write_json",
]
