from __future__ import annotations

import functools
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from domain.simulation.spice.bundled_subcircuit_catalog import load_bundled_subcircuit_catalog
from domain.simulation.spice.primitive_descriptor import PrimitiveDescriptor, PrimitivePinSpec


_REQUIRED_OPAMP_ROLES = frozenset({"input_plus", "input_minus", "output"})
_COMMENT_ROLE_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("non-inverting input", "input_plus"),
    ("noninverting input", "input_plus"),
    ("positive input", "input_plus"),
    ("inverting input", "input_minus"),
    ("negative input", "input_minus"),
    ("positive power supply", "power_positive"),
    ("positive supply", "power_positive"),
    ("negative power supply", "power_negative"),
    ("negative supply", "power_negative"),
    ("output", "output"),
    ("ground", "ground"),
)


def _spec(name: str, role: str) -> PrimitivePinSpec:
    return PrimitivePinSpec(name=name, role=role)


_CLASSIC_5_PIN = (
    _spec("plus", "input_plus"),
    _spec("minus", "input_minus"),
    _spec("vcc", "power_positive"),
    _spec("vee", "power_negative"),
    _spec("out", "output"),
)
_OUTPUT_THIRD_5_PIN = (
    _spec("plus", "input_plus"),
    _spec("minus", "input_minus"),
    _spec("out", "output"),
    _spec("vcc", "power_positive"),
    _spec("vee", "power_negative"),
)
_OUTPUT_FIRST_5_PIN = (
    _spec("out", "output"),
    _spec("vee", "power_negative"),
    _spec("plus", "input_plus"),
    _spec("minus", "input_minus"),
    _spec("vcc", "power_positive"),
)
_CLASSIC_6_PIN_AUX = _CLASSIC_5_PIN + (_spec("aux_1", "auxiliary"),)
_OUTPUT_THIRD_6_PIN_AUX = _OUTPUT_THIRD_5_PIN + (_spec("aux_1", "auxiliary"),)
_OUTPUT_FIRST_6_PIN_AUX = (
    _spec("out", "output"),
    _spec("vee", "power_negative"),
    _spec("plus", "input_plus"),
    _spec("minus", "input_minus"),
    _spec("aux_1", "auxiliary"),
    _spec("vcc", "power_positive"),
)
_CLASSIC_7_PIN_AUX = _CLASSIC_5_PIN + (
    _spec("aux_1", "auxiliary"),
    _spec("aux_2", "auxiliary"),
)


_CLASSIC_5_PIN_MODELS = (
    "lt1001",
    "lt118a",
    "lt1813",
    "lt1880",
    "lt1881",
    "lt1884",
    "lt1886",
    "lm307",
    "lm318",
    "lm318s8",
    "lm107",
    "lm118",
    "op237c",
    "op237g",
    "op27c",
    "op27g",
    "op227c",
    "op227g",
    "op27a",
    "op27e",
    "op227a",
    "op227e",
    "op07c",
    "op07cs8",
    "op07e",
    "op07a",
    "op05c",
    "op05e",
    "op05a",
    "op16b",
    "op16f",
    "op16a",
    "op16e",
    "op16c",
    "op16g",
    "op15b",
    "op15f",
    "op15a",
    "op15e",
    "op15c",
    "op15g",
    "op215a",
    "op215e",
    "op215c",
    "op215g",
    "op97",
    "op07",
    "op05",
    "lt6002",
    "lt6003",
    "lt6275",
    "lt6220",
    "ltc6078",
    "ltc6082",
    "ltc6085",
    "ltc6088",
    "ltc6241",
    "ltc6244",
    "ltc6244hv",
)
_OUTPUT_THIRD_5_PIN_MODELS = (
    "lt1457",
    "lt1672",
    "lt1678",
    "lt1803",
    "lt1815",
    "lt1818",
    "lt6011",
    "lt6013",
    "lt6201",
    "lt6202",
    "lt6205",
    "lt6231",
    "lt6234",
    "ltc2052",
    "ltc2054",
)
_OUTPUT_FIRST_5_PIN_MODELS = (
    "ltc6247",
    "ltc6253",
)
_CLASSIC_6_PIN_AUX_MODELS = (
    "lt6000",
    "ltc2066",
    "ltc6081",
    "ltc6084",
    "ltc6087",
    "ltc6255",
)
_OUTPUT_THIRD_6_PIN_AUX_MODELS = (
    "lt1784",
    "lt6010",
    "lt6200",
    "lt6200-5",
    "lt6200-10",
    "lt6230",
    "lt6230-10",
    "lt6233",
    "lt6233-10",
    "lt6236",
    "ltc2063",
    "ltc6268",
    "ltc6268-10",
)
_OUTPUT_FIRST_6_PIN_AUX_MODELS = (
    "ltc6246",
    "ltc6252",
    "ltc6253-7",
)
_CLASSIC_7_PIN_AUX_MODELS = (
    "lm101a",
    "lm108",
    "lm108a",
    "lm301a",
    "lm308",
    "lm308a",
)


def build_curated_bundled_opamp_pin_specs() -> Dict[str, Tuple[PrimitivePinSpec, ...]]:
    registry: Dict[str, Tuple[PrimitivePinSpec, ...]] = {}
    _register_layout_models(registry, _CLASSIC_5_PIN_MODELS, _CLASSIC_5_PIN)
    _register_layout_models(registry, _OUTPUT_THIRD_5_PIN_MODELS, _OUTPUT_THIRD_5_PIN)
    _register_layout_models(registry, _OUTPUT_FIRST_5_PIN_MODELS, _OUTPUT_FIRST_5_PIN)
    _register_layout_models(registry, _CLASSIC_6_PIN_AUX_MODELS, _CLASSIC_6_PIN_AUX)
    _register_layout_models(registry, _OUTPUT_THIRD_6_PIN_AUX_MODELS, _OUTPUT_THIRD_6_PIN_AUX)
    _register_layout_models(registry, _OUTPUT_FIRST_6_PIN_AUX_MODELS, _OUTPUT_FIRST_6_PIN_AUX)
    _register_layout_models(registry, _CLASSIC_7_PIN_AUX_MODELS, _CLASSIC_7_PIN_AUX)
    return registry


@functools.lru_cache(maxsize=1)
def load_bundled_opamp_descriptors() -> Dict[str, PrimitiveDescriptor]:
    curated_pin_specs = build_curated_bundled_opamp_pin_specs()
    descriptors: Dict[str, PrimitiveDescriptor] = {}
    for header in load_bundled_subcircuit_catalog():
        pin_specs = curated_pin_specs.get(header.name)
        if pin_specs is not None:
            if len(pin_specs) == len(header.ports):
                descriptors[header.name] = _descriptor_from_pin_specs(pin_specs, header.source_file)
            continue
        comment_roles = _extract_comment_roles(header.leading_comment_lines)
        if len(comment_roles) != len(header.ports):
            continue
        descriptor = _descriptor_from_roles(comment_roles, header.source_file)
        if descriptor is not None:
            descriptors[header.name] = descriptor
    return descriptors


def iter_curated_bundled_opamp_model_names() -> Iterable[str]:
    return build_curated_bundled_opamp_pin_specs().keys()


def _register_layout_models(
    registry: Dict[str, Tuple[PrimitivePinSpec, ...]],
    model_names: Sequence[str],
    pin_specs: Tuple[PrimitivePinSpec, ...],
) -> None:
    for model_name in model_names:
        normalized_name = str(model_name or "").strip().lower()
        if not normalized_name:
            continue
        if normalized_name in registry:
            raise ValueError(f"重复的 bundled opamp layout 定义: {normalized_name}")
        registry[normalized_name] = pin_specs


def _extract_comment_roles(lines: Sequence[str]) -> Tuple[str, ...]:
    roles = []
    for line in lines:
        for role in _extract_roles_from_comment_line(line):
            if not roles or roles[-1] != role:
                roles.append(role)
    if len(roles) < 3 or len(roles) > 7:
        return ()
    if not _REQUIRED_OPAMP_ROLES.issubset(set(roles)):
        return ()
    return tuple(roles)


def _extract_roles_from_comment_line(line: str) -> Tuple[str, ...]:
    normalized = str(line or "").strip().lower()
    if not normalized.startswith("*"):
        return ()
    matches = []
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
    ordered_roles = []
    for _, role in matches:
        if not ordered_roles or ordered_roles[-1] != role:
            ordered_roles.append(role)
    return tuple(ordered_roles)


def _descriptor_from_roles(roles: Sequence[str], source_file: Path) -> PrimitiveDescriptor | None:
    pin_specs = []
    for index, role in enumerate(roles):
        normalized_role = str(role or "").strip().lower()
        if not normalized_role:
            return None
        pin_name = _default_pin_name_for_role(normalized_role, index)
        pin_specs.append(PrimitivePinSpec(name=pin_name, role=normalized_role))
    return _descriptor_from_pin_specs(tuple(pin_specs), source_file)


def _descriptor_from_pin_specs(pin_specs: Tuple[PrimitivePinSpec, ...], source_file: Path) -> PrimitiveDescriptor:
    normalized_source = str(source_file).replace("\\", "/")
    return PrimitiveDescriptor(
        primitive_kind="opamp",
        symbol_kind="opamp",
        symbol_variant="opamp",
        pin_specs=pin_specs,
        port_order=tuple(pin.name for pin in pin_specs),
        render_hints=(("orientation", "horizontal"),),
        source=normalized_source,
    )


def _default_pin_name_for_role(role: str, index: int) -> str:
    base_names: Mapping[str, str] = {
        "input_plus": "plus",
        "input_minus": "minus",
        "output": "out",
        "power_positive": "vcc",
        "power_negative": "vee",
        "ground": "gnd",
        "auxiliary": "aux",
    }
    base_name = base_names.get(role, role)
    if role == "auxiliary":
        return f"aux_{index + 1}"
    return base_name


__all__ = [
    "build_curated_bundled_opamp_pin_specs",
    "iter_curated_bundled_opamp_model_names",
    "load_bundled_opamp_descriptors",
]
