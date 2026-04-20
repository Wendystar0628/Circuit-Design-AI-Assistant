from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from domain.simulation.spice.analysis_directive_authority import normalize_analysis_directive
from domain.simulation.spice.ltspice_symbol_catalog import (
    LtspicePinDefinition,
    LtspiceSymbolCatalog,
    LtspiceSymbolDefinition,
    classify_ltspice_symbol_family,
    normalize_ltspice_symbol_key,
)
from domain.simulation.spice.parser import SpiceParser
from domain.simulation.spice.runtime_compatibility import (
    NetlistRuntimeCompatibilityNormalizer,
    RuntimeFallbackLibraryBuilder,
    analyze_spice_library_file,
    load_runtime_compatible_bundled_subcircuit_path_index,
)
from resources.resource_loader import get_spice_cmp_dir


@dataclass(frozen=True)
class TranscribedAscNetlist:
    source_path: str
    netlist_text: str
    warnings: Tuple[str, ...]
    degraded: bool
    validation_errors: Tuple[str, ...]


@dataclass(frozen=True)
class AscConversionOutput:
    source_path: str
    output_path: str
    warnings: Tuple[str, ...]
    degraded: bool
    validation_errors: Tuple[str, ...]


@dataclass(frozen=True)
class AscBatchConversionExecution:
    output_root: str
    converted_files: Tuple[AscConversionOutput, ...]
    failed_files: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class _Point:
    x: int
    y: int


@dataclass(frozen=True)
class _WireSegment:
    start: _Point
    end: _Point


@dataclass(frozen=True)
class _FlagLabel:
    point: _Point
    label: str


@dataclass
class _SymbolInstance:
    symbol_name: str
    origin: _Point
    orientation: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _PlacedPin:
    name: str
    spice_order: int
    point: _Point


@dataclass(frozen=True)
class _DirectiveRecord:
    text: str
    line_index: int


@dataclass(frozen=True)
class _ResolvedSymbolInstance:
    source: _SymbolInstance
    definition: Optional[LtspiceSymbolDefinition]
    family: str
    pins: Tuple[_PlacedPin, ...]


@dataclass(frozen=True)
class _AscDocument:
    source_file: str
    wires: Tuple[_WireSegment, ...]
    flags: Tuple[_FlagLabel, ...]
    symbols: Tuple[_SymbolInstance, ...]
    directives: Tuple[_DirectiveRecord, ...]


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self._parent = list(range(size))
        self._rank = [0] * size

    def find(self, index: int) -> int:
        parent = self._parent[index]
        if parent != index:
            self._parent[index] = self.find(parent)
        return self._parent[index]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        left_rank = self._rank[left_root]
        right_rank = self._rank[right_root]
        if left_rank < right_rank:
            self._parent[left_root] = right_root
            return
        if left_rank > right_rank:
            self._parent[right_root] = left_root
            return
        self._parent[right_root] = left_root
        self._rank[left_root] += 1


class LtspiceAscToCirTranscriber:
    _EARLY_DIRECTIVE_PREFIXES = (
        ".include",
        ".lib",
        ".param",
        ".options",
        ".func",
        ".global",
        ".ic",
        ".nodeset",
        ".temp",
        ".model",
        ".subckt",
        ".ends",
    )

    def __init__(
        self,
        *,
        symbol_catalog: Optional[LtspiceSymbolCatalog] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._symbol_catalog = symbol_catalog or LtspiceSymbolCatalog()
        self._logger = logger or logging.getLogger(__name__)
        self._parser = SpiceParser()
        self._bundled_subckts = set(load_runtime_compatible_bundled_subcircuit_path_index().keys())
        self._bundled_models = _load_bundled_model_names()
        self._runtime_normalizer = NetlistRuntimeCompatibilityNormalizer()

    def convert_files(self, asc_paths: Sequence[str], output_dir: str) -> AscBatchConversionExecution:
        output_root = Path(str(output_dir or "")).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        converted_files: List[AscConversionOutput] = []
        failed_files: List[Tuple[str, str]] = []
        used_output_names: Set[str] = set()
        for raw_path in asc_paths:
            source_path = Path(str(raw_path or "")).expanduser().resolve()
            try:
                transcribed = self.transcribe_file(str(source_path), output_dir=str(output_root))
                output_name = _build_unique_output_name(source_path.stem, used_output_names)
                used_output_names.add(output_name.lower())
                output_path = output_root / output_name
                output_path.write_text(transcribed.netlist_text, encoding="utf-8")
                converted_files.append(
                    AscConversionOutput(
                        source_path=str(source_path),
                        output_path=str(output_path),
                        warnings=transcribed.warnings,
                        degraded=transcribed.degraded,
                        validation_errors=transcribed.validation_errors,
                    )
                )
            except Exception as exc:
                failed_files.append((str(source_path), str(exc)))
        return AscBatchConversionExecution(
            output_root=str(output_root),
            converted_files=tuple(converted_files),
            failed_files=tuple(failed_files),
        )

    def transcribe_file(self, asc_path: str, *, output_dir: str) -> TranscribedAscNetlist:
        source_path = Path(str(asc_path or "")).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"ASC 文件不存在: {source_path}")
        content = source_path.read_text(encoding="utf-8", errors="ignore")
        document = self._parse_asc_content(content, str(source_path))
        warnings: List[str] = []
        resolved_symbols = self._resolve_symbols(document, warnings)
        point_to_net = self._resolve_point_nets(document, resolved_symbols)
        fallback_builder = RuntimeFallbackLibraryBuilder()
        early_directives, late_directives, directive_warnings = self._rewrite_directives(
            document.directives,
            source_path=source_path,
            output_dir=Path(output_dir).expanduser().resolve(),
        )
        warnings.extend(directive_warnings)
        external_models, external_subckts = self._scan_external_definitions([*early_directives, *late_directives])
        available_models = set(self._bundled_models) | external_models
        available_subckts = set(self._bundled_subckts) | external_subckts
        component_lines: List[str] = []
        degraded = False
        for symbol in resolved_symbols:
            line, symbol_warnings, symbol_degraded = self._emit_component_line(
                symbol,
                point_to_net=point_to_net,
                fallback_builder=fallback_builder,
                available_models=available_models,
                available_subckts=available_subckts,
            )
            if line:
                component_lines.append(line)
            if symbol_warnings:
                warnings.extend(symbol_warnings)
            degraded = degraded or symbol_degraded
        fallback_lines = fallback_builder.render()
        title = _sanitize_title(source_path.stem or source_path.name)
        netlist_lines = [f".title {title}"]
        netlist_lines.extend(early_directives)
        netlist_lines.extend(fallback_lines)
        netlist_lines.extend(component_lines)
        netlist_lines.extend(late_directives)
        netlist_lines.append(".end")
        netlist_text = "\n".join(line for line in netlist_lines if str(line or "").strip()) + "\n"
        normalized_runtime = self._runtime_normalizer.normalize(netlist_text, source_file=str(source_path.with_suffix(".cir")))
        netlist_text = normalized_runtime.netlist_text.rstrip() + "\n"
        warnings.extend(normalized_runtime.warnings)
        degraded = degraded or normalized_runtime.degraded
        validation_errors = self._validate_netlist(netlist_text, str(source_path.with_suffix(".cir")))
        return TranscribedAscNetlist(
            source_path=str(source_path),
            netlist_text=netlist_text,
            warnings=tuple(warnings),
            degraded=degraded,
            validation_errors=tuple(validation_errors),
        )

    def _parse_asc_content(self, content: str, source_file: str) -> _AscDocument:
        wires: List[_WireSegment] = []
        flags: List[_FlagLabel] = []
        symbols: List[_SymbolInstance] = []
        directives: List[_DirectiveRecord] = []
        current_symbol: Optional[_SymbolInstance] = None
        for line_index, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            keyword = stripped.split(None, 1)[0].upper()
            if keyword == "WIRE":
                parts = stripped.split()
                if len(parts) >= 5:
                    wires.append(_WireSegment(
                        start=_Point(x=int(parts[1]), y=int(parts[2])),
                        end=_Point(x=int(parts[3]), y=int(parts[4])),
                    ))
                current_symbol = None
                continue
            if keyword == "FLAG":
                parts = stripped.split(None, 3)
                if len(parts) >= 4:
                    flags.append(_FlagLabel(point=_Point(x=int(parts[1]), y=int(parts[2])), label=parts[3].strip()))
                current_symbol = None
                continue
            if keyword == "SYMBOL":
                parts = stripped.split(None, 4)
                if len(parts) >= 4:
                    current_symbol = _SymbolInstance(
                        symbol_name=parts[1].strip(),
                        origin=_Point(x=int(parts[2]), y=int(parts[3])),
                        orientation=parts[4].strip() if len(parts) > 4 else "R0",
                    )
                    symbols.append(current_symbol)
                continue
            if keyword == "SYMATTR" and current_symbol is not None:
                parts = stripped.split(None, 2)
                if len(parts) >= 2:
                    attr_key = parts[1].strip().lower()
                    attr_value = parts[2].strip() if len(parts) > 2 else ""
                    current_symbol.attrs[attr_key] = attr_value
                continue
            if keyword == "TEXT":
                parts = raw_line.split(None, 5)
                if len(parts) >= 6:
                    payload = parts[5].strip()
                    if payload.startswith("!"):
                        directive = payload[1:].strip()
                    elif payload.startswith("."):
                        directive = payload
                    else:
                        directive = ""
                    if directive:
                        directives.append(_DirectiveRecord(text=directive, line_index=line_index))
                current_symbol = None
                continue
            if keyword not in {"WINDOW", "VERSION", "SHEET", "IOPIN"}:
                current_symbol = None
        return _AscDocument(
            source_file=source_file,
            wires=tuple(wires),
            flags=tuple(flags),
            symbols=tuple(symbols),
            directives=tuple(sorted(directives, key=lambda item: item.line_index)),
        )

    def _resolve_symbols(self, document: _AscDocument, warnings: List[str]) -> Tuple[_ResolvedSymbolInstance, ...]:
        base_points: Set[_Point] = {flag.point for flag in document.flags}
        for wire in document.wires:
            base_points.add(wire.start)
            base_points.add(wire.end)
        resolved: List[_ResolvedSymbolInstance] = []
        for symbol in document.symbols:
            definition = self._resolve_symbol_definition(symbol.symbol_name)
            family = definition.family if definition is not None else classify_ltspice_symbol_family(symbol.symbol_name, "")
            pins: List[_PlacedPin] = []
            if definition is not None and definition.pins:
                for pin in definition.pins:
                    pins.append(_PlacedPin(
                        name=pin.name,
                        spice_order=pin.spice_order,
                        point=_transform_pin(pin, symbol.origin, symbol.orientation),
                    ))
            resolved.append(_ResolvedSymbolInstance(
                source=symbol,
                definition=definition,
                family=family,
                pins=tuple(sorted(pins, key=lambda item: item.spice_order)),
            ))
            for pin in pins:
                base_points.add(pin.point)
        final_resolved: List[_ResolvedSymbolInstance] = []
        available_points = tuple(base_points)
        for symbol in resolved:
            if symbol.pins:
                final_resolved.append(symbol)
                continue
            inferred_points = self._infer_generic_pins(symbol.source.origin, available_points)
            if inferred_points:
                warnings.append(f"{symbol.source.symbol_name}: 缺少 .asy 定义，已按周边连线推断引脚。")
            else:
                inferred_points = (symbol.source.origin,)
                warnings.append(f"{symbol.source.symbol_name}: 无法恢复引脚几何，已使用单端兜底。")
            inferred_pins = tuple(
                _PlacedPin(name=f"P{index}", spice_order=index, point=point)
                for index, point in enumerate(inferred_points, start=1)
            )
            final_resolved.append(_ResolvedSymbolInstance(
                source=symbol.source,
                definition=None,
                family=symbol.family,
                pins=inferred_pins,
            ))
        return tuple(final_resolved)

    def _resolve_point_nets(
        self,
        document: _AscDocument,
        symbols: Sequence[_ResolvedSymbolInstance],
    ) -> Dict[_Point, str]:
        points: List[_Point] = []
        seen: Set[_Point] = set()
        def _add_point(point: _Point) -> None:
            if point in seen:
                return
            seen.add(point)
            points.append(point)
        for flag in document.flags:
            _add_point(flag.point)
        for wire in document.wires:
            _add_point(wire.start)
            _add_point(wire.end)
        for symbol in symbols:
            for pin in symbol.pins:
                _add_point(pin.point)
        dsu = _DisjointSet(len(points))
        point_index = {point: index for index, point in enumerate(points)}
        for wire in document.wires:
            on_segment = [point for point in points if _point_on_segment(point, wire)]
            if len(on_segment) < 2:
                continue
            ordered_points = sorted(on_segment, key=lambda point: (point.x, point.y) if wire.start.x != wire.end.x else (point.y, point.x))
            for left, right in zip(ordered_points, ordered_points[1:]):
                dsu.union(point_index[left], point_index[right])
        labels_by_root: Dict[int, List[str]] = {}
        for flag in document.flags:
            root = dsu.find(point_index[flag.point])
            labels_by_root.setdefault(root, []).append(flag.label)
        auto_index = 1
        names_by_root: Dict[int, str] = {}
        for point in points:
            root = dsu.find(point_index[point])
            if root in names_by_root:
                continue
            labels = labels_by_root.get(root, [])
            resolved_label = _choose_net_label(labels)
            if resolved_label:
                names_by_root[root] = resolved_label
                continue
            names_by_root[root] = f"N{auto_index:03d}"
            auto_index += 1
        return {
            point: names_by_root[dsu.find(point_index[point])]
            for point in points
        }

    def _rewrite_directives(
        self,
        directives: Sequence[_DirectiveRecord],
        *,
        source_path: Path,
        output_dir: Path,
    ) -> Tuple[List[str], List[str], Tuple[str, ...]]:
        early: List[str] = []
        late: List[str] = []
        warnings: List[str] = []
        for record in directives:
            rewritten, directive_warnings = self._rewrite_single_directive(record.text, source_path=source_path, output_dir=output_dir)
            warnings.extend(directive_warnings)
            if not rewritten or rewritten.lower() == ".end":
                continue
            if rewritten.lower().startswith(self._EARLY_DIRECTIVE_PREFIXES):
                early.append(rewritten)
            else:
                late.append(rewritten)
        return early, late, tuple(warnings)

    def _rewrite_single_directive(self, directive: str, *, source_path: Path, output_dir: Path) -> Tuple[str, Tuple[str, ...]]:
        text = str(directive or "").strip()
        if not text:
            return "", ()
        normalized_analysis = normalize_analysis_directive(text)
        if normalized_analysis is not None:
            return normalized_analysis, ()
        match = re.match(r"^(\.(?:include|lib))\s+((?:\"[^\"]+\")|(?:'[^']+')|\S+)(.*)$", text, re.IGNORECASE)
        if match is None:
            return text, ()
        command = match.group(1)
        raw_path = match.group(2).strip().strip('"').strip("'")
        suffix = match.group(3).rstrip()
        include_path = Path(raw_path)
        if not include_path.is_absolute():
            include_path = (source_path.parent / include_path).resolve()
        compatibility = analyze_spice_library_file(include_path)
        if not compatibility.is_compatible:
            reason_text = ", ".join(compatibility.incompatible_reasons) or "包含当前项目不支持的 LTspice 专用语法"
            return "", (f"已跳过不兼容库 {include_path.as_posix()}：{reason_text}。",)
        rewritten_path = include_path.as_posix()
        return f"{command} \"{rewritten_path}\"{suffix}", ()

    def _scan_external_definitions(self, directives: Sequence[str]) -> Tuple[Set[str], Set[str]]:
        model_names: Set[str] = set()
        subckt_names: Set[str] = set()
        visited_files: Set[str] = set()
        for directive in directives:
            match = re.match(r"^\.(?:include|lib)\s+((?:\"[^\"]+\")|(?:'[^']+')|\S+)", str(directive or "").strip(), re.IGNORECASE)
            if match is None:
                continue
            target_path = Path(match.group(1).strip().strip('"').strip("'"))
            if not target_path.is_absolute() or not target_path.is_file():
                continue
            normalized_path = str(target_path.resolve()).lower()
            if normalized_path in visited_files:
                continue
            visited_files.add(normalized_path)
            compatibility = analyze_spice_library_file(target_path)
            if not compatibility.is_compatible:
                continue
            model_names.update(compatibility.model_names)
            subckt_names.update(compatibility.subckt_names)
        return model_names, subckt_names

    def _emit_component_line(
        self,
        symbol: _ResolvedSymbolInstance,
        *,
        point_to_net: Dict[_Point, str],
        fallback_builder: RuntimeFallbackLibraryBuilder,
        available_models: Set[str],
        available_subckts: Set[str],
    ) -> Tuple[str, Tuple[str, ...], bool]:
        attrs = _merged_symbol_attrs(symbol)
        prefix = str(attrs.get("prefix") or (symbol.definition.prefix if symbol.definition is not None else "") or "X")
        family = symbol.family
        pins = list(symbol.pins)
        nodes = [point_to_net.get(pin.point, "0") for pin in pins]
        name = _build_instance_name(attrs.get("instname", ""), prefix=prefix, family=family)
        warnings: List[str] = []
        degraded = False
        lead = prefix[:1].upper() if prefix else "X"
        value_text = _normalize_value_text(attrs.get("value", ""))
        value2_text = str(attrs.get("value2", "")).strip()
        spice_model_text = str(attrs.get("spicemodel", "")).strip()
        spice_line_text = str(attrs.get("spiceline", "")).strip()
        spice_line2_text = str(attrs.get("spiceline2", "")).strip()
        pin_roles = _infer_pin_roles(pins)

        if lead in {"R", "C", "L"} and len(nodes) >= 2:
            default_values = {"R": "1k", "C": "1u", "L": "1m"}
            raw_value = value_text or default_values[lead]
            return f"{name} {nodes[0]} {nodes[1]} {raw_value}", tuple(warnings), degraded

        if lead in {"V", "I"} and len(nodes) >= 2:
            raw_value = value_text or "0"
            return f"{name} {nodes[0]} {nodes[1]} {raw_value}", tuple(warnings), degraded

        if lead == "B" and len(nodes) >= 2:
            if not value_text:
                value_text = "I=0" if family in {"behavioral", "current_source"} or symbol.source.symbol_name.lower().endswith("bi") else "V=0"
                degraded = True
                warnings.append(f"{symbol.source.symbol_name}: 行为源表达式缺失，已降级为零输出。")
            return f"{name} {nodes[0]} {nodes[1]} {value_text}", tuple(warnings), degraded

        if lead in {"E", "G"} and len(nodes) >= 4:
            raw_value = value_text or "1"
            if not value_text:
                degraded = True
                warnings.append(f"{symbol.source.symbol_name}: 受控源增益缺失，已使用默认值 1。")
            return f"{name} {nodes[0]} {nodes[1]} {nodes[2]} {nodes[3]} {raw_value}", tuple(warnings), degraded

        if lead in {"F", "H"} and len(nodes) >= 2:
            if value_text:
                return f"{name} {nodes[0]} {nodes[1]} {value_text}", tuple(warnings), degraded
            degraded = True
            warnings.append(f"{symbol.source.symbol_name}: 电流控制源控制信息缺失，已降级为零输出行为源。")
            fallback_name = _build_instance_name(attrs.get("instname", ""), prefix="B", family=family)
            expr = "I=0" if lead == "F" else "V=0"
            return f"{fallback_name} {nodes[0]} {nodes[1]} {expr}", tuple(warnings), degraded

        if lead == "S" and len(nodes) >= 4:
            model_name = value_text or "CAI_SW_DEFAULT"
            if not value_text or model_name.lower() not in available_models:
                model_name = fallback_builder.ensure_model(
                    model_name,
                    ".model {name} SW(Ron=1 Roff=1e12 Vt=0.5 Vh=0.1)".format(name=_sanitize_spice_identifier(model_name, default="CAI_SW_DEFAULT")),
                    "sw",
                )
                degraded = degraded or not value_text
            return f"{name} {nodes[0]} {nodes[1]} {nodes[2]} {nodes[3]} {model_name}", tuple(warnings), degraded

        if lead == "W" and len(nodes) >= 2:
            value_tokens = value_text.split()
            if len(value_tokens) >= 2:
                model_name = value_tokens[-1]
                control_blob = " ".join(value_tokens[:-1])
                if model_name.lower() not in available_models:
                    model_name = fallback_builder.ensure_model(
                        model_name,
                        ".model {name} SW(Ron=1 Roff=1e12 Vt=0.5 Vh=0.1)".format(name=_sanitize_spice_identifier(model_name, default="CAI_CSW_DEFAULT")),
                        "csw",
                    )
                    degraded = True
                return f"{name} {nodes[0]} {nodes[1]} {control_blob} {model_name}", tuple(warnings), degraded
            degraded = True
            warnings.append(f"{symbol.source.symbol_name}: 电流控制开关控制信息缺失，已降级为高阻电阻。")
            fallback_name = _build_instance_name(attrs.get("instname", ""), prefix="R", family=family)
            return f"{fallback_name} {nodes[0]} {nodes[1]} 1e12", tuple(warnings), degraded

        if lead == "D" and len(nodes) >= 2:
            requested_name = value_text or _default_model_name(symbol, lead)
            model_name = requested_name
            if model_name.lower() not in available_models:
                model_name = fallback_builder.ensure_model(
                    requested_name,
                    _generic_model_text(_diode_model_kind(symbol), requested_name),
                    _diode_model_kind(symbol),
                )
                degraded = degraded or not value_text
            return f"{name} {nodes[0]} {nodes[1]} {model_name}", tuple(warnings), degraded

        if lead in {"Q", "M", "J"} and len(nodes) >= 3:
            requested_name = value_text or _default_model_name(symbol, lead)
            model_name = requested_name
            model_kind = _primitive_model_kind(symbol, lead)
            if model_name.lower() not in available_models:
                model_name = fallback_builder.ensure_model(
                    requested_name,
                    _generic_model_text(model_kind, requested_name),
                    model_kind,
                )
                degraded = degraded or not value_text
            if lead == "M":
                limited_nodes = list(nodes[:4])
                if len(limited_nodes) == 3:
                    limited_nodes.append(limited_nodes[2])
                    degraded = True
                    warnings.append(f"{symbol.source.symbol_name}: MOS 缺少 body 节点，已将 body 绑定到 source 以兼容当前运行时。")
            else:
                limited_nodes = nodes[:4]
            return f"{name} {' '.join(limited_nodes)} {model_name}", tuple(warnings), degraded

        model_name_candidates = [
            candidate
            for candidate in (
                value_text,
                value2_text if _looks_like_model_token(value2_text) else "",
                spice_model_text if _looks_like_model_token(spice_model_text) else "",
            )
            if candidate
        ]
        requested_model_name = model_name_candidates[0] if model_name_candidates else _default_subckt_name(symbol)
        subckt_name = requested_model_name
        if subckt_name.lower() not in available_subckts:
            subckt_name = fallback_builder.ensure_subckt(
                requested_model_name,
                pin_count=max(1, len(nodes)),
                family=family,
                plus_index=pin_roles.get("plus"),
                minus_index=pin_roles.get("minus"),
                output_index=pin_roles.get("output"),
            )
            degraded = True
            warnings.append(f"{symbol.source.symbol_name}: 子电路模型缺失，已生成可运行兜底子电路。")
        param_blobs = [blob for blob in (value2_text, spice_line_text, spice_line2_text) if _looks_like_param_blob(blob)]
        if not nodes:
            nodes = ["0"]
            degraded = True
        return f"{name} {' '.join(nodes)} {subckt_name}{(' ' + ' '.join(param_blobs)) if param_blobs else ''}", tuple(warnings), degraded

    def _validate_netlist(self, netlist_text: str, source_file: str) -> List[str]:
        try:
            document = self._parser.parse_content(netlist_text, source_file)
        except Exception as exc:
            return [str(exc)]
        return [str(item.message or "") for item in getattr(document, "parse_errors", []) if str(item.message or "")]

    def _resolve_symbol_definition(self, symbol_name: str) -> Optional[LtspiceSymbolDefinition]:
        normalized = normalize_ltspice_symbol_key(symbol_name)
        definition = self._symbol_catalog.lookup(normalized)
        if definition is not None:
            return definition
        basename = normalized.rsplit("/", 1)[-1]
        alias_candidates = [basename]
        if normalized.startswith("opamps/"):
            alias_candidates.extend(["opamps/lt1001", "opamps/opamp2", "opamps/opamp"])
        if normalized.startswith("comparators/"):
            alias_candidates.append("comparators/lt1011")
        if any(token in basename for token in ("npn", "pnp", "nmos", "pmos", "njf", "pjf", "diode", "zener", "schottky", "battery", "voltage", "current", "res", "cap", "ind", "opamp", "ne555")):
            alias_candidates.extend([
                "npn" if "npn" in basename else "pnp" if "pnp" in basename else "nmos" if "nmos" in basename else "pmos" if "pmos" in basename else "njf" if "njf" in basename else "pjf" if "pjf" in basename else "diode" if "diode" in basename else "zener" if "zener" in basename else "schottky" if "schottky" in basename else "battery" if "battery" in basename else "voltage" if "voltage" in basename else "current" if "current" in basename else "res" if "res" in basename else "cap" if "cap" in basename else "ind" if "ind" in basename else "opamps/lt1001" if "opamp" in basename else "misc/ne555",
            ])
        for candidate in alias_candidates:
            definition = self._symbol_catalog.lookup(candidate)
            if definition is not None:
                return definition
        return None

    def _infer_generic_pins(self, origin: _Point, points: Sequence[_Point]) -> Tuple[_Point, ...]:
        nearby = [
            point for point in points
            if abs(point.x - origin.x) <= 160 and abs(point.y - origin.y) <= 160 and point != origin
        ]
        if not nearby:
            return ()
        def _sort_key(point: _Point) -> Tuple[int, int, int]:
            dx = point.x - origin.x
            dy = point.y - origin.y
            if abs(dx) >= abs(dy):
                side = 0 if dx < 0 else 2
                detail = point.y
            else:
                side = 1 if dy < 0 else 3
                detail = point.x
            return side, detail, abs(dx) + abs(dy)
        unique_points: List[_Point] = []
        seen: Set[_Point] = set()
        for point in sorted(nearby, key=_sort_key):
            if point in seen:
                continue
            seen.add(point)
            unique_points.append(point)
        return tuple(unique_points)



def _transform_pin(pin: LtspicePinDefinition, origin: _Point, orientation: str) -> _Point:
    relative_x = int(pin.x)
    relative_y = int(pin.y)
    normalized_orientation = str(orientation or "R0").strip().upper()
    mirrored = normalized_orientation.startswith("M")
    angle_text = normalized_orientation[1:] if normalized_orientation[:1] in {"R", "M"} else "0"
    try:
        angle = int(angle_text or "0") % 360
    except ValueError:
        angle = 0
    if mirrored:
        relative_x = -relative_x
    if angle == 90:
        rotated_x, rotated_y = -relative_y, relative_x
    elif angle == 180:
        rotated_x, rotated_y = -relative_x, -relative_y
    elif angle == 270:
        rotated_x, rotated_y = relative_y, -relative_x
    else:
        rotated_x, rotated_y = relative_x, relative_y
    return _Point(x=origin.x + rotated_x, y=origin.y + rotated_y)



def _point_on_segment(point: _Point, segment: _WireSegment) -> bool:
    min_x = min(segment.start.x, segment.end.x)
    max_x = max(segment.start.x, segment.end.x)
    min_y = min(segment.start.y, segment.end.y)
    max_y = max(segment.start.y, segment.end.y)
    if point.x < min_x or point.x > max_x or point.y < min_y or point.y > max_y:
        return False
    dx_segment = segment.end.x - segment.start.x
    dy_segment = segment.end.y - segment.start.y
    dx_point = point.x - segment.start.x
    dy_point = point.y - segment.start.y
    return dx_segment * dy_point == dy_segment * dx_point



def _choose_net_label(labels: Sequence[str]) -> str:
    cleaned = [_sanitize_net_name(label) for label in labels if _sanitize_net_name(label)]
    for label in cleaned:
        if label.lower() in {"0", "gnd", "gnd!"}:
            return "0"
    return cleaned[0] if cleaned else ""



def _sanitize_title(value: str) -> str:
    text = str(value or "").strip()
    return text if text else "LTspice ASC Conversion"



def _merged_symbol_attrs(symbol: _ResolvedSymbolInstance) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    if symbol.definition is not None:
        merged.update(symbol.definition.defaults)
    merged.update(symbol.source.attrs)
    return merged



def _build_instance_name(raw_name: str, *, prefix: str, family: str) -> str:
    lead = (str(prefix or "")[:1] or ("X" if family in {"opamp", "comparator", "subckt", "generic"} else "R")).upper()
    normalized = _sanitize_spice_identifier(raw_name, default=f"{lead}1")
    if normalized[:1].upper() == lead:
        return normalized
    return f"{lead}{normalized}"



def _sanitize_spice_identifier(value: str, *, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.$:-]", "_", str(value or "").strip())
    if not cleaned:
        cleaned = default
    if cleaned[0].isdigit():
        cleaned = f"CAI_{cleaned}"
    return cleaned



def _sanitize_net_name(value: str) -> str:
    text = re.sub(r"\s+", "_", str(value or "").strip())
    return text if text else ""



def _normalize_value_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "..." in text:
        return ""
    if text.upper() in {"R", "C", "L", "V", "I", "D", "E", "F", "G", "H", "SW", "CSW", "BI", "BV"}:
        return ""
    return text



def _looks_like_file_token(value: str) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and ("/" in text or "\\" in text or text.endswith((".lib", ".sub", ".mod", ".cir", ".sp", ".ckt")))



def _looks_like_param_blob(value: str) -> bool:
    return "=" in str(value or "")



def _looks_like_model_token(value: str) -> bool:
    text = str(value or "").strip()
    if not text or _looks_like_file_token(text) or _looks_like_param_blob(text):
        return False
    return True



def _infer_pin_roles(pins: Sequence[_PlacedPin]) -> Dict[str, Optional[int]]:
    plus_index: Optional[int] = None
    minus_index: Optional[int] = None
    output_index: Optional[int] = None
    for pin in pins:
        name = str(pin.name or "").strip().lower()
        if plus_index is None and name in {"in+", "+", "noninvin", "noninv", "inp", "vin+", "nc+"}:
            plus_index = pin.spice_order
        if minus_index is None and name in {"in-", "-", "invin", "inv", "inn", "vin-", "nc-"}:
            minus_index = pin.spice_order
        if output_index is None and name in {"out", "output", "vout", "o"}:
            output_index = pin.spice_order
    return {
        "plus": plus_index,
        "minus": minus_index,
        "output": output_index,
    }



def _default_model_name(symbol: _ResolvedSymbolInstance, lead: str) -> str:
    lead_upper = lead.upper()
    if lead_upper == "D":
        return "CAI_DIODE_DEFAULT"
    if lead_upper == "Q":
        return "CAI_PNP_DEFAULT" if "pnp" in symbol.source.symbol_name.lower() else "CAI_NPN_DEFAULT"
    if lead_upper == "M":
        return "CAI_PMOS_DEFAULT" if "pmos" in symbol.source.symbol_name.lower() else "CAI_NMOS_DEFAULT"
    if lead_upper == "J":
        return "CAI_PJF_DEFAULT" if "pjf" in symbol.source.symbol_name.lower() else "CAI_NJF_DEFAULT"
    return f"CAI_{lead_upper}_DEFAULT"



def _default_subckt_name(symbol: _ResolvedSymbolInstance) -> str:
    symbol_key = normalize_ltspice_symbol_key(symbol.source.symbol_name)
    basename = symbol_key.rsplit("/", 1)[-1] if symbol_key else "subckt"
    return _sanitize_spice_identifier(basename or "subckt", default="CAI_SUBCKT_FALLBACK")



def _primitive_model_kind(symbol: _ResolvedSymbolInstance, lead: str) -> str:
    name = symbol.source.symbol_name.lower()
    if lead.upper() == "Q":
        return "pnp" if "pnp" in name else "npn"
    if lead.upper() == "M":
        return "pmos" if "pmos" in name else "nmos"
    if lead.upper() == "J":
        return "pjf" if "pjf" in name else "njf"
    return lead.lower()



def _diode_model_kind(symbol: _ResolvedSymbolInstance) -> str:
    name = symbol.source.symbol_name.lower()
    if "zener" in name:
        return "zener"
    if "schottky" in name:
        return "schottky"
    return "diode"



def _generic_model_text(model_kind: str, requested_name: str) -> str:
    name = _sanitize_spice_identifier(requested_name, default=f"CAI_{model_kind.upper()}_DEFAULT")
    mapping = {
        "diode": f".model {name} D(Is=1e-14 N=1 Rs=0.1)",
        "zener": f".model {name} D(Is=1e-14 N=1 Rs=0.1 Bv=5.1 Ibv=1m)",
        "schottky": f".model {name} D(Is=1e-8 N=1.05 Rs=0.05)",
        "npn": f".model {name} NPN(Is=1e-14 Bf=100 Vaf=100)",
        "pnp": f".model {name} PNP(Is=1e-14 Bf=100 Vaf=100)",
        "nmos": f".model {name} NMOS(Level=1 Vto=1 Kp=1m Lambda=0.01)",
        "pmos": f".model {name} PMOS(Level=1 Vto=-1 Kp=1m Lambda=0.01)",
        "njf": f".model {name} NJF(Beta=1m Vto=-2 Lambda=0.01)",
        "pjf": f".model {name} PJF(Beta=1m Vto=2 Lambda=0.01)",
        "sw": f".model {name} SW(Ron=1 Roff=1e12 Vt=0.5 Vh=0.1)",
        "csw": f".model {name} SW(Ron=1 Roff=1e12 Vt=0.5 Vh=0.1)",
    }
    return mapping.get(model_kind, f".model {name} D(Is=1e-14 N=1 Rs=0.1)")



def _build_unique_output_name(stem: str, used_names: Set[str]) -> str:
    safe_stem = re.sub(r"[\\/:*?\"<>|]+", "_", str(stem or "converted").strip()) or "converted"
    candidate = f"{safe_stem}.cir"
    if candidate.lower() not in used_names:
        return candidate
    index = 2
    while True:
        candidate = f"{safe_stem}_{index}.cir"
        if candidate.lower() not in used_names:
            return candidate
        index += 1


def _read_optional_text(file_path: Path) -> str:
    for encoding in ("utf-8", "latin1"):
        try:
            return file_path.read_text(encoding=encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _load_bundled_model_names() -> Set[str]:
    model_names: Set[str] = set()
    cmp_dir = get_spice_cmp_dir()
    if not cmp_dir.exists():
        return model_names
    pattern = re.compile(r"^\s*\.model\s+([^\s]+)", re.IGNORECASE)
    for file_path in cmp_dir.iterdir():
        if not file_path.is_file():
            continue
        for encoding in ("utf-8", "latin1"):
            try:
                content = file_path.read_text(encoding=encoding, errors="ignore")
                break
            except Exception:
                content = ""
        for line in content.splitlines():
            match = pattern.match(line)
            if match is not None:
                model_names.add(match.group(1).strip().lower())
    return model_names


__all__ = [
    "AscBatchConversionExecution",
    "AscConversionOutput",
    "LtspiceAscToCirTranscriber",
    "TranscribedAscNetlist",
]
