from __future__ import annotations

import functools
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from domain.simulation.spice.include_parser import IncludeParser
from domain.simulation.spice.models import (
    SourceSpan,
    SpiceComponent,
    SpiceDocument,
    SpiceEditableField,
    SpiceInclude,
    SpiceParseError,
    SpicePin,
    SpiceSubcircuit,
    SpiceToken,
    TokenSpan,
)
from domain.simulation.spice.numeric import is_spice_number
from domain.simulation.spice.primitive_resolver import SpicePrimitiveResolver
from domain.simulation.spice.source_closure import (
    SpiceSourceClosureGraph,
    SpiceSourceView,
)


@functools.lru_cache(maxsize=1)
def _load_bundled_model_variants() -> Dict[str, str]:
    """Scan every bundled device-model file under
    ``resources/models/cmp/`` exactly once per process and return a
    ``model_name → variant`` mapping (``nmos`` / ``pmos`` / ``npn`` /
    ``pnp``). The result is memoized because ``standard.mos`` alone
    defines hundreds of models and the schematic is rendered on every
    editor refresh.

    This catalog is presentation metadata only: it can select an NMOS/PMOS or
    NPN/PNP glyph for a familiar model name, but it never makes that model
    available to ngspice.  A runnable deck must define the model inline or use
    an explicit ``.include``/``.lib`` card.  Local ``.model`` definitions take
    precedence over this visual hint.

    Swallows every I/O error silently: if the library is missing or
    unreadable we simply fall back to the generic ``mos`` / ``bjt``
    symbol, which is no worse than before this feature existed.
    """
    result: Dict[str, str] = {}
    try:
        from resources.resource_loader import get_spice_cmp_dir
        cmp_dir = get_spice_cmp_dir()
    except Exception:
        return result
    if not cmp_dir.exists():
        return result
    for entry in sorted(cmp_dir.iterdir()):
        if not entry.is_file():
            continue
        try:
            text = entry.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        partial = SpiceParser._collect_model_variants(text.splitlines(keepends=True))
        for key, value in partial.items():
            # `setdefault` so that if two bundled files disagree on the
            # same model name, the first one wins deterministically
            # (iteration order on `iterdir()` is filesystem-defined but
            # stable per run for a given directory layout).
            result.setdefault(key.lower(), value)
    return result


_COMPONENT_SYMBOL_KINDS: Dict[str, str] = {
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "D": "diode",
    "V": "voltage_source",
    "I": "current_source",
    "Q": "bjt",
    "M": "mos",
    "J": "jfet",
    "Z": "mesfet",
    "K": "mutual_inductor",
    "O": "transmission_line",
    "Y": "transmission_line",
    "U": "distributed_rc_line",
    "X": "subckt_block",
    "E": "controlled_source",
    "F": "controlled_source",
    "G": "controlled_source",
    "H": "controlled_source",
    "B": "controlled_source",
    "S": "switch",
    "W": "switch",
    "T": "transmission_line",
}

_READONLY_COMPLEX_EXPRESSION = "字段由复杂表达式描述，首版保持只读"
_READONLY_UNSUPPORTED_FIELD = "该字段当前未提供语义等价写回能力"


class SpiceParser:
    def __init__(self) -> None:
        self._include_parser = IncludeParser()
        self._primitive_resolver = SpicePrimitiveResolver()

    def parse_file(self, file_path: str) -> SpiceDocument:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        return self.parse_content(content, str(path))

    def parse_content(self, content: str, source_file: str) -> SpiceDocument:
        lines = content.splitlines(keepends=True)
        local_variants = self._collect_model_variants(lines[1:])
        bundled_variants = _load_bundled_model_variants()
        model_variants: Dict[str, str] = {**bundled_variants, **local_variants}

        document = self._parse_content(
            content,
            source_file,
            model_variants=model_variants,
            skip_title=True,
        )
        self._primitive_resolver.apply(document)
        return document

    def parse_source_graph(
        self,
        source_graph: SpiceSourceClosureGraph,
    ) -> SpiceDocument:
        """Parse one already-collected effective SPICE source graph.

        The main deck is parsed from its exact blob so its token offsets remain
        valid for source patching. Dependency semantics come exclusively from
        ``active_views``; physical-only blobs (for example an include inside an
        unselected library section) can affect provenance and file watching but
        never leak into the schematic model.
        """

        model_variants, model_conflicts = (
            self._collect_source_graph_model_variants(source_graph.active_views)
        )
        main_blob = source_graph.main_blob
        document = self._parse_content(
            main_blob.source_text,
            main_blob.key,
            model_variants=model_variants,
            skip_title=True,
        )

        for source_view in source_graph.active_views:
            if source_view.is_main_deck:
                continue
            dependency_document = self._parse_content(
                self._reconstruct_active_view(source_view),
                source_view.key,
                model_variants=model_variants,
                skip_title=False,
            )
            self._make_dependency_fields_readonly(dependency_document)
            document.components.extend(dependency_document.components)
            document.includes.extend(dependency_document.includes)
            document.subcircuits.extend(dependency_document.subcircuits)
            document.parse_errors.extend(dependency_document.parse_errors)

        subcircuit_conflicts = self._find_subcircuit_conflicts(
            document.subcircuits
        )
        for model_name, locations in sorted(model_conflicts.items()):
            document.add_parse_error(
                SpiceParseError(
                    message=(
                        f"模型 {model_name} 在 active source closure 中重复定义："
                        + "，".join(locations)
                    ),
                    source_file=main_blob.key,
                    line_text="",
                )
            )
        for subcircuit_name, locations in sorted(subcircuit_conflicts.items()):
            document.add_parse_error(
                SpiceParseError(
                    message=(
                        f"子电路 {subcircuit_name} 在 active source closure 中重复定义："
                        + "，".join(locations)
                    ),
                    source_file=main_blob.key,
                    line_text="",
                )
            )

        self._primitive_resolver.apply(
            document,
            excluded_subcircuit_names=subcircuit_conflicts,
        )
        return document

    def _parse_content(
        self,
        content: str,
        source_file: str,
        *,
        model_variants: Dict[str, str],
        skip_title: bool,
    ) -> SpiceDocument:
        document = SpiceDocument(source_file=str(source_file or ""))
        subcircuit_stack: List[SpiceSubcircuit] = []
        lines = content.splitlines(keepends=True)
        absolute_offset = 0

        in_control = False
        for line_index, raw_line in enumerate(lines):
            line_text = raw_line.rstrip("\r\n")
            stripped = line_text.strip()
            line_span = self._make_line_span(line_index, line_text, absolute_offset)

            if skip_title and line_index == 0:
                absolute_offset += len(raw_line)
                continue

            if not stripped or stripped.startswith(("*", ";", "$", "//")):
                absolute_offset += len(raw_line)
                continue

            command = self._dot_command_name(line_text)
            if command == ".control":
                in_control = True
                absolute_offset += len(raw_line)
                continue
            if command == ".endc":
                in_control = False
                absolute_offset += len(raw_line)
                continue
            if in_control:
                absolute_offset += len(raw_line)
                continue
            if command == ".end":
                if subcircuit_stack:
                    document.add_parse_error(
                        SpiceParseError(
                            message=f".end 前子电路 {subcircuit_stack[-1].name} 未以 .ends 结束",
                            source_file=str(source_file or ""),
                            source_span=line_span,
                            line_text=line_text,
                        )
                    )
                break

            include = self._include_parser.parse_line(line_text, line_index + 1)
            if include is not None:
                document.add_include(
                    SpiceInclude(
                        path=include.raw_path,
                        source_file=str(source_file or ""),
                        source_span=line_span,
                    )
                )
                absolute_offset += len(raw_line)
                continue

            if command == ".subckt":
                subcircuit = self._parse_subcircuit_header(
                    line_text,
                    source_file,
                    [item.name for item in subcircuit_stack],
                    line_span,
                )
                if subcircuit is not None:
                    subcircuit_stack.append(subcircuit)
                    document.add_subcircuit(subcircuit)
                else:
                    document.add_parse_error(
                        SpiceParseError(
                            message=".subckt 缺少子电路名称",
                            source_file=str(source_file or ""),
                            source_span=line_span,
                            line_text=line_text,
                        )
                    )
                absolute_offset += len(raw_line)
                continue

            if command == ".ends":
                if subcircuit_stack:
                    # ngspice accepts an optional name on .ends but explicitly
                    # does not check it against the active .subckt name.
                    subcircuit_stack.pop()
                else:
                    document.add_parse_error(
                        SpiceParseError(
                            message="孤立的 .ends 没有对应 .subckt",
                            source_file=str(source_file or ""),
                            source_span=line_span,
                            line_text=line_text,
                        )
                    )
                absolute_offset += len(raw_line)
                continue

            if stripped.startswith(".") or stripped.startswith("+"):
                absolute_offset += len(raw_line)
                continue

            component = self._parse_component_line(
                line_text=line_text,
                source_file=str(source_file or ""),
                scope_path=[item.name for item in subcircuit_stack],
                line_index=line_index,
                absolute_offset=absolute_offset,
                model_variants=model_variants,
            )
            if component is not None:
                if subcircuit_stack:
                    subcircuit_stack[-1].components.append(component)
                else:
                    document.add_component(component)
            elif stripped:
                document.add_parse_error(
                    SpiceParseError(
                        message="未能解析的实例行",
                        source_file=str(source_file or ""),
                        source_span=line_span,
                        line_text=line_text,
                    )
                )

            absolute_offset += len(raw_line)

        if subcircuit_stack and not any(".end 前子电路" in error.message for error in document.parse_errors):
            for subcircuit in subcircuit_stack:
                document.add_parse_error(
                    SpiceParseError(
                        message=f"子电路 {subcircuit.name} 缺少 .ends",
                        source_file=str(source_file or ""),
                        source_span=subcircuit.source_span,
                        line_text="",
                    )
                )

        return document

    def _collect_source_graph_model_variants(
        self,
        source_views: Sequence[SpiceSourceView],
    ) -> Tuple[Dict[str, str], Dict[str, Tuple[str, ...]]]:
        semantic_lines: List[str] = []
        definition_locations: Dict[str, List[str]] = {}
        for source_view in source_views:
            for source_line in source_view.lines:
                semantic_lines.append(source_line.text)
                stripped = source_line.text.strip()
                if not stripped.lower().startswith(".model"):
                    continue
                pieces = stripped.split()
                if len(pieces) < 2:
                    continue
                model_name = pieces[1].lower()
                section_suffix = (
                    f"[{source_view.library_section}]"
                    if source_view.library_section
                    else ""
                )
                definition_locations.setdefault(model_name, []).append(
                    f"{source_view.key}{section_suffix}:{source_line.line_number}"
                )

        explicit_names = set(definition_locations)
        explicit_variants = self._collect_model_variants(semantic_lines)
        conflicts = {
            model_name: tuple(locations)
            for model_name, locations in definition_locations.items()
            if len(locations) > 1
        }
        variants = {
            model_name: variant
            for model_name, variant in _load_bundled_model_variants().items()
            if model_name not in explicit_names
        }
        variants.update(
            {
                model_name: variant
                for model_name, variant in explicit_variants.items()
                if model_name not in conflicts
            }
        )
        return variants, conflicts

    @staticmethod
    def _reconstruct_active_view(source_view: SpiceSourceView) -> str:
        if not source_view.lines:
            return ""
        physical_line_count = max(line.line_number for line in source_view.lines)
        lines = ["\n"] * physical_line_count
        for source_line in source_view.lines:
            lines[source_line.line_number - 1] = f"{source_line.text}\n"
        return "".join(lines)

    @staticmethod
    def _make_dependency_fields_readonly(document: SpiceDocument) -> None:
        readonly_reason = "依赖源文件中的字段不能从主电路历史结果直接写回"
        components = list(document.components)
        for subcircuit in document.subcircuits:
            components.extend(subcircuit.components)
        for component in components:
            for field in component.editable_fields:
                field.editable = False
                field.readonly_reason = readonly_reason

    @staticmethod
    def _find_subcircuit_conflicts(
        subcircuits: Sequence[SpiceSubcircuit],
    ) -> Dict[str, Tuple[str, ...]]:
        locations: Dict[str, List[str]] = {}
        for subcircuit in subcircuits:
            name = str(subcircuit.name or "").strip().lower()
            if not name:
                continue
            line_number = (
                subcircuit.source_span.line_index + 1
                if subcircuit.source_span is not None
                else 0
            )
            locations.setdefault(name, []).append(
                f"{subcircuit.source_file}:{line_number}"
            )
        return {
            name: tuple(items)
            for name, items in locations.items()
            if len(items) > 1
        }

    def _parse_subcircuit_header(
        self,
        line_text: str,
        source_file: str,
        scope_path: List[str],
        line_span: SourceSpan,
    ) -> Optional[SpiceSubcircuit]:
        tokens = self._tokenize_line(line_text, line_span.line_index, line_span.absolute_start)
        if len(tokens) < 2:
            return None
        name = tokens[1].text
        port_names = []
        for token in tokens[2:]:
            normalized = token.text.strip().lower()
            if normalized == "params:" or normalized.startswith("params:") or "=" in token.text:
                break
            port_names.append(token.text)
        return SpiceSubcircuit(
            name=name,
            port_names=port_names,
            scope_path=list(scope_path),
            source_file=source_file,
            source_span=line_span,
        )

    def _parse_component_line(
        self,
        *,
        line_text: str,
        source_file: str,
        scope_path: List[str],
        line_index: int,
        absolute_offset: int,
        model_variants: Dict[str, str],
    ) -> Optional[SpiceComponent]:
        source_span = self._make_line_span(line_index, line_text, absolute_offset)
        tokens = self._tokenize_line(line_text, line_index, absolute_offset)
        if len(tokens) < 2:
            return None

        instance_name = tokens[0].text
        prefix = instance_name[0].upper()
        symbol_kind = _COMPONENT_SYMBOL_KINDS.get(prefix, "unknown")
        descriptor = self._describe_component(prefix, tokens, model_variants)
        node_tokens = descriptor["node_tokens"]
        node_ids = [_normalize_node_id(token.text) for token in node_tokens]
        pin_specs: List[Tuple[str, str]] = descriptor["pin_specs"]
        if len(pin_specs) != len(node_tokens):
            pin_specs = [(f"pin_{index + 1}", f"pin_{index + 1}") for index in range(len(node_tokens))]
        pin_roles: Dict[str, str] = {name: role for name, role in pin_specs}
        pins = [
            SpicePin(
                name=pin_specs[index][0],
                node_id=node_ids[index],
                role=pin_specs[index][1],
            )
            for index, token in enumerate(node_tokens)
        ]
        editable_fields = self._build_editable_fields(prefix, tokens, line_text, line_index, absolute_offset)

        component = SpiceComponent(
            id=self._make_component_id(source_file, scope_path, instance_name, source_span.absolute_start),
            instance_name=instance_name,
            kind=prefix,
            symbol_kind=symbol_kind,
            symbol_variant=descriptor["symbol_variant"],
            source_file=source_file,
            scope_path=list(scope_path),
            node_ids=node_ids,
            pins=pins,
            editable_fields=editable_fields,
            source_span=source_span,
            token_spans={field.field_key: field.token_span for field in editable_fields if field.token_span is not None},
            pin_roles=pin_roles,
            polarity_marks=descriptor["polarity_marks"],
            port_order=descriptor["port_order"],
            render_hints=descriptor["render_hints"],
            model_name=descriptor["model_name"],
            subckt_name=descriptor["model_name"] if prefix == "X" else "",
            resolved_model_name=descriptor["model_name"],
            raw_line=line_text,
        )
        return component

    @staticmethod
    def _collect_model_variants(lines: List[str]) -> Dict[str, str]:
        """Scan every `.model` card once and return a mapping of model
        name → canonical variant tag (``nmos`` / ``pmos`` / ``npn`` /
        ``pnp``). Anything else (diode models, custom macros) is
        intentionally excluded so callers can treat a missing entry as
        "no transistor-variant info available" and fall back to a
        neutral symbol.

        A `.model` card in SPICE looks like::

            .model <name> <TYPE> (<params...>)

        with the type token optionally hugging the opening parenthesis
        (``PMOS(`` is as valid as ``PMOS (``). We split whitespace and
        strip a trailing ``(`` off the type token to cover both forms;
        continuation lines (``+ ...``) only carry parameters and are
        ignored because the device type is always on the header line.

        Two device-type dialects are recognized:

        * **Standard SPICE**: the type token itself is ``NMOS`` /
          ``PMOS`` / ``NPN`` / ``PNP``.
        * **LTspice VDMOS**: the type token is ``VDMOS`` and the
          parameter list carries either ``pchan`` (→ PMOS) or no
          channel keyword (→ NMOS by default). This is the format
          used by the bundled ``resources/models/cmp/standard.mos``
          file, so supporting it is what lets parts like BSS84 /
          BSS123 resolve to the right schematic glyph.
        """
        variants: Dict[str, str] = {}
        # Canonical device-type → variant tag. `NJF` / `PJF` are the
        # SPICE standard type tokens for n-channel and p-channel JFETs.
        type_to_variant = {
            "NMOS": "nmos",
            "PMOS": "pmos",
            "NPN": "npn",
            "PNP": "pnp",
            "NJF": "njf",
            "PJF": "pjf",
            "NMF": "nmesfet",
            "PMF": "pmesfet",
        }
        logical_model_lines: List[str] = []
        current_model = ""
        for raw_line in lines:
            stripped = raw_line.strip()
            if stripped.lower().startswith(".model"):
                if current_model:
                    logical_model_lines.append(current_model)
                current_model = stripped
                continue
            if current_model and stripped.startswith("+"):
                current_model += " " + stripped[1:].strip()
                continue
            if current_model:
                logical_model_lines.append(current_model)
                current_model = ""
        if current_model:
            logical_model_lines.append(current_model)

        pending_aliases: List[Tuple[str, str]] = []
        for stripped in logical_model_lines:
            if not stripped:
                continue
            pieces = stripped.split()
            if len(pieces) < 3:
                continue
            model_name = pieces[1].lower()
            # SPICE "AKO" (A Kind Of) inheritance lets one model extend
            # another: `.model NEW ako:BASE TYPE (override params)`. The
            # real device-type token therefore lives in pieces[3] when
            # pieces[2] starts with `ako:`; if the TYPE field is missing
            # (`.model NEW ako:BASE (...)`) we currently leave NEW
            # unresolved — `standard.bjt` always includes the explicit
            # type, and any unresolved AKO simply falls back to the
            # neutral `"bjt"` / `"mos"` / `"jfet"` symbol.
            type_piece_index = 2
            if pieces[type_piece_index].lower().startswith("ako:"):
                base_model = pieces[type_piece_index].split(":", 1)[1].strip().lower()
                if len(pieces) <= 3 or pieces[3].startswith("("):
                    pending_aliases.append((model_name, base_model))
                    continue
                type_piece_index = 3
            # Split on "(" so we canonicalize three spellings of the type
            # token in one step:
            #   "PMOS"          -> ["PMOS"]
            #   "PMOS("         -> ["PMOS", ""]
            #   "PMOS(LEVEL=1)" -> ["PMOS", "LEVEL=1)"]
            # The first element is always the pure type name, which is
            # what we want to look up in `type_to_variant`.
            raw_type = pieces[type_piece_index].split("(", 1)[0].upper()
            variant = type_to_variant.get(raw_type)
            if variant is not None:
                variants[model_name] = variant
                continue
            if raw_type == "VDMOS":
                # LTspice VDMOS: default is N-channel, becomes P-channel
                # only when the parameter list contains the `pchan`
                # keyword (as a whole word). Case-insensitive to tolerate
                # `PCHAN`, `Pchan`, etc. Inspect the rest of the line
                # (`pieces[type_piece_index:]`) because `pchan` may
                # appear on the same line as the type token or on a
                # continuation — but continuation lines are already
                # ignored so we only see the header here.
                rest_text = " ".join(pieces[type_piece_index:]).lower()
                if re.search(r"\bpchan\b", rest_text):
                    variants[model_name] = "pmos"
                else:
                    variants[model_name] = "nmos"
        unresolved = pending_aliases
        while unresolved:
            next_unresolved: List[Tuple[str, str]] = []
            changed = False
            for model_name, base_model in unresolved:
                inherited = variants.get(base_model)
                if inherited is None:
                    next_unresolved.append((model_name, base_model))
                    continue
                variants[model_name] = inherited
                changed = True
            if not changed:
                break
            unresolved = next_unresolved
        return variants

    def _describe_component(
        self,
        prefix: str,
        tokens: List[SpiceToken],
        model_variants: Dict[str, str],
    ) -> Dict[str, object]:
        if prefix in {"R", "C", "L"}:
            node_tokens = tokens[1:3]
            pin_specs = [
                ("terminal_a", "terminal_a"),
                ("terminal_b", "terminal_b"),
            ] if len(node_tokens) == 2 else []
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "two_terminal",
                "polarity_marks": {},
                "port_order": ["terminal_a", "terminal_b"],
                "render_hints": {"orientation": "horizontal"},
                "model_name": "",
            }

        if prefix == "D":
            node_tokens = tokens[1:3]
            pin_specs = [
                ("anode", "anode"),
                ("cathode", "cathode"),
            ] if len(node_tokens) == 2 else []
            model_name = tokens[3].text if len(tokens) > 3 else ""
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "two_terminal_polarized",
                "polarity_marks": {"anode": "+", "cathode": "-"},
                "port_order": ["anode", "cathode"],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        if prefix in {"V", "I"}:
            node_tokens = tokens[1:3]
            pin_specs = [
                ("positive", "positive"),
                ("negative", "negative"),
            ] if len(node_tokens) == 2 else []
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "source",
                "polarity_marks": {"positive": "+", "negative": "-"},
                "port_order": ["positive", "negative"],
                "render_hints": {"orientation": "vertical"},
                "model_name": "",
            }

        if prefix == "Q":
            model_index = self._resolve_bjt_model_token_index(tokens)
            node_tokens = tokens[1:model_index] if model_index is not None else tokens[1:4]
            if len(node_tokens) == 3:
                pin_specs = [
                    ("collector", "collector"),
                    ("base", "base"),
                    ("emitter", "emitter"),
                ]
            elif len(node_tokens) == 4:
                pin_specs = [
                    ("collector", "collector"),
                    ("base", "base"),
                    ("emitter", "emitter"),
                    ("substrate", "substrate"),
                ]
            else:
                pin_specs = []
            model_name = tokens[model_index].text if model_index is not None else ""
            # Resolve the BJT channel variant from the .model lookup
            # built in pass 1. Falls back to the generic "bjt" marker
            # when no .model card was found (e.g. user-provided netlist
            # fragments without models), so downstream renderers can
            # still pick a neutral default.
            variant = model_variants.get(model_name.lower(), "")
            if variant not in ("npn", "pnp"):
                variant = "bjt"
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": variant,
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "right"},
                "model_name": model_name,
            }

        if prefix in {"J", "Z"}:
            # SPICE JFET card: `Jxxx D G S <model>` (3 nodes + model name).
            # Electrode order is drain / gate / source, identical to the
            # first three positions of a MOSFET but without the body
            # terminal, which is why we can reuse the same schematic
            # layout primitives downstream.
            node_tokens = tokens[1:4]
            pin_specs = [
                ("drain", "drain"),
                ("gate", "gate"),
                ("source", "source"),
            ] if len(node_tokens) == 3 else []
            model_name = tokens[4].text if len(tokens) > 4 else ""
            # Resolve the JFET channel variant from the .model lookup.
            # Falls back to the generic "jfet" marker when no .model
            # card was found so the renderer can pick a neutral glyph.
            variant = model_variants.get(model_name.lower(), "")
            if prefix == "Z":
                if variant not in ("nmesfet", "pmesfet"):
                    variant = "mesfet"
            elif variant not in ("njf", "pjf"):
                variant = "jfet"
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": variant,
                "polarity_marks": {},
                "port_order": ["drain", "gate", "source"],
                "render_hints": {"orientation": "right"},
                "model_name": model_name,
            }

        if prefix == "M":
            model_index = self._resolve_mos_model_token_index(tokens)
            node_tokens = tokens[1:model_index] if model_index is not None else tokens[1:5]
            if len(node_tokens) == 3:
                pin_specs = [
                    ("drain", "drain"),
                    ("gate", "gate"),
                    ("source", "source"),
                ]
            elif len(node_tokens) == 4:
                pin_specs = [
                    ("drain", "drain"),
                    ("gate", "gate"),
                    ("source", "source"),
                    ("body", "body"),
                ]
            else:
                pin_specs = []
            model_name = tokens[model_index].text if model_index is not None else ""
            # Same pattern as Q: resolve NMOS vs PMOS from the .model
            # lookup. Falls back to "mos" when no .model card was
            # found so callers can still render a neutral default.
            variant = model_variants.get(model_name.lower(), "")
            if variant not in ("nmos", "pmos"):
                variant = "mos"
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": variant,
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "right"},
                "model_name": model_name,
            }

        if prefix == "X" and len(tokens) >= 3:
            model_index = self._resolve_subckt_model_token_index(tokens)
            if model_index is None:
                node_tokens = tokens[1:-1]
                model_name = tokens[-1].text
            else:
                node_tokens = tokens[1:model_index]
                model_name = tokens[model_index].text
            pin_specs = [(f"port_{index + 1}", f"port_{index + 1}") for index in range(len(node_tokens))]
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "block",
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        if prefix == "K":
            # K cards reference inductor *instance names*, not electrical
            # nodes.  Treating L1/L2 as nets created fictitious connectivity
            # in the schematic.
            return {
                "node_tokens": [],
                "pin_specs": [],
                "symbol_variant": "mutual_inductance",
                "polarity_marks": {},
                "port_order": [],
                "render_hints": {"orientation": "horizontal"},
                "model_name": "",
            }

        if prefix in {"T", "O", "Y"}:
            node_tokens = tokens[1:5]
            pin_specs = [
                ("port_1_positive", "port_1_positive"),
                ("port_1_negative", "port_1_negative"),
                ("port_2_positive", "port_2_positive"),
                ("port_2_negative", "port_2_negative"),
            ] if len(node_tokens) == 4 else []
            model_name = tokens[5].text if prefix in {"O", "Y"} and len(tokens) > 5 else ""
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "lossless" if prefix == "T" else "lossy",
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        if prefix == "U":
            node_tokens = tokens[1:4]
            pin_specs = [
                ("terminal_1", "terminal_1"),
                ("terminal_2", "terminal_2"),
                ("capacitance_reference", "capacitance_reference"),
            ] if len(node_tokens) == 3 else []
            model_name = tokens[4].text if len(tokens) > 4 else ""
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "urc",
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        if prefix in {"E", "G"}:
            # Linear VCVS/VCCS cards have two output and two controlling
            # nodes.  Behavioral/POLY variants cannot be represented by the
            # simple four-pin glyph without lying about their connectivity,
            # so only the unambiguous linear form receives semantic pins.
            control_form = tokens[3].text.lower().split("=", 1)[0] if len(tokens) > 3 else ""
            is_behavioral = control_form in {"value", "vol", "cur", "table", "laplace"} or control_form.startswith("poly(")
            node_tokens = tokens[1:5] if len(tokens) >= 6 and not is_behavioral else tokens[1:3]
            pin_specs = (
                [
                    ("output_positive", "output_positive"),
                    ("output_negative", "output_negative"),
                    ("control_positive", "control_positive"),
                    ("control_negative", "control_negative"),
                ]
                if len(node_tokens) == 4
                else [("output_positive", "output_positive"), ("output_negative", "output_negative")]
            )
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "voltage_controlled",
                "polarity_marks": {"output_positive": "+", "output_negative": "-"},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": "",
            }

        if prefix in {"F", "H", "B"}:
            node_tokens = tokens[1:3]
            pin_specs = [
                ("output_positive", "output_positive"),
                ("output_negative", "output_negative"),
            ] if len(node_tokens) == 2 else []
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "current_controlled" if prefix in {"F", "H"} else "behavioral",
                "polarity_marks": {"output_positive": "+", "output_negative": "-"},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": "",
            }

        if prefix == "S":
            node_tokens = tokens[1:5]
            pin_specs = [
                ("terminal_positive", "terminal_positive"),
                ("terminal_negative", "terminal_negative"),
                ("control_positive", "control_positive"),
                ("control_negative", "control_negative"),
            ] if len(node_tokens) == 4 else []
            model_name = tokens[5].text if len(tokens) > 5 else ""
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "voltage_controlled",
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        if prefix == "W":
            node_tokens = tokens[1:3]
            pin_specs = [
                ("terminal_positive", "terminal_positive"),
                ("terminal_negative", "terminal_negative"),
            ] if len(node_tokens) == 2 else []
            model_name = tokens[4].text if len(tokens) > 4 else ""
            return {
                "node_tokens": node_tokens,
                "pin_specs": pin_specs,
                "symbol_variant": "current_controlled",
                "polarity_marks": {},
                "port_order": [name for name, _ in pin_specs],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        node_tokens = tokens[1:-1] if len(tokens) > 3 else tokens[1:]
        pin_specs = [(f"pin_{index + 1}", f"pin_{index + 1}") for index in range(len(node_tokens))]
        model_name = tokens[-1].text if len(tokens) > 2 else ""
        return {
            "node_tokens": node_tokens,
            "pin_specs": pin_specs,
            "symbol_variant": "generic",
            "polarity_marks": {},
            "port_order": [name for name, _ in pin_specs],
            "render_hints": {"orientation": "horizontal"},
            "model_name": model_name,
        }

    def _resolve_subckt_model_token_index(self, tokens: List[SpiceToken]) -> Optional[int]:
        for index in range(2, len(tokens)):
            normalized = tokens[index].text.strip().lower()
            if normalized == "params:" or normalized.startswith("params:") or "=" in tokens[index].text:
                return index - 1 if index > 1 else None
        return len(tokens) - 1 if len(tokens) > 2 else None

    def _resolve_bjt_model_token_index(
        self,
        tokens: List[SpiceToken],
    ) -> Optional[int]:
        if len(tokens) <= 4:
            return None
        if len(tokens) == 5:
            return 4
        # With six or more tokens, position 5 is either the model of a
        # four-terminal BJT or the first parameter of a three-terminal BJT.
        # This structural distinction also works for models coming from user
        # include files, whose names are intentionally not guessed from the
        # bundled registry.
        return 4 if _looks_like_bjt_parameter(tokens[5].text) else 5

    def _resolve_mos_model_token_index(
        self,
        tokens: List[SpiceToken],
    ) -> Optional[int]:
        if len(tokens) <= 4:
            return None
        # Standard ngspice MOS cards always have D/G/S/B followed by the model
        # name.  The shorter index is retained only to visualize an invalid
        # three-node card truthfully; runtime normalization no longer repairs
        # it by silently tying body to source.
        if len(tokens) == 5 or (len(tokens) > 5 and _looks_like_instance_parameter(tokens[5].text)):
            return 4
        return 5

    def _build_editable_fields(
        self,
        prefix: str,
        tokens: List[SpiceToken],
        line_text: str,
        line_index: int,
        absolute_offset: int,
    ) -> List[SpiceEditableField]:
        if prefix in {"R", "C", "L"} and len(tokens) >= 4:
            return [self._build_value_field(tokens[3], line_text, line_index, absolute_offset)]

        if prefix in {"V", "I"}:
            if len(tokens) >= 5 and tokens[3].text.upper() == "DC":
                return [self._build_value_field(tokens[4], line_text, line_index, absolute_offset)]
            if len(tokens) >= 4:
                return [self._build_value_field(tokens[3], line_text, line_index, absolute_offset)]

        return []

    def _build_value_field(
        self,
        token: SpiceToken,
        line_text: str,
        line_index: int,
        absolute_offset: int,
    ) -> SpiceEditableField:
        text = token.text
        editable = self._is_direct_editable_value(text)
        readonly_reason = "" if editable else self._readonly_reason_for_value(text)
        source_span = SourceSpan(
            line_index=line_index,
            column_start=token.span.column_start,
            column_end=token.span.column_end,
            absolute_start=token.span.absolute_start,
            absolute_end=token.span.absolute_end,
        )
        return SpiceEditableField(
            field_key="value",
            label="数值",
            raw_text=text,
            display_text=text,
            editable=editable,
            readonly_reason=readonly_reason,
            value_kind="literal",
            token_span=token.span,
            source_span=source_span,
        )

    def _readonly_reason_for_value(self, text: str) -> str:
        if any(marker in text for marker in ("{", "}", "(", ")")):
            return _READONLY_COMPLEX_EXPRESSION
        return _READONLY_UNSUPPORTED_FIELD

    def _is_direct_editable_value(self, text: str) -> bool:
        return is_spice_number(text)

    def _tokenize_line(self, line_text: str, line_index: int, absolute_offset: int) -> List[SpiceToken]:
        tokens: List[SpiceToken] = []
        code_text = line_text[:self._inline_comment_start(line_text)]
        for token_index, match in enumerate(re.finditer(r"\S+", code_text)):
            start = match.start()
            end = match.end()
            tokens.append(
                SpiceToken(
                    text=match.group(0),
                    span=TokenSpan(
                        token_index=token_index,
                        column_start=start,
                        column_end=end,
                        absolute_start=absolute_offset + start,
                        absolute_end=absolute_offset + end,
                    ),
                )
            )
        return tokens

    @staticmethod
    def _dot_command_name(line_text: str) -> str:
        stripped = line_text[:SpiceParser._inline_comment_start(line_text)].strip()
        if not stripped.startswith("."):
            return ""
        return stripped.split(None, 1)[0].lower()

    @staticmethod
    def _inline_comment_start(line_text: str) -> int:
        quote = ""
        brace_depth = 0
        paren_depth = 0
        for index, character in enumerate(str(line_text or "")):
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
                and index + 1 < len(line_text)
                and line_text[index + 1] == "/"
                and brace_depth == 0
                and paren_depth == 0
            ):
                return index
            if character in {";", "$"} and brace_depth == 0 and paren_depth == 0:
                return index
        return len(str(line_text or ""))

    def _make_line_span(self, line_index: int, line_text: str, absolute_offset: int) -> SourceSpan:
        return SourceSpan(
            line_index=line_index,
            column_start=0,
            column_end=len(line_text),
            absolute_start=absolute_offset,
            absolute_end=absolute_offset + len(line_text),
        )

    def _make_component_id(
        self,
        source_file: str,
        scope_path: List[str],
        instance_name: str,
        absolute_start: int,
    ) -> str:
        seed = "|".join([
            str(source_file or ""),
            "/".join(scope_path),
            instance_name,
            str(absolute_start),
        ])
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _normalize_node_id(value: str) -> str:
    text = str(value or "").strip().lower()
    # Batch-mode ngspice node identifiers are case-insensitive and GND aliases
    # node 0.  A case-sensitive schematic would otherwise display electrically
    # identical nodes as separate nets and fail to match lowercase result
    # vector names returned by ngspice.
    return "0" if text == "gnd" else text


def _looks_like_bjt_parameter(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if "=" in text or is_spice_number(text):
        return True
    return text in {"area", "off", "ic", "temp", "dtemp", "m"}


def _looks_like_instance_parameter(value: str) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and ("=" in text or text in {"off", "ic", "temp", "dtemp", "m"})


__all__ = ["SpiceParser"]
