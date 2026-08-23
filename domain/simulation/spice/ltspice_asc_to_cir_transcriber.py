from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from domain.simulation.spice.include_parser import IncludeParser
from domain.simulation.spice.ltspice_symbol_catalog import (
    LtspicePinDefinition,
    LtspiceSymbolCatalog,
    LtspiceSymbolDefinition,
    normalize_ltspice_symbol_key,
)
from domain.simulation.spice.parser import SpiceParser
from domain.simulation.spice.numeric import format_spice_number, parse_spice_number
from domain.simulation.spice.runtime_compatibility import (
    analyze_spice_library_file,
)


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
    def __init__(
        self,
        *,
        symbol_catalog: Optional[LtspiceSymbolCatalog] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._symbol_catalog = symbol_catalog or LtspiceSymbolCatalog()
        self._logger = logger or logging.getLogger(__name__)
        self._parser = SpiceParser()
        self._include_parser = IncludeParser()

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
        rewritten_directives, directive_warnings = self._rewrite_directives(
            document.directives,
            source_path=source_path,
        )
        warnings.extend(directive_warnings)
        external_models, external_subckts, external_vdmos_models = self._scan_external_definitions(rewritten_directives)
        # Conversion output must be self-describing.  A name merely existing
        # somewhere in the application's bundled catalog does not make it
        # available to ngspice; only explicit inline/include definitions count.
        available_models = external_models
        available_subckts = external_subckts
        vdmos_models = external_vdmos_models
        component_lines: List[str] = []
        degraded = False
        for symbol in resolved_symbols:
            line, symbol_warnings, symbol_degraded = self._emit_component_line(
                symbol,
                point_to_net=point_to_net,
                available_models=available_models,
                available_subckts=available_subckts,
                vdmos_models=vdmos_models,
            )
            if line:
                component_lines.append(line)
            if symbol_warnings:
                warnings.extend(symbol_warnings)
            degraded = degraded or symbol_degraded
        title = _sanitize_title(source_path.stem or source_path.name)
        netlist_lines = [f".title {title}"]
        # Keep every ASC text directive in source order.  Splitting directives
        # into "early" and "late" groups used to move .ends ahead of the
        # subcircuit body, silently changing a valid embedded definition into
        # unrelated top-level components.  ngspice preprocesses model,
        # parameter and analysis cards without requiring that reordering.
        netlist_lines.extend(rewritten_directives)
        netlist_lines.extend(component_lines)
        netlist_lines.append(".end")
        netlist_text = "\n".join(line for line in netlist_lines if str(line or "").strip()) + "\n"
        validation_errors = self._validate_netlist(netlist_text, str(source_path.with_suffix(".cir")))
        if validation_errors:
            raise ValueError("ASC 转换结果未通过 SPICE 语义校验: " + "; ".join(validation_errors))
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
        resolved: List[_ResolvedSymbolInstance] = []
        for symbol in document.symbols:
            definition = self._resolve_symbol_definition(symbol.symbol_name)
            if definition is None:
                raise ValueError(
                    f"{symbol.symbol_name}: 缺少精确 .asy 符号定义，禁止猜测引脚或替换成通用元件"
                )
            if not definition.pins:
                raise ValueError(f"{symbol.symbol_name}: .asy 符号未提供 SpiceOrder 引脚")
            pins: List[_PlacedPin] = []
            for pin in definition.pins:
                pins.append(_PlacedPin(
                    name=pin.name,
                    spice_order=pin.spice_order,
                    point=_transform_pin(pin, symbol.origin, symbol.orientation),
                ))
            resolved.append(_ResolvedSymbolInstance(
                source=symbol,
                definition=definition,
                family=definition.family,
                pins=tuple(sorted(pins, key=lambda item: item.spice_order)),
            ))
        return tuple(resolved)

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
    ) -> Tuple[List[str], Tuple[str, ...]]:
        rewritten_directives: List[str] = []
        warnings: List[str] = []
        for record in directives:
            rewritten, directive_warnings = self._rewrite_single_directive(record.text, source_path=source_path)
            warnings.extend(directive_warnings)
            if not rewritten or rewritten.lower() == ".end":
                continue
            rewritten_directives.append(rewritten)
        return rewritten_directives, tuple(warnings)

    def _rewrite_single_directive(self, directive: str, *, source_path: Path) -> Tuple[str, Tuple[str, ...]]:
        text = str(directive or "").strip()
        if not text:
            return "", ()
        command = text.split(None, 1)[0].lower()
        if command == ".tran":
            converted = _convert_ltspice_transient_shorthand(text)
            if converted:
                return converted, (
                    "LTspice 单参数 .tran 已转为 ngspice 显式 tstep/tstop；"
                    "tstep 取 tstop/1000，请按波形带宽复核采样密度。",
                )
        if command in {".op", ".tran", ".ac", ".dc", ".noise"}:
            return text, ()
        if command not in {".include", ".inc", ".incpslt", ".lib"}:
            return text, ()
        parsed = self._include_parser.parse_line(text, 1)
        # A one-argument .lib names an in-file library section rather than a
        # file dependency; preserve it verbatim.  Malformed include cards are
        # rejected now instead of being copied into an inevitably failing deck.
        if parsed is None:
            if command == ".lib":
                return text, ()
            raise ValueError(f"无效的 SPICE 库引用: {text}")
        include_path = Path(parsed.raw_path)
        if not include_path.is_absolute():
            include_path = (source_path.parent / include_path).resolve()
        compatibility = analyze_spice_library_file(include_path)
        if not include_path.is_file():
            raise ValueError(f"SPICE 库文件不存在: {include_path.as_posix()}")
        if not compatibility.is_compatible:
            reason_text = ", ".join(compatibility.incompatible_reasons) or "包含当前项目不支持的 LTspice 专用语法"
            raise ValueError(
                f"SPICE 库 {include_path.as_posix()} 无法由当前 ngspice 可靠执行: {reason_text}"
            )
        rewritten_path = include_path.as_posix()
        if parsed.statement_type == "lib":
            return f'.lib "{rewritten_path}" {parsed.library_section}', ()
        if parsed.statement_type == "incpslt":
            return f'.incpslt "{rewritten_path}"', ()
        return f'.include "{rewritten_path}"', ()

    def _scan_external_definitions(self, directives: Sequence[str]) -> Tuple[Set[str], Set[str], Set[str]]:
        inline_models, inline_vdmos_models = _scan_model_catalog("\n".join(directives))
        model_names: Set[str] = set(inline_models)
        subckt_names: Set[str] = set()
        vdmos_models: Set[str] = set(inline_vdmos_models)
        visited_files: Set[str] = set()
        for directive in directives:
            subckt_match = re.match(r"^\s*\.subckt\s+([^\s(]+)", str(directive or ""), re.IGNORECASE)
            if subckt_match is not None:
                subckt_names.add(subckt_match.group(1).strip().lower())
            parsed = self._include_parser.parse_line(str(directive or ""), 1)
            if parsed is None:
                continue
            target_path = Path(parsed.raw_path)
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
            file_model_names, file_vdmos_models = _scan_model_catalog(_read_optional_text(target_path))
            model_names.update(file_model_names)
            vdmos_models.update(file_vdmos_models)
        return model_names, subckt_names, vdmos_models

    def _emit_component_line(
        self,
        symbol: _ResolvedSymbolInstance,
        *,
        point_to_net: Dict[_Point, str],
        available_models: Set[str],
        available_subckts: Set[str],
        vdmos_models: Set[str],
    ) -> Tuple[str, Tuple[str, ...], bool]:
        attrs = _merged_symbol_attrs(symbol)
        prefix = str(attrs.get("prefix") or (symbol.definition.prefix if symbol.definition is not None else "") or "X")
        family = symbol.family
        pins = list(symbol.pins)
        nodes = [point_to_net[pin.point] for pin in pins]
        name = _build_instance_name(attrs.get("instname", ""), prefix=prefix, family=family)
        warnings: List[str] = []
        lead = prefix[:1].upper() if prefix else "X"
        value_text = _normalize_value_text(attrs.get("value", ""))
        value2_text = str(attrs.get("value2", "")).strip()
        spice_model_text = str(attrs.get("spicemodel", "")).strip()
        spice_line_text = str(attrs.get("spiceline", "")).strip()
        spice_line2_text = str(attrs.get("spiceline2", "")).strip()
        extra_parameters = " ".join(
            value for value in (value2_text, spice_line_text, spice_line2_text) if value
        )

        if lead in {"R", "C", "L"}:
            if len(nodes) != 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: {lead} 器件必须有两个 SpiceOrder 引脚")
            if not value_text:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 缺少元件值，禁止填入伪默认值")
            suffix = f" {extra_parameters}" if extra_parameters else ""
            return f"{name} {nodes[0]} {nodes[1]} {value_text}{suffix}", tuple(warnings), False

        if lead in {"V", "I"}:
            if len(nodes) != 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 独立源必须有正、负两个 SpiceOrder 引脚")
            source_specification = " ".join(
                value for value in (value_text, value2_text, spice_line_text, spice_line2_text) if value
            )
            if not source_specification:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 独立源没有 DC、AC 或时域激励定义")
            return f"{name} {nodes[0]} {nodes[1]} {source_specification}", tuple(warnings), False

        if lead == "B":
            if len(nodes) != 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 行为源必须有两个 SpiceOrder 引脚")
            expression = " ".join(
                value for value in (value_text, value2_text, spice_line_text, spice_line2_text) if value
            )
            if not expression:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 行为源表达式缺失")
            return f"{name} {nodes[0]} {nodes[1]} {expression}", tuple(warnings), False

        if lead in {"E", "G"}:
            if len(nodes) != 4:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 线性受控源必须有四个 SpiceOrder 引脚")
            control_specification = " ".join(
                value for value in (value_text, value2_text, spice_line_text, spice_line2_text) if value
            )
            if not control_specification:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 受控源增益或表达式缺失")
            return (
                f"{name} {nodes[0]} {nodes[1]} {nodes[2]} {nodes[3]} {control_specification}",
                tuple(warnings),
                False,
            )

        if lead in {"F", "H"}:
            if len(nodes) != 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 电流控制源必须有两个输出 SpiceOrder 引脚")
            control_blob = " ".join(value for value in (value_text, value2_text, spice_line_text, spice_line2_text) if value)
            if len(control_blob.split()) < 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 电流控制源缺少控制电压源名或增益")
            return f"{name} {nodes[0]} {nodes[1]} {control_blob}", tuple(warnings), False

        if lead == "S":
            if len(nodes) != 4:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 电压控制开关必须有四个 SpiceOrder 引脚")
            if not value_text:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 开关模型名缺失")
            if value_text.lower() not in available_models:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 开关模型 {value_text} 未定义")
            suffix = f" {extra_parameters}" if extra_parameters else ""
            return f"{name} {nodes[0]} {nodes[1]} {nodes[2]} {nodes[3]} {value_text}{suffix}", tuple(warnings), False

        if lead == "W":
            if len(nodes) != 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 电流控制开关必须有两个 SpiceOrder 引脚")
            control_blob = " ".join(value for value in (value_text, value2_text, spice_line_text, spice_line2_text) if value)
            value_tokens = control_blob.split()
            if len(value_tokens) >= 2:
                model_name = value_tokens[-1]
                if model_name.lower() not in available_models:
                    raise ValueError(f"{symbol.source.symbol_name}/{name}: 电流控制开关模型 {model_name} 未定义")
                return f"{name} {nodes[0]} {nodes[1]} {' '.join(value_tokens)}", tuple(warnings), False
            raise ValueError(f"{symbol.source.symbol_name}/{name}: 电流控制开关缺少控制源或模型")

        if lead == "D":
            if len(nodes) != 2:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 二极管必须有两个 SpiceOrder 引脚")
            if not value_text:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 二极管模型名缺失")
            if value_text.lower() not in available_models:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 二极管模型 {value_text} 未定义")
            suffix = f" {extra_parameters}" if extra_parameters else ""
            return f"{name} {nodes[0]} {nodes[1]} {value_text}{suffix}", tuple(warnings), False

        if lead in {"Q", "M", "J"}:
            valid_pin_counts = {"Q": {3, 4}, "M": {3, 4}, "J": {3}}[lead]
            if len(nodes) not in valid_pin_counts:
                raise ValueError(
                    f"{symbol.source.symbol_name}/{name}: {lead} 器件的 SpiceOrder 引脚数 {len(nodes)} 不合法"
                )
            if not value_text:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 半导体模型名缺失")
            if value_text.lower() not in available_models:
                raise ValueError(f"{symbol.source.symbol_name}/{name}: 半导体模型 {value_text} 未定义")
            if lead == "M":
                limited_nodes = list(nodes[:4])
                if len(limited_nodes) == 3 and value_text.lower() not in vdmos_models:
                    limited_nodes.append(limited_nodes[2])
                    warnings.append(
                        f"{symbol.source.symbol_name}/{name}: 三端标准 MOS 符号显式连接 body=source；"
                        "VDMOS 模型则保留 ngspice 原生三端形式。"
                    )
            else:
                limited_nodes = nodes[:4]
            suffix = f" {extra_parameters}" if extra_parameters else ""
            return f"{name} {' '.join(limited_nodes)} {value_text}{suffix}", tuple(warnings), False

        model_name_candidates = [
            candidate
            for candidate in (
                value_text,
                value2_text if _looks_like_model_token(value2_text) else "",
                spice_model_text if _looks_like_model_token(spice_model_text) else "",
            )
            if candidate
        ]
        requested_model_name = model_name_candidates[0] if model_name_candidates else ""
        if not requested_model_name:
            raise ValueError(f"{symbol.source.symbol_name}/{name}: 子电路名缺失")
        if requested_model_name.lower() not in available_subckts:
            raise ValueError(
                f"{symbol.source.symbol_name}/{name}: 子电路 {requested_model_name} 不存在或不能由当前 ngspice 可靠执行"
            )
        param_blobs = [blob for blob in (value2_text, spice_line_text, spice_line2_text) if _looks_like_param_blob(blob)]
        if not nodes:
            raise ValueError(f"{symbol.source.symbol_name}/{name}: 子电路实例没有引脚")
        return (
            f"{name} {' '.join(nodes)} {requested_model_name}"
            f"{(' ' + ' '.join(param_blobs)) if param_blobs else ''}",
            tuple(warnings),
            False,
        )

    def _validate_netlist(self, netlist_text: str, source_file: str) -> List[str]:
        try:
            document = self._parser.parse_content(netlist_text, source_file)
        except Exception as exc:
            return [str(exc)]
        return [str(item.message or "") for item in getattr(document, "parse_errors", []) if str(item.message or "")]

    def _resolve_symbol_definition(self, symbol_name: str) -> Optional[LtspiceSymbolDefinition]:
        return self._symbol_catalog.lookup(normalize_ltspice_symbol_key(symbol_name))



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


def _convert_ltspice_transient_shorthand(directive_text: str) -> str:
    """Translate LTspice-only ``.tran tstop [UIC]`` at the ASC boundary."""

    pieces = _strip_ltspice_inline_comment(
        str(directive_text or "").strip()
    ).split()
    if not pieces or pieces[0].casefold() != ".tran":
        return ""
    has_uic = len(pieces) >= 2 and pieces[-1].casefold() == "uic"
    body = pieces[1:-1] if has_uic else pieces[1:]
    if len(body) != 1:
        return ""
    stop_token = body[0]
    stop_value = parse_spice_number(stop_token)
    if stop_value is None or stop_value <= 0:
        return ""
    converted = (
        f".tran {format_spice_number(stop_value / 1000.0)} {stop_token}"
    )
    return f"{converted} uic" if has_uic else converted


def _strip_ltspice_inline_comment(text: str) -> str:
    quote = ""
    brace_depth = 0
    paren_depth = 0
    for index, character in enumerate(str(text or "")):
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "{":
            brace_depth += 1
            continue
        if character == "}" and brace_depth:
            brace_depth -= 1
            continue
        if character == "(":
            paren_depth += 1
            continue
        if character == ")" and paren_depth:
            paren_depth -= 1
            continue
        if (
            character == "/"
            and index + 1 < len(text)
            and text[index + 1] == "/"
            and brace_depth == 0
            and paren_depth == 0
        ):
            return text[:index]
        if (
            character in {";", "$"}
            and brace_depth == 0
            and paren_depth == 0
        ):
            return text[:index]
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


def _scan_model_catalog(content: str) -> Tuple[Set[str], Set[str]]:
    model_names: Set[str] = set()
    vdmos_models: Set[str] = set()
    inherited_models: List[Tuple[str, str]] = []
    pattern = re.compile(r"^\s*\.model\s+([^\s]+)\s+(.+)$", re.IGNORECASE)
    for line in str(content or "").splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        model_name = match.group(1).strip().lower()
        model_names.add(model_name)
        definition_tokens = match.group(2).strip().split()
        if not definition_tokens:
            continue
        type_index = 0
        if definition_tokens[0].lower().startswith("ako:"):
            base_model = definition_tokens[0].split(":", 1)[1].strip().lower()
            if len(definition_tokens) == 1 or definition_tokens[1].startswith("("):
                inherited_models.append((model_name, base_model))
                continue
            type_index = 1
        model_type = definition_tokens[type_index].split("(", 1)[0].strip().lower()
        if model_type == "vdmos":
            vdmos_models.add(model_name)
    unresolved = inherited_models
    while unresolved:
        remaining: List[Tuple[str, str]] = []
        changed = False
        for model_name, base_model in unresolved:
            if base_model not in vdmos_models:
                remaining.append((model_name, base_model))
                continue
            vdmos_models.add(model_name)
            changed = True
        if not changed:
            break
        unresolved = remaining
    return model_names, vdmos_models


__all__ = [
    "AscBatchConversionExecution",
    "AscConversionOutput",
    "LtspiceAscToCirTranscriber",
    "TranscribedAscNetlist",
]
