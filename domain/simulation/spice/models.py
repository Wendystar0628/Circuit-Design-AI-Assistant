from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SourceSpan:
    line_index: int
    column_start: int
    column_end: int
    absolute_start: int
    absolute_end: int


@dataclass(frozen=True)
class TokenSpan:
    token_index: int
    column_start: int
    column_end: int
    absolute_start: int
    absolute_end: int


@dataclass(frozen=True)
class SpiceToken:
    text: str
    span: TokenSpan


@dataclass
class SpiceEditableField:
    field_key: str
    label: str
    raw_text: str
    display_text: str
    editable: bool
    readonly_reason: str
    value_kind: str
    token_span: Optional[TokenSpan] = None
    source_span: Optional[SourceSpan] = None


@dataclass
class SpicePin:
    name: str
    node_id: str
    role: str


@dataclass
class SpiceComponent:
    id: str
    instance_name: str
    kind: str
    symbol_kind: str
    symbol_variant: str
    source_file: str
    scope_path: List[str] = field(default_factory=list)
    node_ids: List[str] = field(default_factory=list)
    pins: List[SpicePin] = field(default_factory=list)
    editable_fields: List[SpiceEditableField] = field(default_factory=list)
    source_span: Optional[SourceSpan] = None
    token_spans: Dict[str, TokenSpan] = field(default_factory=dict)
    pin_roles: Dict[str, str] = field(default_factory=dict)
    polarity_marks: Dict[str, str] = field(default_factory=dict)
    port_order: List[str] = field(default_factory=list)
    render_hints: Dict[str, str] = field(default_factory=dict)
    model_name: str = ""
    primitive_kind: str = ""
    primitive_source: str = ""
    subckt_name: str = ""
    resolved_model_name: str = ""
    semantic_roles: List[str] = field(default_factory=list)
    raw_line: str = ""


@dataclass
class SpiceInclude:
    path: str
    source_file: str
    source_span: Optional[SourceSpan] = None


@dataclass
class SpiceSubcircuit:
    name: str
    port_names: List[str] = field(default_factory=list)
    scope_path: List[str] = field(default_factory=list)
    source_file: str = ""
    source_span: Optional[SourceSpan] = None
    components: List[SpiceComponent] = field(default_factory=list)
    primitive_kind: str = ""


@dataclass
class SpiceParseError:
    message: str
    source_file: str
    source_span: Optional[SourceSpan] = None
    line_text: str = ""


@dataclass
class SpiceDocument:
    source_file: str
    components: List[SpiceComponent] = field(default_factory=list)
    includes: List[SpiceInclude] = field(default_factory=list)
    subcircuits: List[SpiceSubcircuit] = field(default_factory=list)
    parse_errors: List[SpiceParseError] = field(default_factory=list)

    def add_component(self, component: SpiceComponent) -> None:
        self.components.append(component)

    def add_include(self, include: SpiceInclude) -> None:
        self.includes.append(include)

    def add_subcircuit(self, subcircuit: SpiceSubcircuit) -> None:
        self.subcircuits.append(subcircuit)

    def add_parse_error(self, parse_error: SpiceParseError) -> None:
        self.parse_errors.append(parse_error)
