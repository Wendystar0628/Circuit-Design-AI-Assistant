from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from domain.simulation.spice.models import (
    SpiceComponent,
    SpiceDocument,
    SpiceEditableField,
    SpiceParseError,
    SpicePin,
    SpiceSubcircuit,
)


def make_schematic_document_id(file_path: str) -> str:
    seed = str(file_path or "")
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _normalize_revision_dependency_snapshots(dependency_snapshots: Optional[Dict[str, str]] = None) -> List[Tuple[str, str]]:
    payload = dependency_snapshots if isinstance(dependency_snapshots, dict) else {}
    normalized: List[Tuple[str, str]] = []
    for path, snapshot in payload.items():
        normalized_path = str(path or "").strip()
        if not normalized_path:
            continue
        normalized.append((normalized_path, str(snapshot or "")))
    normalized.sort(key=lambda item: item[0])
    return normalized


def make_schematic_revision(file_path: str, source_text: str, dependency_snapshots: Optional[Dict[str, str]] = None) -> str:
    seed_parts = [str(file_path or ""), str(source_text or "")]
    for dependency_path, dependency_snapshot in _normalize_revision_dependency_snapshots(dependency_snapshots):
        seed_parts.append(dependency_path)
        seed_parts.append(dependency_snapshot)
    seed = "|".join(seed_parts)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


class SpiceSchematicBuilder:
    def build_document(
        self,
        spice_document: Optional[SpiceDocument],
        *,
        source_text: str = "",
        dependency_snapshots: Optional[Dict[str, str]] = None,
        title: str = "",
    ) -> Dict[str, Any]:
        if spice_document is None:
            return self.build_empty_document()

        file_path = str(spice_document.source_file or "")
        file_name = Path(file_path).name if file_path else ""
        all_components = self._collect_all_components(spice_document)
        components_payload = [self._build_component_payload(component) for component in all_components]
        document_title = title or file_name or "电路"
        readonly_reasons = self._collect_readonly_reasons(all_components)
        return {
            "document_id": make_schematic_document_id(file_path),
            "revision": make_schematic_revision(file_path, source_text, dependency_snapshots),
            "file_path": file_path,
            "file_name": file_name,
            "has_schematic": bool(components_payload or spice_document.subcircuits),
            "title": document_title,
            "components": components_payload,
            "nets": self._build_nets_payload(all_components),
            "subcircuits": [self._build_subcircuit_payload(item) for item in spice_document.subcircuits],
            "parse_errors": [self._build_parse_error_payload(item) for item in spice_document.parse_errors],
            "readonly_reasons": readonly_reasons,
        }

    def build_empty_document(self, file_path: str = "", dependency_snapshots: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        normalized_file_path = str(file_path or "")
        file_name = Path(normalized_file_path).name if normalized_file_path else ""
        return {
            "document_id": make_schematic_document_id(normalized_file_path),
            "revision": make_schematic_revision(normalized_file_path, "", dependency_snapshots),
            "file_path": normalized_file_path,
            "file_name": file_name,
            "has_schematic": False,
            "title": file_name or "电路",
            "components": [],
            "nets": [],
            "subcircuits": [],
            "parse_errors": [],
            "readonly_reasons": [],
        }

    def build_write_result(
        self,
        *,
        document_id: str = "",
        revision: str = "",
        request_id: str = "",
        success: bool = False,
        component_id: str = "",
        field_key: str = "",
        result_type: str = "",
        error_message: str = "",
    ) -> Dict[str, Any]:
        return {
            "document_id": str(document_id or ""),
            "revision": str(revision or ""),
            "request_id": str(request_id or ""),
            "success": bool(success),
            "component_id": str(component_id or ""),
            "field_key": str(field_key or ""),
            "result_type": str(result_type or ""),
            "error_message": str(error_message or ""),
        }

    def _collect_all_components(self, spice_document: SpiceDocument) -> List[SpiceComponent]:
        components = list(spice_document.components)
        for subcircuit in spice_document.subcircuits:
            components.extend(subcircuit.components)
        return components

    def _build_component_payload(self, component: SpiceComponent) -> Dict[str, Any]:
        value_field = self._find_value_field(component.editable_fields)
        return {
            "id": component.id,
            "instance_name": component.instance_name,
            "kind": component.kind,
            "symbol_kind": component.symbol_kind or "unknown",
            "display_name": component.instance_name,
            "display_value": value_field.display_text if value_field is not None else "",
            "pins": [self._build_pin_payload(item) for item in component.pins],
            "node_ids": list(component.node_ids),
            "editable_fields": [self._build_editable_field_payload(item) for item in component.editable_fields],
            "scope_path": list(component.scope_path),
            "source_file": component.source_file,
            "symbol_variant": component.symbol_variant,
            "pin_roles": dict(component.pin_roles),
            "port_side_hints": self._build_port_side_hints(component),
            "label_slots": self._build_label_slots(component),
            "polarity_marks": dict(component.polarity_marks),
            "render_hints": dict(component.render_hints),
        }

    def _build_pin_payload(self, pin: SpicePin) -> Dict[str, Any]:
        return {
            "name": pin.name,
            "node_id": pin.node_id,
            "role": pin.role,
        }

    def _build_editable_field_payload(self, field: SpiceEditableField) -> Dict[str, Any]:
        return {
            "field_key": field.field_key,
            "label": field.label,
            "raw_text": field.raw_text,
            "display_text": field.display_text,
            "editable": field.editable,
            "readonly_reason": field.readonly_reason,
            "value_kind": field.value_kind,
        }

    def _build_subcircuit_payload(self, subcircuit: SpiceSubcircuit) -> Dict[str, Any]:
        return {
            "name": subcircuit.name,
            "port_names": list(subcircuit.port_names),
            "scope_path": list(subcircuit.scope_path),
            "source_file": subcircuit.source_file,
            "component_ids": [component.id for component in subcircuit.components],
        }

    def _build_parse_error_payload(self, parse_error: SpiceParseError) -> Dict[str, Any]:
        return {
            "message": parse_error.message,
            "source_file": parse_error.source_file,
            "line_text": parse_error.line_text,
            "line_index": parse_error.source_span.line_index if parse_error.source_span is not None else -1,
            "column_start": parse_error.source_span.column_start if parse_error.source_span is not None else -1,
            "column_end": parse_error.source_span.column_end if parse_error.source_span is not None else -1,
        }

    def _build_nets_payload(self, components: Iterable[SpiceComponent]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for component in components:
            scope_key = "/".join(component.scope_path)
            for pin in component.pins:
                net_seed = "|".join([component.source_file, scope_key, pin.node_id])
                net_id = hashlib.sha1(net_seed.encode("utf-8")).hexdigest()[:16]
                payload = grouped.setdefault(
                    net_id,
                    {
                        "id": net_id,
                        "name": pin.node_id,
                        "scope_path": list(component.scope_path),
                        "source_file": component.source_file,
                        "connections": [],
                    },
                )
                payload["connections"].append(
                    {
                        "component_id": component.id,
                        "instance_name": component.instance_name,
                        "pin_name": pin.name,
                        "pin_role": pin.role,
                    }
                )
        return list(grouped.values())

    def _build_port_side_hints(self, component: SpiceComponent) -> Dict[str, str]:
        port_order = list(component.port_order)
        if not port_order:
            return {}
        if len(port_order) == 1:
            return {port_order[0]: "left"}
        if len(port_order) == 2:
            return {
                port_order[0]: "left",
                port_order[1]: "right",
            }
        hints: Dict[str, str] = {}
        for index, role in enumerate(port_order):
            if index == 0:
                hints[role] = "left"
            elif index == len(port_order) - 1:
                hints[role] = "right"
            else:
                hints[role] = "bottom"
        return hints

    def _build_label_slots(self, component: SpiceComponent) -> Dict[str, str]:
        slots = {
            "name": "top",
        }
        if self._find_value_field(component.editable_fields) is not None:
            slots["value"] = "bottom"
        return slots

    def _collect_readonly_reasons(self, components: Iterable[SpiceComponent]) -> List[str]:
        reasons: List[str] = []
        for component in components:
            for field in component.editable_fields:
                reason = str(field.readonly_reason or "").strip()
                if reason and reason not in reasons:
                    reasons.append(reason)
        return reasons

    def _find_value_field(self, fields: Iterable[SpiceEditableField]) -> Optional[SpiceEditableField]:
        for field in fields:
            if field.field_key == "value":
                return field
        return None


__all__ = ["SpiceSchematicBuilder", "make_schematic_document_id", "make_schematic_revision"]
