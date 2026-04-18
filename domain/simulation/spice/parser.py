from __future__ import annotations

import functools
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

from domain.dependency.scanner.include_parser import IncludeParser
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


@functools.lru_cache(maxsize=1)
def _load_bundled_model_variants() -> Dict[str, str]:
    """Scan every bundled device-model file under
    ``resources/models/cmp/`` exactly once per process and return a
    ``model_name → variant`` mapping (``nmos`` / ``pmos`` / ``npn`` /
    ``pnp``). The result is memoized because ``standard.mos`` alone
    defines hundreds of models and the schematic is rendered on every
    editor refresh.

    Users rarely put ``.model`` cards into their ``.cir`` files —
    ``SpiceExecutor._inject_model_libraries`` pulls the definitions
    from the bundled library at simulation time. For the schematic to
    know NMOS vs PMOS at *render* time (before simulation runs) we
    have to consult the same library ourselves. Local ``.model``
    cards in the user's ``.cir`` always take precedence over the
    bundled defaults — see the merge in ``parse_content``.

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
    for entry in cmp_dir.iterdir():
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
            result.setdefault(key, value)
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
    "U": "opamp",
    "X": "subckt_block",
    "E": "controlled_source",
    "F": "controlled_source",
    "G": "controlled_source",
    "H": "controlled_source",
}

_READONLY_COMPLEX_EXPRESSION = "字段由复杂表达式描述，首版保持只读"
_READONLY_UNSUPPORTED_FIELD = "该字段当前未提供语义等价写回能力"


class SpiceParser:
    def __init__(self) -> None:
        self._include_parser = IncludeParser()

    def parse_file(self, file_path: str) -> SpiceDocument:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        return self.parse_content(content, str(path))

    def parse_content(self, content: str, source_file: str) -> SpiceDocument:
        document = SpiceDocument(source_file=str(source_file or ""))
        subcircuit_stack: List[SpiceSubcircuit] = []
        lines = content.splitlines(keepends=True)
        absolute_offset = 0

        # Pass 1: pre-scan every `.model` card so we know, for each
        # model name referenced by a Q / M component, whether that model
        # represents an N-channel or P-channel / NPN or PNP device. This
        # information is the only trustworthy source for the schematic's
        # NMOS vs PMOS (and NPN vs PNP) rendering choice — ngspice
        # itself reads the same .model card at simulation time, so by
        # mirroring that lookup here we keep schematic and simulator in
        # lock-step without asking the user to hint anything.
        #
        # Local `.model` cards in the current file take precedence over
        # the bundled standard-library defaults so users can always
        # override a bundled part by redefining it inline.
        local_variants = self._collect_model_variants(lines)
        bundled_variants = _load_bundled_model_variants()
        model_variants: Dict[str, str] = {**bundled_variants, **local_variants}

        for line_index, raw_line in enumerate(lines):
            line_text = raw_line.rstrip("\r\n")
            stripped = line_text.strip()
            line_span = self._make_line_span(line_index, line_text, absolute_offset)

            if not stripped or stripped.startswith("*") or stripped.startswith(";"):
                absolute_offset += len(raw_line)
                continue

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

            lowered = stripped.lower()
            if lowered.startswith(".subckt"):
                subcircuit = self._parse_subcircuit_header(line_text, source_file, line_span)
                if subcircuit is not None:
                    subcircuit_stack.append(subcircuit)
                    document.add_subcircuit(subcircuit)
                absolute_offset += len(raw_line)
                continue

            if lowered.startswith(".ends"):
                if subcircuit_stack:
                    subcircuit_stack.pop()
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

        return document

    def _parse_subcircuit_header(
        self,
        line_text: str,
        source_file: str,
        line_span: SourceSpan,
    ) -> Optional[SpiceSubcircuit]:
        tokens = self._tokenize_line(line_text, line_span.line_index, line_span.absolute_start)
        if len(tokens) < 2:
            return None
        name = tokens[1].text
        port_names = [token.text for token in tokens[2:]]
        return SpiceSubcircuit(
            name=name,
            port_names=port_names,
            scope_path=[name],
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
        node_ids = [token.text for token in node_tokens]
        pin_roles: Dict[str, str] = descriptor["pin_roles"]
        pins = [
            SpicePin(
                name=token.text,
                node_id=token.text,
                role=pin_roles.get(token.text, f"pin_{index + 1}"),
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
        }
        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if not lowered.startswith(".model"):
                continue
            pieces = stripped.split()
            if len(pieces) < 3:
                continue
            model_name = pieces[1]
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
                if len(pieces) <= 3:
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
        return variants

    def _describe_component(
        self,
        prefix: str,
        tokens: List[SpiceToken],
        model_variants: Dict[str, str],
    ) -> Dict[str, object]:
        if prefix in {"R", "C", "L"}:
            node_tokens = tokens[1:3]
            node_names = [token.text for token in node_tokens]
            pin_roles = {
                node_names[0]: "terminal_a",
                node_names[1]: "terminal_b",
            } if len(node_names) == 2 else {}
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": "two_terminal",
                "polarity_marks": {},
                "port_order": ["terminal_a", "terminal_b"],
                "render_hints": {"orientation": "horizontal"},
                "model_name": "",
            }

        if prefix == "D":
            node_tokens = tokens[1:3]
            node_names = [token.text for token in node_tokens]
            pin_roles = {
                node_names[0]: "anode",
                node_names[1]: "cathode",
            } if len(node_names) == 2 else {}
            model_name = tokens[3].text if len(tokens) > 3 else ""
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": "two_terminal_polarized",
                "polarity_marks": {"anode": "+", "cathode": "-"},
                "port_order": ["anode", "cathode"],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        if prefix in {"V", "I"}:
            node_tokens = tokens[1:3]
            node_names = [token.text for token in node_tokens]
            pin_roles = {
                node_names[0]: "positive",
                node_names[1]: "negative",
            } if len(node_names) == 2 else {}
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": "source",
                "polarity_marks": {"positive": "+", "negative": "-"},
                "port_order": ["positive", "negative"],
                "render_hints": {"orientation": "vertical"},
                "model_name": "",
            }

        if prefix == "Q":
            node_tokens = tokens[1:4]
            node_names = [token.text for token in node_tokens]
            pin_roles = {
                node_names[0]: "collector",
                node_names[1]: "base",
                node_names[2]: "emitter",
            } if len(node_names) == 3 else {}
            model_name = tokens[4].text if len(tokens) > 4 else ""
            # Resolve the BJT channel variant from the .model lookup
            # built in pass 1. Falls back to the generic "bjt" marker
            # when no .model card was found (e.g. user-provided netlist
            # fragments without models), so downstream renderers can
            # still pick a neutral default.
            variant = model_variants.get(model_name, "")
            if variant not in ("npn", "pnp"):
                variant = "bjt"
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": variant,
                "polarity_marks": {},
                "port_order": ["collector", "base", "emitter"],
                "render_hints": {"orientation": "right"},
                "model_name": model_name,
            }

        if prefix == "J":
            # SPICE JFET card: `Jxxx D G S <model>` (3 nodes + model name).
            # Electrode order is drain / gate / source, identical to the
            # first three positions of a MOSFET but without the body
            # terminal, which is why we can reuse the same schematic
            # layout primitives downstream.
            node_tokens = tokens[1:4]
            node_names = [token.text for token in node_tokens]
            pin_roles = {
                node_names[0]: "drain",
                node_names[1]: "gate",
                node_names[2]: "source",
            } if len(node_names) == 3 else {}
            model_name = tokens[4].text if len(tokens) > 4 else ""
            # Resolve the JFET channel variant from the .model lookup.
            # Falls back to the generic "jfet" marker when no .model
            # card was found so the renderer can pick a neutral glyph.
            variant = model_variants.get(model_name, "")
            if variant not in ("njf", "pjf"):
                variant = "jfet"
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": variant,
                "polarity_marks": {},
                "port_order": ["drain", "gate", "source"],
                "render_hints": {"orientation": "right"},
                "model_name": model_name,
            }

        if prefix == "M":
            node_tokens = tokens[1:5]
            node_names = [token.text for token in node_tokens]
            pin_roles = {
                node_names[0]: "drain",
                node_names[1]: "gate",
                node_names[2]: "source",
                node_names[3]: "body",
            } if len(node_names) == 4 else {}
            model_name = tokens[5].text if len(tokens) > 5 else ""
            # Same pattern as Q: resolve NMOS vs PMOS from the .model
            # lookup. Falls back to "mos" when no .model card was
            # found so callers can still render a neutral default.
            variant = model_variants.get(model_name, "")
            if variant not in ("nmos", "pmos"):
                variant = "mos"
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": variant,
                "polarity_marks": {},
                "port_order": ["drain", "gate", "source", "body"],
                "render_hints": {"orientation": "right"},
                "model_name": model_name,
            }

        if prefix in {"X", "U"} and len(tokens) >= 3:
            node_tokens = tokens[1:-1]
            pin_roles = {token.text: f"port_{index + 1}" for index, token in enumerate(node_tokens)}
            model_name = tokens[-1].text
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": "block",
                "polarity_marks": {},
                "port_order": [f"port_{index + 1}" for index in range(len(node_tokens))],
                "render_hints": {"orientation": "horizontal"},
                "model_name": model_name,
            }

        node_tokens = tokens[1:-1] if len(tokens) > 3 else tokens[1:]
        pin_roles = {token.text: f"pin_{index + 1}" for index, token in enumerate(node_tokens)}
        model_name = tokens[-1].text if len(tokens) > 2 else ""
        return {
            "node_tokens": node_tokens,
            "pin_roles": pin_roles,
            "symbol_variant": "generic",
            "polarity_marks": {},
            "port_order": [f"pin_{index + 1}" for index in range(len(node_tokens))],
            "render_hints": {"orientation": "horizontal"},
            "model_name": model_name,
        }

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
        lowered = text.lower()
        if any(marker in lowered for marker in ("{", "}", "(", ")")):
            return False
        if lowered.startswith("@") or lowered.startswith("="):
            return False
        return bool(re.match(r"^[a-z0-9_+\-.]+$", lowered))

    def _tokenize_line(self, line_text: str, line_index: int, absolute_offset: int) -> List[SpiceToken]:
        tokens: List[SpiceToken] = []
        for token_index, match in enumerate(re.finditer(r"\S+", line_text)):
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


__all__ = ["SpiceParser"]
