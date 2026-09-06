"""Model annotations bound to the definitions in a frozen SPICE source graph.

The manifest inventories declarations in active include/library sections; it
does not pretend every declaration is instantiated or manufacturer validated.
Catalog annotations are keyed by exact source bytes, never a part-name guess.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from typing import Any, Mapping

from domain.simulation.spice.source_closure import SpiceSourceClosureGraph


_BINDING_FIELDS = frozenset({
    "name", "kind", "source_id", "source", "version", "voltage_range",
    "frequency_range", "temperature_range", "simplified", "assumptions",
})
_ANNOTATION_FIELDS = (
    "source", "version", "voltage_range", "frequency_range",
    "temperature_range", "simplified", "assumptions",
)
_DEFINITION = re.compile(r"^\s*\.(model|subckt)\s+([^\s(]+)", re.I)
_MANIFEST_FIELDS = _BINDING_FIELDS | frozenset({
    "identity", "source_path", "library_section", "line_number", "scope",
    "definition_digest", "file_digest", "metadata_origin", "binding_status",
    "usage_state",
})
# These descriptions come from the checked-in files' own headers. The digest
# prevents a same-named replacement from inheriting unverified provenance.
_BUNDLED_BY_SHA256 = {
    "b962f54f7bf406ddad42e00df533e886a04847d18173b38eec521070b62f662c": {
        "source": "National Semiconductor, Inc. (copyright in bundled LM741.lib)",
        "simplified": True,
        "assumptions": [
            "LM741 operational-amplifier macro-model, as identified by its source header.",
            "No validated voltage, frequency or temperature range is supplied in this model file.",
        ],
    },
    "5be3ef2da1cddb5996288c50dbc0dc2a3fbefc3249e0c6abe9938536ddb990b5": {
        "source": "Bundled testcircuit_discrete.lib, adapted from resources/models/cmp/standard.*",
        "simplified": True,
        "assumptions": [
            "Curated ngspice adaptation for the checked-in TestCircuit corpus.",
            "Catalog-only metadata and unsupported LTspice JFET extensions were omitted, as documented in the source header.",
            "Device ratings in a catalog are not validated model applicability ranges.",
        ],
    },
}
# Git checkouts may carry this same upstream file with LF or CRLF endings.
_BUNDLED_BY_SHA256["f58370983c8bd22bf6a59ddd05a1dd492f1a0ea60f673ffd460a356da5e693dc"] = (
    _BUNDLED_BY_SHA256["b962f54f7bf406ddad42e00df533e886a04847d18173b38eec521070b62f662c"]
)


def _text(value: Any, label: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"{label} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} must not be empty")
    return value or None


def _range(value: Any, field: str) -> dict[str, float | None] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) - {"min", "max"}:
        raise ValueError(f"{field} must contain only min/max")
    result: dict[str, float | None] = {}
    for bound in ("min", "max"):
        numeric = value.get(bound)
        if numeric is not None:
            if isinstance(numeric, bool) or not isinstance(numeric, (int, float)):
                raise ValueError(f"{field}.{bound} must be a finite number")
            numeric = float(numeric)
            if not math.isfinite(numeric):
                raise ValueError(f"{field}.{bound} must be a finite number")
            if field == "frequency_range" and numeric < 0:
                raise ValueError("frequency_range cannot be negative")
            if field == "temperature_range" and numeric < -273.15:
                raise ValueError("temperature_range cannot be below absolute zero")
        result[bound] = numeric
    if result["min"] is None and result["max"] is None:
        return None
    if result["min"] is not None and result["max"] is not None and result["min"] > result["max"]:
        raise ValueError(f"{field} min must not exceed max")
    return result


def validate_model_bindings(payload: Any) -> list[dict[str, Any]]:
    """Normalize user declarations; unknown metadata remains explicitly unknown.

    Applicability uses fixed SI units: voltage V, frequency Hz, temperature degC.
    These ranges are user annotations, not an automatically verified operating test.
    """
    if not isinstance(payload, list):
        raise ValueError("model_bindings must be a list")
    output: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for entry in payload:
        if not isinstance(entry, Mapping) or set(entry) - _BINDING_FIELDS:
            raise ValueError("model binding has invalid fields")
        name = _text(entry.get("name"), "model name", required=True)
        if re.search(r"[\s()]", name):
            raise ValueError("model name must be a SPICE identifier")
        kind = entry.get("kind", "model")
        if not isinstance(kind, str) or kind not in {"model", "subcircuit"}:
            raise ValueError("model kind must be model or subcircuit")
        source_id = _text(entry.get("source_id"), "model source_id")
        identity = (name.casefold(), kind, source_id or "")
        if identity in identities:
            raise ValueError(f"Duplicate model binding: {name}")
        identities.add(identity)
        simplified = entry.get("simplified")
        if simplified is not None and not isinstance(simplified, bool):
            raise ValueError("model simplified must be true, false or null")
        assumptions = entry.get("assumptions", [])
        if not isinstance(assumptions, list):
            raise ValueError("model assumptions must be a list of strings")
        output.append({
            "name": name, "kind": kind, "source_id": source_id,
            "source": _text(entry.get("source"), "model source"),
            "version": _text(entry.get("version"), "model version"),
            "voltage_range": _range(entry.get("voltage_range"), "voltage_range"),
            "frequency_range": _range(entry.get("frequency_range"), "frequency_range"),
            "temperature_range": _range(entry.get("temperature_range"), "temperature_range"),
            "simplified": simplified,
            "assumptions": [_text(item, "model assumption", required=True) for item in assumptions],
        })
    return output


def _definitions(graph: SpiceSourceClosureGraph) -> list[dict[str, Any]]:
    blobs = {blob.key: blob for blob in graph.blobs}
    output: list[dict[str, Any]] = []
    for view in graph.active_views:
        blob = blobs[view.key]
        file_digest = hashlib.sha256(blob.raw_bytes).hexdigest()
        # A declaration's exact text and enclosing scope are retained without
        # evaluating SPICE expressions. Full bytes live in the source snapshot.
        lines = []
        for line in view.lines:
            if view.is_main_deck and line.line_number == 1:
                continue
            if view.is_main_deck and re.match(r"^\s*\.end(?:\s|$)", line.text, re.I):
                break
            lines.append(line)
        scopes: list[str] = []
        for index, line in enumerate(lines):
            if re.match(r"^\s*\.ends(?:\s|$)", line.text, re.I):
                if scopes:
                    scopes.pop()
                continue
            match = _DEFINITION.match(line.text)
            if match is None:
                continue
            kind = "model" if match[1].casefold() == "model" else "subcircuit"
            name = match[2]
            definition_lines = [line.text]
            depth = 1
            for next_index in range(index + 1, len(lines)):
                following = lines[next_index]
                if kind == "model":
                    if following.text.lstrip().startswith("+"):
                        definition_lines.append(following.text)
                    elif not following.text.strip() or following.text.lstrip().startswith("*"):
                        continue
                    else:
                        break
                else:
                    definition_lines.append(following.text)
                    if re.match(r"^\s*\.subckt\s", following.text, re.I):
                        depth += 1
                    if re.match(r"^\s*\.ends(?:\s|$)", following.text, re.I):
                        depth -= 1
                        if depth == 0:
                            break
            scope = "/".join(scopes)
            identity = f"{view.source_id}::{view.library_section}::{scope}::{kind}:{name.casefold()}:{line.line_number}"
            annotation = {field: None for field in _ANNOTATION_FIELDS}
            annotation["assumptions"] = []
            bundled = _BUNDLED_BY_SHA256.get(file_digest)
            if bundled is not None:
                annotation.update(copy.deepcopy(bundled))
            output.append({
                "identity": identity, "name": name, "kind": kind,
                "source_id": view.source_id, "source_path": view.source_id,
                "library_section": view.library_section, "line_number": line.line_number,
                "scope": scope, "file_digest": file_digest,
                "definition_digest": hashlib.sha256("\n".join(definition_lines).encode("utf-8")).hexdigest(),
                **annotation,
                "metadata_origin": "bundled_source" if bundled else "unspecified",
                "binding_status": "none", "usage_state": "declared_in_active_source",
            })
            if kind == "subcircuit":
                scopes.append(name)
    return output


def capture_model_manifest(
    graph: SpiceSourceClosureGraph, bindings: Any = None,
) -> list[dict[str, Any]]:
    """Bind annotations only to unambiguous declarations in frozen bytes."""
    declarations = validate_model_bindings([] if bindings is None else bindings)
    manifest = _definitions(graph)
    candidates = []
    for binding in declarations:
        candidates.append([
            item for item in manifest
            if item["name"].casefold() == binding["name"].casefold()
            and item["kind"] == binding["kind"]
            and (binding["source_id"] is None or item["source_id"] == binding["source_id"])
        ])
    for binding, matches in zip(declarations, candidates):
        # Also prevent a general and a source-specific binding from silently
        # overwriting one another on the same actual declaration.
        overlaps = len(matches) == 1 and sum(matches[0] in group for group in candidates) > 1
        if len(matches) == 1 and not overlaps:
            target = matches[0]
            for field in _ANNOTATION_FIELDS:
                if binding[field] is not None and (field != "assumptions" or binding[field]):
                    target[field] = copy.deepcopy(binding[field])
            target["metadata_origin"] = "user_declared"
            target["binding_status"] = "matched"
        else:
            manifest.append({
                **copy.deepcopy(binding), "identity": None,
                "source_path": binding["source_id"], "library_section": None,
                "line_number": None, "scope": None, "file_digest": None,
                "definition_digest": None, "metadata_origin": "user_declared",
                "binding_status": "ambiguous" if matches else "unmatched",
                "usage_state": "not_bound",
            })
    return manifest


def validate_model_manifest(
    payload: Any, *, graph: SpiceSourceClosureGraph | None = None,
) -> list[dict[str, Any]]:
    """Validate archived inventory without consulting a live model catalog.

    When graph is supplied, every declared identity and digest must correspond
    to those historical bytes; annotations are preserved exactly as captured.
    """
    if not isinstance(payload, list):
        raise ValueError("models must be a list")
    output = copy.deepcopy(payload)
    seen = set()
    for item in output:
        if not isinstance(item, dict) or set(item) != _MANIFEST_FIELDS:
            raise ValueError("model manifest has invalid fields")
        validate_model_bindings([{field: item[field] for field in _BINDING_FIELDS}])
        if item["metadata_origin"] not in {"user_declared", "bundled_source", "unspecified"}:
            raise ValueError("model manifest has invalid metadata_origin")
        if item["binding_status"] not in {"none", "matched", "unmatched", "ambiguous"}:
            raise ValueError("model manifest has invalid binding_status")
        if item["identity"] is None:
            if item["binding_status"] not in {"unmatched", "ambiguous"} or item["usage_state"] != "not_bound":
                raise ValueError("unbound model metadata cannot claim a model definition")
            if any(item[field] is not None for field in ("definition_digest", "file_digest", "line_number", "scope", "library_section")):
                raise ValueError("unbound model metadata cannot claim a source digest")
        else:
            if not isinstance(item["identity"], str) or item["identity"] in seen:
                raise ValueError("Duplicate or invalid model definition identity")
            seen.add(item["identity"])
            if item["usage_state"] != "declared_in_active_source" or item["binding_status"] not in {"none", "matched"}:
                raise ValueError("model definition has invalid binding status")
            for field in ("source_id", "source_path", "library_section", "scope"):
                if not isinstance(item[field], str):
                    raise ValueError(f"model manifest {field} must be a string")
            if type(item["line_number"]) is not int or item["line_number"] < 1:
                raise ValueError("model manifest line_number must be positive")
            for field in ("definition_digest", "file_digest"):
                if not isinstance(item[field], str) or re.fullmatch(r"[0-9a-f]{64}", item[field]) is None:
                    raise ValueError(f"model manifest {field} must be SHA256")
    if graph is not None:
        expected = {item["identity"]: item for item in _definitions(graph)}
        actual = {item["identity"]: item for item in output if item["identity"] is not None}
        if set(actual) != set(expected):
            raise ValueError("model manifest identities do not match frozen source declarations")
        fields = ("name", "kind", "source_id", "source_path", "library_section", "scope", "line_number", "definition_digest", "file_digest")
        if any(actual[key][field] != expected[key][field] for key in expected for field in fields):
            raise ValueError("model manifest definition digest or identity does not match frozen source")
    return output


__all__ = ["validate_model_bindings", "capture_model_manifest", "validate_model_manifest"]
