from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from domain.simulation.spice.bundled_opamp_registry import load_bundled_opamp_descriptors
from domain.simulation.spice.bundled_subcircuit_catalog import load_bundled_subcircuit_catalog
from domain.simulation.spice.parser import SpiceParser


_UNSUPPORTED_LIBRARY_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("OTA", re.compile(r"\bOTA\b", re.IGNORECASE)),
    ("noiseless", re.compile(r"\bnoiseless\b", re.IGNORECASE)),
    ("uplim", re.compile(r"\buplim\s*\(", re.IGNORECASE)),
    ("dnlim", re.compile(r"\bdnlim\s*\(", re.IGNORECASE)),
)
_INCLUDE_PATTERN = re.compile(r"^(\.(?:include|lib))\s+((?:\"[^\"]+\")|(?:'[^']+')|\S+)(.*)$", re.IGNORECASE)
_MODEL_PATTERN = re.compile(r"^\s*\.model\s+([^\s]+)", re.IGNORECASE)
_SUBCKT_PATTERN = re.compile(r"^\s*\.subckt\s+([^\s(]+)", re.IGNORECASE)


@dataclass(frozen=True)
class SpiceLibraryCompatibility:
    file_path: str
    is_compatible: bool
    model_names: Tuple[str, ...]
    subckt_names: Tuple[str, ...]
    incompatible_reasons: Tuple[str, ...]


@dataclass(frozen=True)
class RuntimeNormalizedNetlist:
    netlist_text: str
    warnings: Tuple[str, ...]
    degraded: bool


class RuntimeFallbackLibraryBuilder:
    def __init__(self) -> None:
        self._model_definitions: Dict[str, Tuple[str, str]] = {}
        self._subckt_definitions: Dict[str, Tuple[Tuple[object, ...], str]] = {}

    def ensure_model(self, requested_name: str, model_text: str, model_kind: str) -> str:
        normalized_name = _sanitize_spice_identifier(requested_name, default=f"CAI_{model_kind.upper()}_MODEL")
        signature = (model_kind, model_text)
        existing = self._model_definitions.get(normalized_name.lower())
        if existing is not None:
            if existing == signature:
                return normalized_name
            normalized_name = self._next_available_name(normalized_name, self._model_definitions)
        self._model_definitions[normalized_name.lower()] = signature
        return normalized_name

    def ensure_subckt(
        self,
        requested_name: str,
        *,
        pin_count: int,
        family: str,
        plus_index: Optional[int],
        minus_index: Optional[int],
        output_index: Optional[int],
    ) -> str:
        default_name = (
            f"CAI_COMPAT_{family.upper()}_{pin_count}"
            if family in {"opamp", "comparator"}
            else f"CAI_COMPAT_{family.upper()}_{pin_count}"
        )
        base_name = _sanitize_spice_identifier(default_name, default=default_name)
        signature = (pin_count, family, plus_index, minus_index, output_index)
        existing = self._subckt_definitions.get(base_name.lower())
        if existing is not None:
            if existing[0] == signature:
                return base_name
            base_name = self._next_available_name(base_name, self._subckt_definitions)
        self._subckt_definitions[base_name.lower()] = (
            signature,
            self._build_subckt_text(
                base_name,
                pin_count=pin_count,
                family=family,
                plus_index=plus_index,
                minus_index=minus_index,
                output_index=output_index,
            ),
        )
        return base_name

    def render(self) -> List[str]:
        lines: List[str] = []
        for name in sorted(self._model_definitions):
            _kind, text = self._model_definitions[name]
            lines.extend(text.splitlines())
        for name in sorted(self._subckt_definitions):
            _signature, text = self._subckt_definitions[name]
            lines.extend(text.splitlines())
        return lines

    def _build_subckt_text(
        self,
        subckt_name: str,
        *,
        pin_count: int,
        family: str,
        plus_index: Optional[int],
        minus_index: Optional[int],
        output_index: Optional[int],
    ) -> str:
        ports = [f"P{index}" for index in range(1, max(1, pin_count) + 1)]
        lines = [f".subckt {subckt_name} {' '.join(ports)}"]
        if family in {"opamp", "comparator"} and plus_index and minus_index and output_index:
            plus_port = ports[plus_index - 1]
            minus_port = ports[minus_index - 1]
            output_port = ports[output_index - 1]
            lines.append(f"E1 NDRV 0 {plus_port} {minus_port} 1e6")
            lines.append(f"R1 NDRV {output_port} 1")
            lines.append(f"R2 {output_port} 0 1e9")
            used_indexes = {plus_index, minus_index, output_index}
        else:
            used_indexes = set()
        resistor_index = 3
        for port_index, port_name in enumerate(ports, start=1):
            if port_index in used_indexes:
                continue
            lines.append(f"R{resistor_index} {port_name} 0 1e12")
            resistor_index += 1
        lines.append(f".ends {subckt_name}")
        return "\n".join(lines)

    @staticmethod
    def _next_available_name(base_name: str, registry: Dict[str, object]) -> str:
        suffix = 2
        while True:
            candidate = f"{base_name}__CAI_{suffix}"
            if candidate.lower() not in registry:
                return candidate
            suffix += 1


class NetlistRuntimeCompatibilityNormalizer:
    def __init__(self) -> None:
        self._parser = SpiceParser()
        self._bundled_opamps = load_bundled_opamp_descriptors()
        self._compatible_bundled_subckts = set(load_runtime_compatible_bundled_subcircuit_path_index().keys())

    def normalize(self, netlist_text: str, *, source_file: str) -> RuntimeNormalizedNetlist:
        warnings: List[str] = []
        degraded = False
        rewritten_text, external_subckts, directive_warnings, directive_degraded = rewrite_library_directives_for_runtime(
            netlist_text,
            source_file=source_file,
            keep_absolute_paths=False,
        )
        warnings.extend(directive_warnings)
        degraded = degraded or directive_degraded

        document = self._parser.parse_content(rewritten_text, source_file)
        defined_subckts = {str(subckt.name or "").strip().lower() for subckt in getattr(document, "subcircuits", [])}
        replacement_lines: Dict[int, str] = {}
        fallback_builder = RuntimeFallbackLibraryBuilder()

        for component in self._iter_components(document):
            if str(getattr(component, "kind", "")).upper() not in {"X", "U"}:
                continue
            model_name = str(getattr(component, "model_name", "") or "").strip()
            if not model_name:
                continue
            normalized_model = model_name.lower()
            if normalized_model in defined_subckts or normalized_model in external_subckts or normalized_model in self._compatible_bundled_subckts:
                continue
            if str(getattr(component, "primitive_kind", "") or "").lower() != "opamp":
                continue
            replacement_name = fallback_builder.ensure_subckt(
                model_name,
                pin_count=len(getattr(component, "pins", []) or []),
                family="opamp",
                plus_index=_pin_index_for_role(getattr(component, "pins", []) or [], "input_plus"),
                minus_index=_pin_index_for_role(getattr(component, "pins", []) or [], "input_minus"),
                output_index=_pin_index_for_role(getattr(component, "pins", []) or [], "output"),
            )
            line_index = int(getattr(getattr(component, "source_span", None), "line_index", -1))
            if line_index < 0:
                continue
            original_line = str(getattr(component, "raw_line", "") or "")
            rewritten_line = _replace_subckt_model_name(original_line, replacement_name)
            if not rewritten_line or rewritten_line == original_line:
                continue
            replacement_lines[line_index] = rewritten_line
            warnings.append(f"{model_name}: 检测到 LTspice 专用运放宏模型，已替换为项目可运行的通用运放子电路。")
            degraded = True

        if replacement_lines:
            lines = rewritten_text.splitlines()
            for line_index, replacement in sorted(replacement_lines.items()):
                if 0 <= line_index < len(lines):
                    lines[line_index] = replacement
            fallback_lines = fallback_builder.render()
            rewritten_text = _append_lines_before_end(lines, fallback_lines)

        return RuntimeNormalizedNetlist(
            netlist_text=rewritten_text,
            warnings=tuple(warnings),
            degraded=degraded,
        )

    def _iter_components(self, document) -> Iterable:
        yield from getattr(document, "components", [])
        for subckt in getattr(document, "subcircuits", []):
            yield from getattr(subckt, "components", [])


def rewrite_library_directives_for_runtime(
    netlist_text: str,
    *,
    source_file: str,
    keep_absolute_paths: bool,
) -> Tuple[str, Set[str], Tuple[str, ...], bool]:
    source_path = Path(str(source_file or "")).expanduser()
    base_dir = source_path.parent if source_path.parent else Path.cwd()
    warnings: List[str] = []
    available_subckts: Set[str] = set()
    result_lines: List[str] = []
    degraded = False

    for raw_line in str(netlist_text or "").splitlines():
        match = _INCLUDE_PATTERN.match(raw_line.strip())
        if match is None:
            result_lines.append(raw_line)
            continue
        command = match.group(1)
        raw_path = match.group(2).strip().strip('"').strip("'")
        suffix = match.group(3).rstrip()
        target_path = Path(raw_path)
        if not target_path.is_absolute():
            target_path = (base_dir / target_path).resolve()
        compatibility = analyze_spice_library_file(target_path)
        if not compatibility.is_compatible:
            degraded = True
            reason_text = ", ".join(compatibility.incompatible_reasons) or "包含当前运行时不支持的 LTspice 专用语法"
            warnings.append(f"已跳过不兼容库 {target_path.as_posix()}：{reason_text}。")
            continue
        available_subckts.update(compatibility.subckt_names)
        rewritten_path = target_path.as_posix() if keep_absolute_paths else raw_path.replace('\\', '/')
        result_lines.append(f'{command} "{rewritten_path}"{suffix}')

    return "\n".join(result_lines), available_subckts, tuple(warnings), degraded


@functools.lru_cache(maxsize=None)
def analyze_spice_library_file(file_path: Path) -> SpiceLibraryCompatibility:
    resolved_path = Path(file_path).expanduser().resolve()
    if not resolved_path.is_file():
        return SpiceLibraryCompatibility(
            file_path=str(resolved_path),
            is_compatible=False,
            model_names=(),
            subckt_names=(),
            incompatible_reasons=("文件不存在",),
        )

    content = _read_optional_text(resolved_path)
    if not content:
        return SpiceLibraryCompatibility(
            file_path=str(resolved_path),
            is_compatible=False,
            model_names=(),
            subckt_names=(),
            incompatible_reasons=("文件不可读",),
        )

    reasons = [label for label, pattern in _UNSUPPORTED_LIBRARY_PATTERNS if pattern.search(content)]
    models = sorted({match.group(1).strip().lower() for match in _MODEL_PATTERN.finditer(content)})
    subckts = sorted({match.group(1).strip().lower() for match in _SUBCKT_PATTERN.finditer(content)})
    return SpiceLibraryCompatibility(
        file_path=str(resolved_path),
        is_compatible=not reasons,
        model_names=tuple(models),
        subckt_names=tuple(subckts),
        incompatible_reasons=tuple(reasons),
    )


@functools.lru_cache(maxsize=1)
def load_runtime_compatible_bundled_subcircuit_path_index() -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    compatibility_by_file: Dict[str, SpiceLibraryCompatibility] = {}
    for header in load_bundled_subcircuit_catalog():
        source_file = Path(header.source_file).resolve()
        file_key = str(source_file).lower()
        compatibility = compatibility_by_file.get(file_key)
        if compatibility is None:
            compatibility = analyze_spice_library_file(source_file)
            compatibility_by_file[file_key] = compatibility
        if not compatibility.is_compatible:
            continue
        index.setdefault(header.name, source_file)
    return index


def _append_lines_before_end(lines: Sequence[str], append_lines: Sequence[str]) -> str:
    materialized = list(lines)
    if not append_lines:
        return "\n".join(materialized)
    inserted = False
    result: List[str] = []
    for line in materialized:
        if line.strip().lower() == ".end" and not inserted:
            result.extend(append_lines)
            inserted = True
        result.append(line)
    if not inserted:
        result.extend(append_lines)
        result.append(".end")
    return "\n".join(result)


def _pin_index_for_role(pins: Sequence[object], role: str) -> Optional[int]:
    for index, pin in enumerate(pins, start=1):
        if str(getattr(pin, "role", "") or "").strip().lower() == role:
            return index
    return None


def _replace_subckt_model_name(raw_line: str, replacement_name: str) -> str:
    pieces = str(raw_line or "").split()
    if len(pieces) < 3:
        return str(raw_line or "")
    model_index = -1
    for index in range(len(pieces) - 1, 0, -1):
        if "=" in pieces[index]:
            continue
        model_index = index
        break
    if model_index <= 0:
        return str(raw_line or "")
    pieces[model_index] = replacement_name
    return " ".join(pieces)


def _sanitize_spice_identifier(value: str, *, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.$:-]", "_", str(value or "").strip())
    if not cleaned:
        cleaned = default
    if cleaned[0].isdigit():
        cleaned = f"CAI_{cleaned}"
    return cleaned


def _read_optional_text(file_path: Path) -> str:
    for encoding in ("utf-8", "latin1", "cp1252"):
        try:
            return file_path.read_text(encoding=encoding, errors="ignore")
        except Exception:
            continue
    return ""


__all__ = [
    "NetlistRuntimeCompatibilityNormalizer",
    "RuntimeFallbackLibraryBuilder",
    "RuntimeNormalizedNetlist",
    "SpiceLibraryCompatibility",
    "analyze_spice_library_file",
    "load_runtime_compatible_bundled_subcircuit_path_index",
    "rewrite_library_directives_for_runtime",
]
