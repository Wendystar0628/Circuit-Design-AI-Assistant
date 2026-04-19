from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_SUPPLY_PREFIXES: Tuple[str, ...] = (
    "vcc",
    "vdd",
    "vee",
    "vss",
    "avdd",
    "avss",
    "dvdd",
    "dvss",
    "pvdd",
    "pvss",
    "vpp",
    "vnn",
)
_SOURCE_PREFIXES: Tuple[str, ...] = (
    "vin",
    "vip",
    "vinp",
    "vinn",
    "vp",
    "vn",
    "vref",
    "ibias",
    "vbias",
    "tail",
    "bias",
)
_PROBE_PREFIXES: Tuple[str, ...] = (
    "probe",
    "test",
    "tp",
    "sense",
    "mon",
    "meas",
    "dbg",
)
_DEVICE_PREFIX_RANK: Dict[str, int] = {
    "V": 0,
    "I": 0,
    "Q": 1,
    "M": 2,
    "J": 3,
    "D": 4,
    "R": 5,
    "C": 6,
    "L": 7,
    "X": 8,
}
_DEVICE_PARAM_PRIORITY: Tuple[str, ...] = (
    "id",
    "ic",
    "ib",
    "ie",
    "is",
    "gm",
    "gds",
    "gmb",
    "gmbs",
    "vgs",
    "vds",
    "vdsat",
    "vth",
    "vbe",
    "vce",
    "vbc",
    "beta",
    "ro",
)
_REGION_PARAM_NAMES = {"region", "operating_region", "op_region", "mode", "state"}
_MOS_REGION_CODE_MAP: Dict[int, str] = {
    0: "cutoff",
    1: "linear",
    2: "saturation",
    3: "subthreshold",
}
_PARAM_UNIT_MAP: Dict[str, str] = {
    "id": "A",
    "ic": "A",
    "ib": "A",
    "ie": "A",
    "is": "A",
    "gm": "S",
    "gds": "S",
    "gmb": "S",
    "gmbs": "S",
    "vgs": "V",
    "vds": "V",
    "vdsat": "V",
    "vth": "V",
    "vbe": "V",
    "vce": "V",
    "vbc": "V",
    "ro": "Ω",
}
_DEVICE_PARAM_PATTERN = re.compile(r"^@(?P<device>.+?)\[(?P<param>[^\]]+)\]$")


def extract_signal_target(signal_name: str) -> str:
    if len(signal_name) >= 4 and signal_name[1] == "(" and signal_name.endswith(")"):
        return signal_name[2:-1]
    return signal_name


def op_result_node_name_sort_key(name: str) -> Tuple[int, int, str]:
    target = extract_signal_target(str(name or "")).strip()
    lowered = target.lower()
    if lowered in {"0", "gnd", "ground"}:
        return (0, 0, lowered)
    if lowered.startswith(_SUPPLY_PREFIXES):
        return (0, 1, lowered)
    if lowered.startswith(_SOURCE_PREFIXES):
        return (0, 2, lowered)
    if lowered.startswith(_PROBE_PREFIXES):
        return (2, 0, lowered)
    return (1, 0, lowered)


def op_result_branch_name_sort_key(name: str) -> Tuple[int, str]:
    target = extract_signal_target(str(name or "")).strip()
    return (_DEVICE_PREFIX_RANK.get(target[:1].upper(), 99), target.lower())


def op_result_device_name_sort_key(name: str) -> Tuple[int, str]:
    target = str(name or "").strip()
    return (_DEVICE_PREFIX_RANK.get(target[:1].upper(), 99), target.lower())


def sort_op_result_node_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: op_result_node_name_sort_key(str(row.get("name") or "")))


def sort_op_result_branch_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: op_result_branch_name_sort_key(str(row.get("device") or row.get("name") or "")))


def sort_op_result_device_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: op_result_device_name_sort_key(str(row.get("device") or "")))


def normalize_op_result_payload(value: Any) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    nodes = sort_op_result_node_rows(_normalize_node_rows(payload.get("nodes")))
    branches = sort_op_result_branch_rows(_normalize_branch_rows(payload.get("branches")))
    devices = sort_op_result_device_rows(_normalize_device_rows(payload.get("devices")))
    return {
        "nodes": nodes,
        "branches": branches,
        "devices": devices,
        "row_count": len(nodes) + len(branches) + len(devices),
        "section_count": 2 + (1 if devices else 0) if (nodes or branches or devices) else 0,
    }


def build_op_result_payload_from_signals(signals: Dict[str, Any], signal_types: Dict[str, str]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    branches: List[Dict[str, Any]] = []
    device_parameters: Dict[str, Dict[str, float]] = {}

    for signal_name, signal_value in (signals or {}).items():
        scalar = _extract_scalar(signal_value)
        if scalar is None:
            continue
        upper_name = str(signal_name).upper()
        if upper_name.startswith("V("):
            node_name = extract_signal_target(str(signal_name))
            nodes.append({
                "name": node_name,
                "voltage": scalar,
                "formatted": _format_value(scalar, "V"),
            })
            continue
        if upper_name.startswith("I("):
            device_name = extract_signal_target(str(signal_name))
            branches.append({
                "device": device_name,
                "current": scalar,
                "formatted": _format_value(scalar, "A"),
            })
            continue
        device_name, parameter_name = _extract_device_parameter(str(signal_name))
        if not device_name or not parameter_name:
            continue
        device_parameters.setdefault(device_name, {})[parameter_name] = scalar

    return normalize_op_result_payload({
        "nodes": nodes,
        "branches": branches,
        "devices": _build_device_rows(device_parameters),
    })


def build_op_result_sections(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = normalize_op_result_payload(payload)
    sections = [
        {
            "id": "nodes",
            "title": "节点电压",
            "row_count": len(normalized["nodes"]),
            "rows": [
                {
                    "name": row["name"],
                    "formatted_value": row["formatted"],
                    "raw_value": row["voltage"],
                    "unit": "V",
                }
                for row in normalized["nodes"]
            ],
        },
        {
            "id": "branches",
            "title": "支路电流",
            "row_count": len(normalized["branches"]),
            "rows": [
                {
                    "name": row["device"],
                    "formatted_value": row["formatted"],
                    "raw_value": row["current"],
                    "unit": "A",
                }
                for row in normalized["branches"]
            ],
        },
    ]
    if normalized["devices"]:
        sections.append(
            {
                "id": "devices",
                "title": "器件工作点",
                "row_count": len(normalized["devices"]),
                "rows": [
                    {
                        "name": row["device"],
                        "formatted_value": f"{row['operating_region']} | {row['key_parameters_summary']}".strip(" |"),
                        "raw_value": None,
                        "unit": "",
                    }
                    for row in normalized["devices"]
                ],
            }
        )
    return sections


def render_op_result_markdown(payload: Dict[str, Any]) -> str:
    normalized = normalize_op_result_payload(payload)
    blocks = [
        _render_table(
            "nodes",
            ["name", "voltage", "formatted"],
            [
                [row["name"], _format_scalar_column(row["voltage"]), row["formatted"]]
                for row in normalized["nodes"]
            ],
        ),
        _render_table(
            "branches",
            ["device", "current", "formatted"],
            [
                [row["device"], _format_scalar_column(row["current"]), row["formatted"]]
                for row in normalized["branches"]
            ],
        ),
    ]
    if normalized["devices"]:
        blocks.append(
            _render_table(
                "devices",
                ["device", "operating_region", "key_parameters"],
                [
                    [
                        row["device"],
                        row["operating_region"],
                        row["key_parameters_summary"],
                    ]
                    for row in normalized["devices"]
                ],
            )
        )
    return "\n\n".join(blocks).strip()


def _normalize_node_rows(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        voltage = _as_float(item.get("voltage", item.get("raw_value")))
        if not name or voltage is None:
            continue
        formatted = str(item.get("formatted") or item.get("formatted_value") or _format_value(voltage, "V"))
        rows.append({"name": name, "voltage": voltage, "formatted": formatted})
    return rows


def _normalize_branch_rows(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        device = str(item.get("device") or item.get("name") or "").strip()
        current = _as_float(item.get("current", item.get("raw_value")))
        if not device or current is None:
            continue
        formatted = str(item.get("formatted") or item.get("formatted_value") or _format_value(current, "A"))
        rows.append({"device": device, "current": current, "formatted": formatted})
    return rows


def _normalize_device_rows(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        device = str(item.get("device") or "").strip()
        operating_region = str(item.get("operating_region") or "").strip()
        if not device or not operating_region:
            continue
        key_parameters = _normalize_key_parameters(item.get("key_parameters"))
        key_parameters_summary = str(item.get("key_parameters_summary") or _summarize_key_parameters(key_parameters))
        rows.append(
            {
                "device": device,
                "operating_region": operating_region,
                "key_parameters": key_parameters,
                "key_parameters_summary": key_parameters_summary,
            }
        )
    return rows


def _normalize_key_parameters(value: Any) -> List[Dict[str, Any]]:
    parameters: List[Dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        numeric = _as_float(item.get("value"))
        if not name or numeric is None:
            continue
        unit = str(item.get("unit") or "").strip()
        formatted = str(item.get("formatted") or _format_value(numeric, unit))
        parameters.append({"name": name, "value": numeric, "unit": unit, "formatted": formatted})
    return parameters


def _extract_scalar(value: Any) -> Optional[float]:
    if value is None:
        return None
    if np.isscalar(value):
        return _as_float(value)
    try:
        length = len(value)
    except TypeError:
        return _as_float(value)
    if length == 0:
        return None
    candidate = value[0]
    if np.iscomplexobj(candidate):
        complex_value = complex(candidate)
        if abs(complex_value.imag) > 1e-15:
            return None
        candidate = complex_value.real
    return _as_float(candidate)


def _extract_device_parameter(signal_name: str) -> Tuple[str, str]:
    match = _DEVICE_PARAM_PATTERN.match(signal_name.strip())
    if not match:
        return "", ""
    device = match.group("device").strip()
    parameter = match.group("param").strip().lower()
    if not device or not parameter:
        return "", ""
    return device.split(".")[-1], parameter


def _build_device_rows(device_parameters: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for device_name, parameters in device_parameters.items():
        operating_region = _resolve_operating_region(parameters)
        if not operating_region:
            continue
        key_parameters = _build_key_parameters(parameters)
        rows.append(
            {
                "device": device_name,
                "operating_region": operating_region,
                "key_parameters": key_parameters,
                "key_parameters_summary": _summarize_key_parameters(key_parameters),
            }
        )
    return rows


def _resolve_operating_region(parameters: Dict[str, float]) -> str:
    for parameter_name in _REGION_PARAM_NAMES:
        if parameter_name not in parameters:
            continue
        numeric = _as_float(parameters.get(parameter_name))
        if numeric is None:
            continue
        rounded = int(round(numeric))
        if abs(numeric - rounded) <= 1e-9 and rounded in _MOS_REGION_CODE_MAP:
            return _MOS_REGION_CODE_MAP[rounded]
        return _format_scalar_column(numeric)
    return ""


def _build_key_parameters(parameters: Dict[str, float]) -> List[Dict[str, Any]]:
    ordered_names: List[str] = [name for name in _DEVICE_PARAM_PRIORITY if name in parameters]
    ordered_names.extend(
        sorted(
            name for name in parameters.keys()
            if name not in _REGION_PARAM_NAMES and name not in ordered_names
        )
    )
    key_parameters: List[Dict[str, Any]] = []
    for name in ordered_names:
        if name in _REGION_PARAM_NAMES:
            continue
        numeric = _as_float(parameters.get(name))
        if numeric is None:
            continue
        unit = _PARAM_UNIT_MAP.get(name, "")
        key_parameters.append(
            {
                "name": name,
                "value": numeric,
                "unit": unit,
                "formatted": _format_value(numeric, unit),
            }
        )
        if len(key_parameters) >= 6:
            break
    return key_parameters


def _summarize_key_parameters(parameters: List[Dict[str, Any]]) -> str:
    return "; ".join(
        f"{str(item.get('name') or '')}={str(item.get('formatted') or '')}".strip("=")
        for item in parameters
        if str(item.get("name") or "") and str(item.get("formatted") or "")
    )


def _format_value(value: float, unit: str = "") -> str:
    return f"{value:.6g} {unit}".strip()


def _format_scalar_column(value: float) -> str:
    return f"{value:.6g}"


def _as_float(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _render_table(title: str, columns: List[str], rows: List[List[str]]) -> str:
    header = [f"## {title}", f"| {' | '.join(columns)} |", f"| {' | '.join('---' for _ in columns)} |"]
    body_rows = rows or [["(none)", *([""] * (len(columns) - 1))]]
    body = [f"| {' | '.join(str(cell or '') for cell in row)} |" for row in body_rows]
    return "\n".join(header + body)


__all__ = [
    "build_op_result_payload_from_signals",
    "build_op_result_sections",
    "extract_signal_target",
    "normalize_op_result_payload",
    "op_result_branch_name_sort_key",
    "op_result_device_name_sort_key",
    "op_result_node_name_sort_key",
    "render_op_result_markdown",
    "sort_op_result_branch_rows",
    "sort_op_result_device_rows",
    "sort_op_result_node_rows",
]
