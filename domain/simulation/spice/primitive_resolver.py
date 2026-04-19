from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from resources.resource_loader import get_spice_sub_dir


@dataclass(frozen=True)
class PrimitivePinSpec:
    name: str
    role: str


@dataclass(frozen=True)
class PrimitiveDescriptor:
    primitive_kind: str
    symbol_kind: str
    symbol_variant: str
    pin_specs: Tuple[PrimitivePinSpec, ...]
    port_order: Tuple[str, ...]
    render_hints: Tuple[Tuple[str, str], ...]
    source: str


_REQUIRED_OPAMP_ROLES = frozenset({"input_plus", "input_minus", "output"})
_BUNDLED_OPAMP_FALLBACKS: Dict[str, Tuple[str, ...]] = {
    "lt1001": ("input_plus", "input_minus", "power_positive", "power_negative", "output"),
}
_COMMENT_ROLE_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("non-inverting input", "input_plus"),
    ("noninverting input", "input_plus"),
    ("positive power supply", "power_positive"),
    ("positive supply", "power_positive"),
    ("negative power supply", "power_negative"),
    ("negative supply", "power_negative"),
    ("inverting input", "input_minus"),
    ("output", "output"),
    ("ground", "ground"),
)
_EXPLICIT_PORT_ROLE_MAP: Dict[str, str] = {
    "plus": "input_plus",
    "inp": "input_plus",
    "in+": "input_plus",
    "noninv": "input_plus",
    "non_inverting": "input_plus",
    "noninverting": "input_plus",
    "vp": "input_plus",
    "v+": "input_plus",
    "minus": "input_minus",
    "inn": "input_minus",
    "in-": "input_minus",
    "inv": "input_minus",
    "inverting": "input_minus",
    "vn": "input_minus",
    "v-": "input_minus",
    "out": "output",
    "output": "output",
    "vo": "output",
    "vcc": "power_positive",
    "vdd": "power_positive",
    "positive_supply": "power_positive",
    "vee": "power_negative",
    "vss": "power_negative",
    "negative_supply": "power_negative",
    "vneg": "power_negative",
    "gnd": "ground",
    "ground": "ground",
    "0": "ground",
}


class SpicePrimitiveResolver:
    def apply(self, document) -> None:
        inline_descriptors: Dict[str, PrimitiveDescriptor] = {}
        for subckt in document.subcircuits:
            descriptor = self.resolve_subcircuit(subckt.name, subckt.port_names)
            if descriptor is None:
                continue
            subckt.primitive_kind = descriptor.primitive_kind
            inline_descriptors[subckt.name.strip().lower()] = descriptor

        bundled_descriptors = _load_bundled_opamp_descriptors()
        for component in self._iter_components(document):
            if component.kind not in {"X", "U"}:
                continue
            subckt_name = str(component.model_name or "").strip()
            if not subckt_name:
                continue
            key = subckt_name.lower()
            descriptor = inline_descriptors.get(key)
            if descriptor is None:
                descriptor = bundled_descriptors.get(key)
            if descriptor is None:
                descriptor = self.resolve_subcircuit(subckt_name, [pin.node_id for pin in component.pins])
            if descriptor is None or len(descriptor.pin_specs) != len(component.pins):
                continue
            component.symbol_kind = descriptor.symbol_kind
            component.symbol_variant = descriptor.symbol_variant
            component.primitive_kind = descriptor.primitive_kind
            component.primitive_source = descriptor.source
            component.subckt_name = subckt_name
            component.resolved_model_name = subckt_name
            component.semantic_roles = [descriptor.primitive_kind]
            component.port_order = list(descriptor.port_order)
            component.render_hints = dict(descriptor.render_hints)
            component.pin_roles = {}
            for pin, spec in zip(component.pins, descriptor.pin_specs):
                pin.name = spec.name
                pin.role = spec.role
                component.pin_roles[spec.name] = spec.role

    def resolve_subcircuit(
        self,
        name: str,
        ports: Sequence[str],
        *,
        library_comment_roles: Optional[Sequence[str]] = None,
        metadata_hint: bool = False,
    ) -> Optional[PrimitiveDescriptor]:
        descriptor = self._descriptor_from_explicit_ports(ports)
        if descriptor is not None:
            return descriptor

        comment_roles = tuple(role for role in (library_comment_roles or []) if role)
        if comment_roles:
            descriptor = self._descriptor_from_roles(comment_roles, source="bundled_library_metadata")
            if descriptor is not None and len(descriptor.pin_specs) == len(ports):
                return descriptor

        fallback_roles = _BUNDLED_OPAMP_FALLBACKS.get(str(name or "").strip().lower())
        if fallback_roles is not None and len(fallback_roles) == len(ports):
            return self._descriptor_from_roles(fallback_roles, source="bundled_fallback_registry")

        if metadata_hint:
            canonical_roles = _canonical_roles_for_pin_count(len(ports))
            if canonical_roles is not None:
                return self._descriptor_from_roles(canonical_roles, source="bundled_symbol_metadata")
        return None

    def _descriptor_from_explicit_ports(self, ports: Sequence[str]) -> Optional[PrimitiveDescriptor]:
        roles = [self._role_for_explicit_port(port) for port in ports]
        if not _REQUIRED_OPAMP_ROLES.issubset({role for role in roles if role}):
            return None
        canonical_roles = _canonical_roles_for_pin_count(len(ports))
        if canonical_roles is None:
            return None
        unresolved_indices = [index for index, role in enumerate(roles) if not role]
        missing_roles = [role for role in canonical_roles if role not in roles]
        if len(unresolved_indices) != len(missing_roles):
            return None
        for index, role in zip(unresolved_indices, missing_roles):
            roles[index] = role
        return self._descriptor_from_roles(roles, source="explicit_subckt_ports")

    def _role_for_explicit_port(self, port: str) -> str:
        return _EXPLICIT_PORT_ROLE_MAP.get(str(port or "").strip().lower(), "")

    def _descriptor_from_roles(self, roles: Sequence[str], *, source: str) -> Optional[PrimitiveDescriptor]:
        normalized_roles = tuple(str(role or "").strip().lower() for role in roles if str(role or "").strip())
        if len(normalized_roles) < 3 or len(normalized_roles) > 5:
            return None
        if not _REQUIRED_OPAMP_ROLES.issubset(set(normalized_roles)):
            return None
        try:
            pin_specs = tuple(PrimitivePinSpec(name=_pin_name_for_role(role), role=role) for role in normalized_roles)
        except KeyError:
            return None
        return PrimitiveDescriptor(
            primitive_kind="opamp",
            symbol_kind="opamp",
            symbol_variant="opamp",
            pin_specs=pin_specs,
            port_order=tuple(pin.name for pin in pin_specs),
            render_hints=(("orientation", "horizontal"),),
            source=source,
        )

    def _iter_components(self, document) -> Iterable:
        yield from document.components
        for subckt in document.subcircuits:
            yield from subckt.components


@functools.lru_cache(maxsize=1)
def _load_bundled_opamp_descriptors() -> Dict[str, PrimitiveDescriptor]:
    result: Dict[str, PrimitiveDescriptor] = {}
    sub_dir = get_spice_sub_dir()
    if not sub_dir.exists():
        return result

    resolver = SpicePrimitiveResolver()
    for path in sub_dir.rglob("*.lib"):
        try:
            lines = path.read_text(encoding="latin1", errors="ignore").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines):
            match = re.match(r"\s*\.subckt\s+([^\s(]+)(.*)$", line, re.IGNORECASE)
            if match is None:
                continue
            name = match.group(1).strip()
            ports = [token for token in match.group(2).split() if token]
            comment_window = lines[max(0, index - 12):index]
            metadata_window = lines[max(0, index - 12):min(len(lines), index + 4)]
            metadata_hint = any("symbol=opamp" in item.lower() for item in metadata_window)
            comment_roles = _extract_comment_roles(comment_window)
            if not metadata_hint and not comment_roles and name.strip().lower() not in _BUNDLED_OPAMP_FALLBACKS:
                continue
            descriptor = resolver.resolve_subcircuit(
                name,
                ports,
                library_comment_roles=comment_roles,
                metadata_hint=metadata_hint,
            )
            if descriptor is not None:
                bundled_source = str(path).replace("\\", "/")
                result.setdefault(
                    name.strip().lower(),
                    PrimitiveDescriptor(
                        primitive_kind=descriptor.primitive_kind,
                        symbol_kind=descriptor.symbol_kind,
                        symbol_variant=descriptor.symbol_variant,
                        pin_specs=descriptor.pin_specs,
                        port_order=descriptor.port_order,
                        render_hints=descriptor.render_hints,
                        source=bundled_source,
                    ),
                )
    return result


def _extract_comment_roles(lines: Sequence[str]) -> Tuple[str, ...]:
    roles: List[str] = []
    for line in lines:
        for role in _extract_roles_from_comment_line(line):
            if not roles or roles[-1] != role:
                roles.append(role)
    if len(roles) < 3 or len(roles) > 5:
        return ()
    if not _REQUIRED_OPAMP_ROLES.issubset(set(roles)):
        return ()
    return tuple(roles)


def _extract_roles_from_comment_line(line: str) -> Tuple[str, ...]:
    normalized = str(line or "").strip().lower()
    if not normalized.startswith("*"):
        return ()
    matches: List[Tuple[int, str]] = []
    for keyword, role in _COMMENT_ROLE_KEYWORDS:
        position = normalized.find(keyword)
        if position < 0:
            continue
        if role == "input_minus" and ("non-inverting input" in normalized or "noninverting input" in normalized):
            continue
        matches.append((position, role))
    if not matches:
        return ()
    matches.sort(key=lambda item: item[0])
    ordered: List[str] = []
    for _, role in matches:
        if not ordered or ordered[-1] != role:
            ordered.append(role)
    return tuple(ordered)


def _canonical_roles_for_pin_count(pin_count: int) -> Optional[Tuple[str, ...]]:
    if pin_count == 3:
        return ("input_plus", "input_minus", "output")
    if pin_count == 4:
        return ("input_plus", "input_minus", "ground", "output")
    if pin_count == 5:
        return ("input_plus", "input_minus", "power_positive", "power_negative", "output")
    return None


def _pin_name_for_role(role: str) -> str:
    return {
        "input_plus": "plus",
        "input_minus": "minus",
        "output": "out",
        "power_positive": "vcc",
        "power_negative": "vee",
        "ground": "gnd",
    }[role]


__all__ = ["PrimitiveDescriptor", "PrimitivePinSpec", "SpicePrimitiveResolver"]
