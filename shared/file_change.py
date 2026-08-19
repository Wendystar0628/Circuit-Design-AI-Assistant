"""Strict contract for project-scoped on-disk file change events.

``EVENT_FILE_CHANGED`` has exactly one payload schema.  Producers construct a
``FileChange`` and publish ``to_payload()``; EventBus subscribers receive the
canonical payload inside the normal EventBus envelope.  Invalid or unrelated
events fail closed instead of being guessed into this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from shared.event_types import EVENT_FILE_CHANGED


_CANONICAL_OPERATIONS = frozenset({"create", "update", "delete", "move"})
_PAYLOAD_FIELDS = frozenset(
    {
        "operation",
        "path",
        "dest_path",
        "is_directory",
        "origin",
        "project_root",
        "generation",
        "revision",
    }
)


@dataclass(frozen=True)
class FileChange:
    """One canonical filesystem change bound to a project generation."""

    operation: str
    path: str
    dest_path: str
    is_directory: bool
    origin: str
    project_root: str
    generation: int
    revision: str

    def __post_init__(self) -> None:
        if type(self.operation) is not str or self.operation not in _CANONICAL_OPERATIONS:
            raise ValueError(
                f"Unsupported file change operation: {self.operation!r}"
            )
        for field_name in ("path", "origin", "project_root", "revision"):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise ValueError(f"File change {field_name} must be a non-empty string")
        if type(self.dest_path) is not str:
            raise ValueError("File change dest_path must be a string")
        if self.operation == "move":
            if not self.dest_path:
                raise ValueError("Move file change requires dest_path")
        elif self.dest_path:
            raise ValueError("Only a move file change may provide dest_path")
        if type(self.is_directory) is not bool:
            raise ValueError("File change is_directory must be a bool")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("File change generation must be a positive integer")

    def to_payload(self) -> dict[str, Any]:
        """Return the complete canonical EventBus payload."""

        return {
            "operation": self.operation,
            "path": self.path,
            "dest_path": self.dest_path,
            "is_directory": self.is_directory,
            "origin": self.origin,
            "project_root": self.project_root,
            "generation": self.generation,
            "revision": self.revision,
        }


def normalize_file_change(event_data: Any) -> FileChange:
    """Return a canonical change from ``FileChange`` or an EventBus envelope.

    Raw dictionaries are deliberately rejected.  Subscribers see an EventBus
    envelope, while isolated callers/tests can construct ``FileChange``
    explicitly.  Requiring the exact payload keys prevents removed aliases or
    partially scoped events from silently entering project state.
    """

    if isinstance(event_data, FileChange):
        return event_data
    if not isinstance(event_data, Mapping):
        raise ValueError("File change must be a FileChange or EventBus envelope")
    if event_data.get("type") != EVENT_FILE_CHANGED or "data" not in event_data:
        raise ValueError("File change mapping must be an EVENT_FILE_CHANGED envelope")

    raw = event_data["data"]
    if not isinstance(raw, Mapping):
        raise ValueError("File change envelope data must be a canonical mapping")
    payload_keys = frozenset(raw.keys())
    if payload_keys != _PAYLOAD_FIELDS:
        missing = sorted(_PAYLOAD_FIELDS - payload_keys)
        unexpected = sorted(str(key) for key in payload_keys - _PAYLOAD_FIELDS)
        raise ValueError(
            "File change payload fields do not match the canonical schema "
            f"(missing={missing}, unexpected={unexpected})"
        )

    return FileChange(
        operation=raw["operation"],
        path=raw["path"],
        dest_path=raw["dest_path"],
        is_directory=raw["is_directory"],
        origin=raw["origin"],
        project_root=raw["project_root"],
        generation=raw["generation"],
        revision=raw["revision"],
    )


def extract_file_change(event_data: Any) -> Optional[FileChange]:
    """Return a canonical change, or ``None`` for invalid/unrelated input."""

    try:
        return normalize_file_change(event_data)
    except (TypeError, ValueError):
        return None


__all__ = ["FileChange", "normalize_file_change", "extract_file_change"]
