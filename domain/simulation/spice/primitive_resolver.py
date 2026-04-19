from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Tuple

from domain.simulation.spice.bundled_opamp_registry import load_bundled_opamp_descriptors
from domain.simulation.spice.primitive_descriptor import PrimitiveDescriptor, PrimitivePinSpec


_REQUIRED_OPAMP_ROLES = frozenset({"input_plus", "input_minus", "output"})
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

        bundled_descriptors = load_bundled_opamp_descriptors()
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
            if descriptor is None or len(descriptor.pin_specs) != len(component.pins):
                continue
            self._apply_descriptor(component, descriptor, subckt_name)

    def resolve_subcircuit(
        self,
        name: str,
        ports: Sequence[str],
    ) -> Optional[PrimitiveDescriptor]:
        return self._descriptor_from_explicit_ports(ports)

    def _apply_descriptor(self, component, descriptor: PrimitiveDescriptor, subckt_name: str) -> None:
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

    def _descriptor_from_explicit_ports(self, ports: Sequence[str]) -> Optional[PrimitiveDescriptor]:
        roles = [self._role_for_explicit_port(port) for port in ports]
        if not _REQUIRED_OPAMP_ROLES.issubset({role for role in roles if role}):
            return None
        pin_specs = []
        auxiliary_index = 1
        for role in roles:
            normalized_role = str(role or "").strip().lower()
            if normalized_role:
                pin_specs.append(PrimitivePinSpec(name=_pin_name_for_role(normalized_role), role=normalized_role))
                continue
            pin_specs.append(PrimitivePinSpec(name=f"aux_{auxiliary_index}", role="auxiliary"))
            auxiliary_index += 1
        return self._descriptor_from_pin_specs(tuple(pin_specs), source="explicit_subckt_ports")

    def _role_for_explicit_port(self, port: str) -> str:
        return _EXPLICIT_PORT_ROLE_MAP.get(str(port or "").strip().lower(), "")

    def _descriptor_from_roles(self, roles: Sequence[str], *, source: str) -> Optional[PrimitiveDescriptor]:
        normalized_roles = tuple(str(role or "").strip().lower() for role in roles if str(role or "").strip())
        if len(normalized_roles) < 3 or len(normalized_roles) > 7:
            return None
        if not _REQUIRED_OPAMP_ROLES.issubset(set(normalized_roles)):
            return None
        try:
            pin_specs = tuple(PrimitivePinSpec(name=_pin_name_for_role(role), role=role) for role in normalized_roles)
        except KeyError:
            return None
        return self._descriptor_from_pin_specs(pin_specs, source=source)

    def _descriptor_from_pin_specs(
        self,
        pin_specs: Tuple[PrimitivePinSpec, ...],
        *,
        source: str,
    ) -> PrimitiveDescriptor:
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
