"""Strict schema for the three authoritative simulation lifecycle events."""

from __future__ import annotations

import copy
import math
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

from shared.event_types import EVENT_SIM_COMPLETE, EVENT_SIM_ERROR, EVENT_SIM_STARTED


_COMMON_IDENTITY_FIELDS: Tuple[str, ...] = (
    "job_id",
    "origin",
    "circuit_file",
    "project_root",
    "session_id",
)

SIM_PAYLOAD_FIELDS: Dict[str, Tuple[str, ...]] = {
    EVENT_SIM_STARTED: _COMMON_IDENTITY_FIELDS,
    EVENT_SIM_COMPLETE: _COMMON_IDENTITY_FIELDS
    + ("result_path", "export_root", "duration_seconds"),
    EVENT_SIM_ERROR: _COMMON_IDENTITY_FIELDS
    + (
        "error_message",
        "result_path",
        "export_root",
        "cancelled",
        "duration_seconds",
    ),
}

SIM_LIFECYCLE_EVENT_TYPES: Tuple[str, ...] = tuple(SIM_PAYLOAD_FIELDS)
_ORIGINS = frozenset({"ui_editor", "agent_tool"})


class MissingSimPayloadFieldError(ValueError):
    def __init__(self, event_type: str, missing: Tuple[str, ...], payload: Any):
        self.event_type = event_type
        self.missing = missing
        self.payload = payload
        super().__init__(
            f"Simulation event {event_type!r} is missing fields {list(missing)}"
        )


class InvalidSimEventEnvelopeError(ValueError):
    """The EventBus envelope is absent, malformed, or mislabeled."""


class InvalidSimPayloadError(ValueError):
    """A lifecycle payload has fields with invalid types or semantics."""


def _path(path: str) -> PurePath:
    if len(path) >= 3 and path[1] == ":" and path[2] in ("/", "\\"):
        return PureWindowsPath(path)
    return PurePosixPath(path)


def _require_nonempty_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise InvalidSimPayloadError(f"{field} must be a non-empty string")
    return value


def _require_absolute_path(payload: Mapping[str, Any], field: str) -> PurePath:
    value = _require_nonempty_string(payload, field)
    parsed = _path(value)
    if not parsed.is_absolute():
        raise InvalidSimPayloadError(f"{field} must be an absolute path")
    return parsed


def _validate_duration(payload: Mapping[str, Any]) -> None:
    value = payload["duration_seconds"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidSimPayloadError("duration_seconds must be a number")
    if not math.isfinite(float(value)) or float(value) < 0:
        raise InvalidSimPayloadError(
            "duration_seconds must be finite and non-negative"
        )


def _validate_bundle(
    payload: Mapping[str, Any],
    *,
    required: bool,
) -> None:
    result_path = payload["result_path"]
    export_root = payload["export_root"]
    if not isinstance(result_path, str) or not isinstance(export_root, str):
        raise InvalidSimPayloadError("result_path and export_root must be strings")
    if bool(result_path) != bool(export_root):
        raise InvalidSimPayloadError(
            "result_path and export_root must both be present or both be empty"
        )
    if not result_path:
        if required:
            raise InvalidSimPayloadError("completed simulations require a bundle")
        return

    relative = PurePosixPath(result_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or str(relative) != result_path
        or relative.name != "result.json"
        or len(relative.parts) < 4
        or relative.parts[0] != "simulation_results"
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or part.startswith(".__bundle_tmp__")
            for part in relative.parts
        )
    ):
        raise InvalidSimPayloadError(
            "result_path must be a canonical simulation_results/.../result.json path"
        )

    project_root = _require_absolute_path(payload, "project_root")
    export = _require_absolute_path(payload, "export_root")
    if type(project_root) is not type(export):
        raise InvalidSimPayloadError("project_root and export_root use different path forms")
    expected = project_root.joinpath(*relative.parent.parts)
    if isinstance(expected, PureWindowsPath):
        matches = str(expected).casefold() == str(export).casefold()
    else:
        matches = expected == export
    if not matches:
        raise InvalidSimPayloadError(
            "export_root must be the absolute parent of project_root/result_path"
        )


def validate_sim_payload(
    event_type: str,
    payload: Any,
) -> Mapping[str, Any]:
    """Validate an inner payload and return an isolated read-only copy."""

    required = SIM_PAYLOAD_FIELDS[event_type]
    if not isinstance(payload, Mapping):
        raise InvalidSimPayloadError("simulation payload must be a mapping")

    missing = tuple(field for field in required if field not in payload)
    if missing:
        raise MissingSimPayloadFieldError(event_type, missing, payload)
    extras = tuple(sorted(set(payload) - set(required)))
    if extras:
        raise InvalidSimPayloadError(
            f"Simulation event {event_type!r} has unexpected fields {list(extras)}"
        )

    job_id = _require_nonempty_string(payload, "job_id")
    if not job_id.startswith("job_"):
        raise InvalidSimPayloadError("job_id must use the canonical job_ prefix")
    origin = _require_nonempty_string(payload, "origin")
    if origin not in _ORIGINS:
        raise InvalidSimPayloadError(f"unsupported simulation origin {origin!r}")
    circuit_file = _require_absolute_path(payload, "circuit_file")
    project_root = _require_absolute_path(payload, "project_root")
    if type(circuit_file) is not type(project_root):
        raise InvalidSimPayloadError(
            "circuit_file and project_root use different path forms"
        )
    try:
        circuit_file.relative_to(project_root)
    except ValueError as exc:
        raise InvalidSimPayloadError(
            "circuit_file must be inside project_root"
        ) from exc
    if not isinstance(payload["session_id"], str):
        raise InvalidSimPayloadError("session_id must be a string")

    if event_type == EVENT_SIM_COMPLETE:
        _validate_bundle(payload, required=True)
        _validate_duration(payload)
    elif event_type == EVENT_SIM_ERROR:
        _require_nonempty_string(payload, "error_message")
        if type(payload["cancelled"]) is not bool:
            raise InvalidSimPayloadError("cancelled must be a bool")
        _validate_bundle(payload, required=False)
        _validate_duration(payload)

    # Detach validation output from the publisher's mutable input and block
    # accidental top-level writes. EventBus separately deep-copies lifecycle
    # envelopes per subscriber so nested handler mutations cannot leak.
    isolated = copy.deepcopy(dict(payload))
    return MappingProxyType(isolated)


def extract_sim_payload(
    event_type: str,
    event_data: Any,
) -> Mapping[str, Any]:
    """Unwrap an EventBus envelope and validate its lifecycle payload."""

    if event_type not in SIM_PAYLOAD_FIELDS:
        raise KeyError(event_type)
    if not isinstance(event_data, Mapping):
        raise InvalidSimEventEnvelopeError("simulation event envelope must be a mapping")
    if event_data.get("type") != event_type:
        raise InvalidSimEventEnvelopeError(
            f"envelope type {event_data.get('type')!r} does not match {event_type!r}"
        )
    if "data" not in event_data:
        raise InvalidSimEventEnvelopeError("simulation event envelope has no data field")
    try:
        return validate_sim_payload(event_type, event_data["data"])
    except InvalidSimPayloadError:
        raise
    except MissingSimPayloadFieldError:
        raise


__all__ = [
    "InvalidSimEventEnvelopeError",
    "InvalidSimPayloadError",
    "MissingSimPayloadFieldError",
    "SIM_LIFECYCLE_EVENT_TYPES",
    "SIM_PAYLOAD_FIELDS",
    "extract_sim_payload",
    "validate_sim_payload",
]
