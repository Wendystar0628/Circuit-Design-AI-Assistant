from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


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


__all__ = ["PrimitiveDescriptor", "PrimitivePinSpec"]
