from __future__ import annotations

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


_COMPONENT_SYMBOL_KINDS: Dict[str, str] = {
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "D": "diode",
    "V": "voltage_source",
    "I": "current_source",
    "Q": "bjt",
    "M": "mos",
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
    ) -> Optional[SpiceComponent]:
        source_span = self._make_line_span(line_index, line_text, absolute_offset)
        tokens = self._tokenize_line(line_text, line_index, absolute_offset)
        if len(tokens) < 2:
            return None

        instance_name = tokens[0].text
        prefix = instance_name[0].upper()
        symbol_kind = _COMPONENT_SYMBOL_KINDS.get(prefix, "unknown")
        descriptor = self._describe_component(prefix, tokens)
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

    def _describe_component(self, prefix: str, tokens: List[SpiceToken]) -> Dict[str, object]:
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
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": "bjt",
                "polarity_marks": {},
                "port_order": ["collector", "base", "emitter"],
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
            return {
                "node_tokens": node_tokens,
                "pin_roles": pin_roles,
                "symbol_variant": "mos",
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
