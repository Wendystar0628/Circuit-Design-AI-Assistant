from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from resources.resource_loader import get_spice_sym_dir


@dataclass(frozen=True)
class LtspicePinDefinition:
    name: str
    spice_order: int
    x: int
    y: int


@dataclass(frozen=True)
class LtspiceSymbolDefinition:
    key: str
    basename: str
    source_file: str
    prefix: str
    defaults: Dict[str, str]
    pins: Tuple[LtspicePinDefinition, ...]
    family: str


class LtspiceSymbolCatalog:
    def __init__(self, sym_dir: Optional[Path] = None) -> None:
        self._sym_dir = Path(sym_dir) if sym_dir is not None else get_spice_sym_dir()
        self._symbols_by_key: Optional[Dict[str, LtspiceSymbolDefinition]] = None
        self._symbols_by_basename: Optional[Dict[str, LtspiceSymbolDefinition]] = None

    def lookup(self, symbol_name: str) -> Optional[LtspiceSymbolDefinition]:
        normalized = normalize_ltspice_symbol_key(symbol_name)
        if not normalized:
            return None
        self._ensure_loaded()
        assert self._symbols_by_key is not None
        assert self._symbols_by_basename is not None
        definition = self._symbols_by_key.get(normalized)
        if definition is not None:
            return definition
        return self._symbols_by_basename.get(normalized.rsplit("/", 1)[-1])

    def all_symbols(self) -> Sequence[LtspiceSymbolDefinition]:
        self._ensure_loaded()
        assert self._symbols_by_key is not None
        return tuple(self._symbols_by_key.values())

    def _ensure_loaded(self) -> None:
        if self._symbols_by_key is not None and self._symbols_by_basename is not None:
            return
        symbols_by_key: Dict[str, LtspiceSymbolDefinition] = {}
        symbols_by_basename: Dict[str, LtspiceSymbolDefinition] = {}
        if self._sym_dir.exists():
            for file_path in sorted(self._sym_dir.rglob("*")):
                if not file_path.is_file() or file_path.suffix.lower() != ".asy":
                    continue
                definition = _parse_symbol_definition(file_path, self._sym_dir)
                if definition is None:
                    continue
                symbols_by_key.setdefault(definition.key, definition)
                symbols_by_basename.setdefault(definition.basename, definition)
        self._symbols_by_key = symbols_by_key
        self._symbols_by_basename = symbols_by_basename


def normalize_ltspice_symbol_key(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/ ")
    lower = normalized.lower()
    if lower.endswith(".asy"):
        normalized = normalized[:-4]
    return normalized.replace("\\", "/").strip("/ ").lower()


def classify_ltspice_symbol_family(symbol_key: str, prefix: str) -> str:
    normalized_key = normalize_ltspice_symbol_key(symbol_key)
    basename = normalized_key.rsplit("/", 1)[-1]
    lead = str(prefix or "").strip().upper()[:1]
    if normalized_key.startswith("opamps/") or "opamp" in basename:
        return "opamp"
    if normalized_key.startswith("comparators/") or "compar" in basename:
        return "comparator"
    if basename in {"res", "res2"} or lead == "R":
        return "resistor"
    if basename in {"cap", "cap2", "polcap", "polcap2"} or lead == "C":
        return "capacitor"
    if basename in {"ind", "ind2", "indcp", "indcp2"} or lead == "L":
        return "inductor"
    if basename in {"voltage", "voltage2"} or lead == "V":
        return "voltage_source"
    if basename in {"current", "current2"} or lead == "I":
        return "current_source"
    if basename in {"diode", "zener", "schottky", "led"} or lead == "D":
        return "diode"
    if basename in {"npn", "pnp", "npn2", "pnp2", "ncomp", "pcomp"} or lead == "Q":
        return "bjt"
    if basename in {"nmos", "pmos", "nmos4", "pmos4", "mesfet"} or lead == "M":
        return "mos"
    if basename in {"njf", "pjf", "njf2", "pjf2"} or lead == "J":
        return "jfet"
    if basename in {"sw", "asw"} or lead == "S":
        return "switch"
    if basename == "csw" or lead == "W":
        return "cswitch"
    if basename in {"bv", "bi", "bi2"} or lead == "B":
        return "behavioral"
    if lead in {"E", "F", "G", "H"}:
        return "controlled_source"
    if basename == "ne555":
        return "timer"
    if lead == "X":
        return "subckt"
    return "generic"


@dataclass
class _PendingPin:
    x: int
    y: int
    name: str = ""
    spice_order: Optional[int] = None


def _parse_symbol_definition(file_path: Path, sym_root: Path) -> Optional[LtspiceSymbolDefinition]:
    content = _read_text(file_path)
    if not content:
        return None
    defaults: Dict[str, str] = {}
    pins: List[LtspicePinDefinition] = []
    pending_pin: Optional[_PendingPin] = None
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        upper = stripped.split(None, 1)[0].upper()
        if upper == "PIN":
            pending_pin = _flush_pending_pin(pending_pin, pins)
            parts = stripped.split()
            if len(parts) < 3:
                continue
            try:
                pending_pin = _PendingPin(x=int(parts[1]), y=int(parts[2]))
            except (TypeError, ValueError):
                pending_pin = None
            continue
        if upper == "PINATTR" and pending_pin is not None:
            rest = stripped.split(None, 2)
            if len(rest) < 2:
                continue
            attr_key = rest[1].strip().lower()
            attr_value = rest[2].strip() if len(rest) > 2 else ""
            if attr_key == "pinname":
                pending_pin.name = attr_value
            elif attr_key == "spiceorder":
                try:
                    pending_pin.spice_order = int(attr_value or "0")
                except (TypeError, ValueError):
                    pending_pin.spice_order = None
            continue
        if upper == "SYMATTR":
            rest = stripped.split(None, 2)
            if len(rest) < 2:
                continue
            attr_key = rest[1].strip().lower()
            attr_value = rest[2].strip() if len(rest) > 2 else ""
            defaults[attr_key] = attr_value
    _flush_pending_pin(pending_pin, pins)
    relative_path = file_path.relative_to(sym_root)
    symbol_key = normalize_ltspice_symbol_key(str(relative_path))
    basename = symbol_key.rsplit("/", 1)[-1]
    prefix = defaults.get("prefix", "")
    return LtspiceSymbolDefinition(
        key=symbol_key,
        basename=basename,
        source_file=str(file_path),
        prefix=prefix,
        defaults=dict(defaults),
        pins=tuple(sorted(pins, key=lambda item: (item.spice_order, item.name.lower(), item.x, item.y))),
        family=classify_ltspice_symbol_family(symbol_key, prefix),
    )


def _flush_pending_pin(
    pending_pin: Optional[_PendingPin],
    pins: List[LtspicePinDefinition],
) -> Optional[_PendingPin]:
    if pending_pin is None:
        return None
    if pending_pin.spice_order is not None:
        pins.append(
            LtspicePinDefinition(
                name=str(pending_pin.name or f"PIN{pending_pin.spice_order}"),
                spice_order=int(pending_pin.spice_order),
                x=int(pending_pin.x),
                y=int(pending_pin.y),
            )
        )
    return None


def _read_text(file_path: Path) -> str:
    for encoding in ("utf-8", "latin1"):
        try:
            return file_path.read_text(encoding=encoding, errors="ignore")
        except Exception:
            continue
    return ""


__all__ = [
    "LtspicePinDefinition",
    "LtspiceSymbolCatalog",
    "LtspiceSymbolDefinition",
    "classify_ltspice_symbol_family",
    "normalize_ltspice_symbol_key",
]
