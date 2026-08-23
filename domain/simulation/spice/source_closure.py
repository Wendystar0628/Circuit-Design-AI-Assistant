"""Deterministic SPICE source-closure provenance and runtime snapshots.

``source_digest`` identifies the effective input graph, not merely the main
deck.  Every referenced source is loaded exactly once, the graph is hashed
without embedding machine paths, and runtime execution is redirected to a
temporary mirror built from those same byte snapshots.

The pure :func:`build_spice_source_closure` entry point accepts injected blob
loading, reference resolution and stable-id functions so Git-commit migration
uses exactly the same manifest algorithm as live execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from domain.simulation.spice.file_codec import decode_spice_source_bytes
from domain.simulation.spice.include_parser import IncludeParser, ParsedInclude
from domain.simulation.spice.directive_tokenizer import (
    is_spice_end_directive,
    tokenize_spice_directive,
)


SPICE_SOURCE_CLOSURE_ALGORITHM = "spice-source-closure-v1"
_CLOSURE_DOMAIN = f"{SPICE_SOURCE_CLOSURE_ALGORITHM}\0".encode("ascii")
_ANALYSIS_COMMANDS = frozenset({".ac", ".dc", ".tran", ".noise", ".op"})
_REFERENCE_COMMANDS = frozenset({".include", ".inc", ".incpslt", ".lib"})

LoadBytes = Callable[[str], bytes]
ResolveReference = Callable[[str, str], str]
IdentifySource = Callable[[str, str, str, str], str]


class SpiceSourceClosureError(ValueError):
    """The complete effective source graph cannot be identified safely."""


@dataclass(frozen=True)
class SpiceSourceReference:
    parent_key: str
    parent_id: str
    line_number: int
    statement_type: str
    raw_path: str
    library_section: str
    target_key: str
    target_id: str


@dataclass(frozen=True)
class SpiceSourceCommand:
    source_id: str
    line_number: int
    statement: str
    analysis_type: str = ""


@dataclass(frozen=True)
class SpiceSourceLine:
    line_number: int
    text: str


@dataclass(frozen=True)
class SpiceSourceView:
    key: str
    source_id: str
    library_section: str
    is_main_deck: bool
    lines: Tuple[SpiceSourceLine, ...]


@dataclass(frozen=True)
class SpiceSourceBlob:
    key: str
    source_id: str
    raw_bytes: bytes
    source_text: str
    encoding: str
    analysis_commands: Tuple[SpiceSourceCommand, ...]
    control_commands: Tuple[SpiceSourceCommand, ...]


@dataclass(frozen=True)
class SpiceSourceClosureGraph:
    main_key: str
    digest: str
    blobs: Tuple[SpiceSourceBlob, ...]
    references: Tuple[SpiceSourceReference, ...]
    active_views: Tuple[SpiceSourceView, ...]

    @property
    def source_keys(self) -> Tuple[str, ...]:
        return tuple(blob.key for blob in self.blobs)

    @property
    def dependency_analysis_commands(
        self,
    ) -> Tuple[Tuple[str, int, str], ...]:
        return tuple(
            (command.source_id, command.line_number, command.statement)
            for blob in self.blobs
            if blob.key != self.main_key
            for command in blob.analysis_commands
        )

    @property
    def main_analysis_commands(self) -> Tuple[SpiceSourceCommand, ...]:
        for blob in self.blobs:
            if blob.key == self.main_key:
                return blob.analysis_commands
        return ()

    @property
    def main_blob(self) -> SpiceSourceBlob:
        for blob in self.blobs:
            if blob.key == self.main_key:
                return blob
        raise SpiceSourceClosureError("source closure 缺少主网表 blob")

    @property
    def control_commands(self) -> Tuple[Tuple[str, int, str], ...]:
        return tuple(
            (command.source_id, command.line_number, command.statement)
            for blob in self.blobs
            for command in blob.control_commands
        )


class RuntimeSpiceSourceClosure:
    """Context-managed mirror of one already-collected source closure."""

    def __init__(
        self,
        *,
        graph: SpiceSourceClosureGraph,
        temporary_directory: tempfile.TemporaryDirectory[str],
        snapshot_root: Path,
        main_text: str,
    ) -> None:
        self.graph = graph
        self.digest = graph.digest
        self.source_paths = graph.source_keys
        self.snapshot_root = snapshot_root
        self.main_text = main_text
        self._temporary_directory: Optional[tempfile.TemporaryDirectory[str]] = (
            temporary_directory
        )

    def close(self) -> None:
        temporary_directory = self._temporary_directory
        self._temporary_directory = None
        if temporary_directory is not None:
            temporary_directory.cleanup()

    def __enter__(self) -> "RuntimeSpiceSourceClosure":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def build_spice_source_closure(
    main_key: str,
    *,
    load_bytes: LoadBytes,
    resolve_reference: ResolveReference,
    identify_source: IdentifySource,
    main_bytes: Optional[bytes] = None,
) -> SpiceSourceClosureGraph:
    """Collect and hash a source graph through injected storage callbacks.

    ``identify_source(parent_key, parent_id, target_key, raw_path)`` must return
    a stable, non-empty POSIX-like identifier. The returned identifier, raw
    blob hashes and ordered graph edges form the canonical manifest.
    """

    normalized_main_key = _require_key(main_key)
    parser = IncludeParser()
    raw_by_key: Dict[str, bytes] = {}
    blob_by_key: Dict[str, SpiceSourceBlob] = {}
    decoded_by_key: Dict[str, Tuple[str, str]] = {}
    source_id_by_key: Dict[str, str] = {normalized_main_key: "@main"}
    key_by_source_id: Dict[str, str] = {"@main": normalized_main_key}
    references: list[SpiceSourceReference] = []
    reference_by_location: Dict[
        Tuple[str, int, str], SpiceSourceReference
    ] = {}
    active_views: list[SpiceSourceView] = []
    physical_visiting: list[str] = []
    physically_expanded: set[str] = set()
    semantic_visiting: list[Tuple[str, str]] = []
    semantically_expanded: set[Tuple[str, str]] = set()
    semantic_origin_by_view: Dict[
        Tuple[str, str], Optional[SpiceSourceReference]
    ] = {}

    if main_bytes is not None:
        if not isinstance(main_bytes, bytes):
            raise TypeError("main_bytes must be bytes")
        raw_by_key[normalized_main_key] = main_bytes

    def get_raw(key: str) -> bytes:
        if key in raw_by_key:
            return raw_by_key[key]
        try:
            raw = load_bytes(key)
        except Exception as exc:
            raise SpiceSourceClosureError(
                f"无法读取 SPICE source closure 文件: {key}: {exc}"
            ) from exc
        if not isinstance(raw, bytes):
            raise SpiceSourceClosureError(
                f"SPICE source loader 必须返回 bytes: {key}"
            )
        raw_by_key[key] = raw
        return raw

    def register_identity(key: str, source_id: str) -> None:
        normalized_id = _normalize_source_id(source_id)
        existing_id = source_id_by_key.get(key)
        if existing_id is not None and existing_id != normalized_id:
            raise SpiceSourceClosureError(
                "同一依赖通过不一致的路径身份被引用: "
                f"{key} ({existing_id!r} vs {normalized_id!r})"
            )
        existing_key = key_by_source_id.get(normalized_id)
        if existing_key is not None and existing_key != key:
            raise SpiceSourceClosureError(
                "不同依赖产生相同的稳定 source-id: "
                f"{normalized_id!r}"
            )
        source_id_by_key[key] = normalized_id
        key_by_source_id[normalized_id] = key

    def get_decoded(key: str) -> Tuple[str, str]:
        existing = decoded_by_key.get(key)
        if existing is not None:
            return existing
        raw = get_raw(key)
        try:
            source_text, encoding = decode_spice_source_bytes(raw)
        except (TypeError, UnicodeError) as exc:
            raise SpiceSourceClosureError(
                f"无法解码 SPICE source closure 文件: {key}: {exc}"
            ) from exc
        decoded_by_key[key] = (source_text, encoding)
        return source_text, encoding

    def resolve_card(
        parent_key: str,
        parsed: ParsedInclude,
        *,
        record: bool,
    ) -> SpiceSourceReference:
        parent_id = source_id_by_key[parent_key]
        try:
            target_key = _require_key(
                resolve_reference(parent_key, parsed.raw_path)
            )
        except Exception as exc:
            raise SpiceSourceClosureError(
                f"无法解析 {parent_key}:{parsed.line_number} 的依赖 "
                f"{parsed.raw_path!r}: {exc}"
            ) from exc
        if (
            parsed.statement_type != "lib"
            and target_key in physical_visiting
        ):
            cycle_start = physical_visiting.index(target_key)
            cycle = physical_visiting[cycle_start:] + [target_key]
            raise SpiceSourceClosureError(
                "SPICE include 依赖形成循环: " + " -> ".join(cycle)
            )
        try:
            target_id = identify_source(
                parent_key,
                parent_id,
                target_key,
                parsed.raw_path,
            )
        except Exception as exc:
            raise SpiceSourceClosureError(
                f"无法生成稳定 source-id: {target_key}: {exc}"
            ) from exc
        register_identity(target_key, target_id)
        reference = SpiceSourceReference(
            parent_key=parent_key,
            parent_id=parent_id,
            line_number=parsed.line_number,
            statement_type=parsed.statement_type,
            raw_path=parsed.raw_path,
            library_section=parsed.library_section,
            target_key=target_key,
            target_id=source_id_by_key[target_key],
        )
        if record:
            location = (
                parent_key,
                parsed.line_number,
                parsed.statement_type,
            )
            existing = reference_by_location.get(location)
            if existing is not None and existing != reference:
                raise SpiceSourceClosureError(
                    "同一 source line 解析出不一致的依赖: "
                    f"{parent_key}:{parsed.line_number}"
                )
            if existing is None:
                reference_by_location[location] = reference
                references.append(reference)
        return reference

    def ensure_physical_closure(key: str) -> None:
        """Load every file ngspice's include preprocessor may open.

        ngspice expands ``.include``/``.inc``/``.incpslt`` before selecting a
        ``.lib`` section.  Consequently those cards are physical dependencies
        even inside an unselected section.  File-selecting ``.lib`` cards are
        different: only an active semantic view opens their target.
        """

        if key in physical_visiting:
            cycle_start = physical_visiting.index(key)
            cycle = physical_visiting[cycle_start:] + [key]
            raise SpiceSourceClosureError(
                "SPICE include 依赖形成循环: " + " -> ".join(cycle)
            )
        if key in physically_expanded:
            return

        raw = get_raw(key)
        source_id = source_id_by_key[key]
        source_text, encoding = get_decoded(key)
        if key not in blob_by_key:
            blob_by_key[key] = SpiceSourceBlob(
                key=key,
                source_id=source_id,
                raw_bytes=raw,
                source_text=source_text,
                encoding=encoding,
                analysis_commands=(),
                control_commands=(),
            )

        physical_visiting.append(key)
        try:
            physical_references = _scan_physical_include_references(
                source_text,
                parser=parser,
                is_main=key == normalized_main_key,
                source_key=key,
            )
            for parsed in physical_references:
                reference = resolve_card(key, parsed, record=True)
                ensure_physical_closure(reference.target_key)
        finally:
            physical_visiting.pop()
        physically_expanded.add(key)

    def visit_semantic_view(
        key: str,
        *,
        is_main: bool,
        selected_section: str = "",
        origin: Optional[SpiceSourceReference] = None,
    ) -> None:
        normalized_section = _normalize_library_section(selected_section)
        view_key = (key, normalized_section)
        if view_key in semantic_visiting:
            cycle_start = semantic_visiting.index(view_key)
            cycle = semantic_visiting[cycle_start:] + [view_key]
            raise SpiceSourceClosureError(
                "SPICE include/lib 依赖形成循环: "
                + " -> ".join(
                    _format_source_view(item_key, item_section)
                    for item_key, item_section in cycle
                )
            )
        if view_key in semantically_expanded:
            first_origin = semantic_origin_by_view.get(view_key)
            first_location = (
                "主网表"
                if first_origin is None
                else f"{first_origin.parent_id}:{first_origin.line_number}"
            )
            duplicate_location = (
                "主网表"
                if origin is None
                else f"{origin.parent_id}:{origin.line_number}"
            )
            raise SpiceSourceClosureError(
                "重复 active SPICE source expansion 会让网表定义或测量重复: "
                f"{_format_source_view(key, normalized_section)} "
                f"(首次 {first_location}，再次 {duplicate_location})"
            )

        semantic_origin_by_view[view_key] = origin

        ensure_physical_closure(key)
        source_id = source_id_by_key[key]
        source_text, _encoding = get_decoded(key)
        (
            parsed_references,
            analysis_commands,
            control_commands,
            active_lines,
        ) = _scan_source_text(
            source_text,
            parser=parser,
            is_main=is_main,
            source_key=key,
            source_id=source_id,
            selected_section=normalized_section,
        )
        active_views.append(
            SpiceSourceView(
                key=key,
                source_id=source_id,
                library_section=normalized_section,
                is_main_deck=is_main,
                lines=active_lines,
            )
        )
        existing_blob = blob_by_key.get(key)
        if existing_blob is None:
            raise SpiceSourceClosureError(
                f"source closure 内部缺少已加载 blob: {key}"
            )
        blob_by_key[key] = SpiceSourceBlob(
            key=key,
            source_id=source_id,
            raw_bytes=existing_blob.raw_bytes,
            source_text=source_text,
            encoding=existing_blob.encoding,
            analysis_commands=_merge_source_commands(
                existing_blob.analysis_commands,
                analysis_commands,
            ),
            control_commands=_merge_source_commands(
                existing_blob.control_commands,
                control_commands,
            ),
        )

        semantic_visiting.append(view_key)
        try:
            for parsed in parsed_references:
                if parsed.statement_type == "lib":
                    reference = resolve_card(key, parsed, record=True)
                    target_section = parsed.library_section
                    ensure_physical_closure(reference.target_key)
                else:
                    location = (key, parsed.line_number, parsed.statement_type)
                    reference = reference_by_location.get(location)
                    if reference is None:
                        raise SpiceSourceClosureError(
                            "active include 缺少物理预处理依赖: "
                            f"{key}:{parsed.line_number}"
                        )
                    target_section = ""
                target_key = reference.target_key
                target_view_key = (
                    target_key,
                    _normalize_library_section(target_section),
                )
                if target_view_key in semantic_visiting:
                    cycle_start = semantic_visiting.index(target_view_key)
                    cycle = semantic_visiting[cycle_start:] + [target_view_key]
                    raise SpiceSourceClosureError(
                        "SPICE include/lib 依赖形成循环: "
                        + " -> ".join(
                            _format_source_view(
                                item_key,
                                item_section,
                            )
                            for item_key, item_section in cycle
                        )
                    )
                visit_semantic_view(
                    target_key,
                    is_main=False,
                    selected_section=target_section,
                    origin=reference,
                )
        finally:
            semantic_visiting.pop()
        semantically_expanded.add(view_key)

    visit_semantic_view(normalized_main_key, is_main=True)
    blobs = tuple(sorted(blob_by_key.values(), key=lambda item: item.source_id))
    ordered_references = tuple(
        sorted(
            references,
            key=lambda item: (
                item.parent_id,
                item.line_number,
                item.statement_type,
                item.target_id,
                item.library_section,
            ),
        )
    )
    digest = _build_closure_digest(blobs, ordered_references)
    return SpiceSourceClosureGraph(
        main_key=normalized_main_key,
        digest=digest,
        blobs=blobs,
        references=ordered_references,
        active_views=tuple(
            sorted(
                active_views,
                key=lambda item: (
                    item.source_id,
                    item.library_section,
                    not item.is_main_deck,
                ),
            )
        ),
    )


def collect_spice_source_closure(
    main_path: str | Path,
    *,
    main_bytes: Optional[bytes] = None,
) -> SpiceSourceClosureGraph:
    """Collect one immutable live source graph without creating a mirror."""

    path = _require_live_file(main_path)
    callbacks = _LivePathCallbacks(path)
    return build_spice_source_closure(
        str(path),
        load_bytes=callbacks.load_bytes,
        resolve_reference=callbacks.resolve_reference,
        identify_source=callbacks.identify_source,
        main_bytes=main_bytes,
    )


def snapshot_spice_source_closure(
    main_path: str | Path,
    *,
    main_bytes: Optional[bytes] = None,
) -> RuntimeSpiceSourceClosure:
    """Collect a live source graph and mirror that exact snapshot for native execution."""

    graph = collect_spice_source_closure(main_path, main_bytes=main_bytes)
    temporary_directory = tempfile.TemporaryDirectory(
        prefix="circuit-ai-spice-closure-"
    )
    snapshot_root = Path(temporary_directory.name).resolve()
    try:
        main_text = _write_runtime_mirror(graph, snapshot_root)
    except Exception:
        temporary_directory.cleanup()
        raise
    return RuntimeSpiceSourceClosure(
        graph=graph,
        temporary_directory=temporary_directory,
        snapshot_root=snapshot_root,
        main_text=main_text,
    )


class _LivePathCallbacks:
    def __init__(self, main_path: Path) -> None:
        self._main_path = main_path
        self._main_dir = main_path.parent
        self._absolute_anchor_by_key: Dict[str, Tuple[Path, str]] = {}

    @staticmethod
    def load_bytes(key: str) -> bytes:
        path = _require_live_file(key)
        return path.read_bytes()

    @staticmethod
    def resolve_reference(parent_key: str, raw_path: str) -> str:
        parent = Path(parent_key)
        candidate = Path(raw_path).expanduser()
        target = (
            candidate.resolve(strict=False)
            if candidate.is_absolute()
            else (parent.parent / candidate).resolve(strict=False)
        )
        return str(_require_live_file(target))

    def identify_source(
        self,
        parent_key: str,
        parent_id: str,
        target_key: str,
        raw_path: str,
    ) -> str:
        target = Path(target_key).resolve(strict=True)
        raw_candidate = Path(raw_path).expanduser()
        if raw_candidate.is_absolute():
            normalized_absolute = os.path.normcase(str(target))
            anchor_hash = hashlib.sha256(
                normalized_absolute.encode("utf-8")
            ).hexdigest()
            self._absolute_anchor_by_key[target_key] = (
                target.parent,
                anchor_hash,
            )
            return f"absolute/{anchor_hash}/{target.name}"

        absolute_anchor = self._absolute_anchor_by_key.get(parent_key)
        if absolute_anchor is not None or parent_id.startswith("absolute/"):
            if absolute_anchor is None:
                raise SpiceSourceClosureError(
                    f"绝对依赖后代缺少稳定锚点: {parent_key}"
                )
            anchor_dir, anchor_hash = absolute_anchor
            relative = os.path.relpath(target, anchor_dir).replace("\\", "/")
            relative = posixpath.normpath(relative)
            self._absolute_anchor_by_key[target_key] = (
                anchor_dir,
                anchor_hash,
            )
            return f"absolute/{anchor_hash}/{relative}"

        try:
            relative = os.path.relpath(target, self._main_dir)
        except ValueError as exc:
            raise SpiceSourceClosureError(
                "相对依赖无法表示为主网表目录的稳定路径"
            ) from exc
        return posixpath.normpath(relative.replace("\\", "/"))


def _select_active_source_lines(
    source_text: str,
    *,
    selected_section: str,
    source_key: str,
) -> Tuple[SpiceSourceLine, ...]:
    physical_lines = tuple(
        SpiceSourceLine(line_number=line_number, text=line)
        for line_number, line in enumerate(source_text.splitlines(), start=1)
    )
    requested = _normalize_library_section(selected_section)
    if not requested:
        return physical_lines

    active: list[SpiceSourceLine] = []
    current_section = ""
    matched_blocks = 0
    for source_line in physical_lines:
        tokens = tokenize_spice_directive(source_line.text)
        command = tokens[0].casefold() if tokens else ""
        if command == ".lib" and len(tokens) == 2:
            if current_section:
                raise SpiceSourceClosureError(
                    f"SPICE .lib section 不允许嵌套: "
                    f"{source_key}:{source_line.line_number}"
                )
            current_section = _normalize_library_section(tokens[1])
            if not current_section:
                raise SpiceSourceClosureError(
                    f"SPICE .lib section 名称为空: "
                    f"{source_key}:{source_line.line_number}"
                )
            if current_section == requested:
                matched_blocks += 1
            continue
        if command == ".endl":
            if not current_section:
                raise SpiceSourceClosureError(
                    f"SPICE .endl 缺少对应 .lib section: "
                    f"{source_key}:{source_line.line_number}"
                )
            if len(tokens) > 2:
                raise SpiceSourceClosureError(
                    f"SPICE .endl 语法无效: "
                    f"{source_key}:{source_line.line_number}"
                )
            end_section = (
                _normalize_library_section(tokens[1])
                if len(tokens) == 2
                else current_section
            )
            if end_section != current_section:
                raise SpiceSourceClosureError(
                    f"SPICE .endl section 与 .lib 不匹配: "
                    f"{source_key}:{source_line.line_number}"
                )
            current_section = ""
            continue
        if current_section == requested:
            active.append(source_line)

    if current_section:
        raise SpiceSourceClosureError(
            f"SPICE .lib section 未以 .endl 结束: {source_key}: {current_section}"
        )
    if matched_blocks == 0:
        raise SpiceSourceClosureError(
            f"SPICE 库中不存在请求的 section: {source_key}: {requested}"
        )
    if matched_blocks > 1:
        raise SpiceSourceClosureError(
            f"SPICE 库 section 重复，无法唯一选择: {source_key}: {requested}"
        )
    return tuple(active)


def _normalize_library_section(value: object) -> str:
    normalized = str(value or "").strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {"'", '"'}
    ):
        normalized = normalized[1:-1].strip()
    return normalized.casefold()


def _format_source_view(key: str, section: str) -> str:
    return f"{key}[{section}]" if section else key


def _merge_source_commands(
    first: Tuple[SpiceSourceCommand, ...],
    second: Tuple[SpiceSourceCommand, ...],
) -> Tuple[SpiceSourceCommand, ...]:
    by_identity = {
        (
            command.source_id,
            command.line_number,
            command.statement,
            command.analysis_type,
        ): command
        for command in (*first, *second)
    }
    return tuple(
        by_identity[key]
        for key in sorted(by_identity, key=lambda item: (item[1], item[2], item[3]))
    )


def _scan_physical_include_references(
    source_text: str,
    *,
    parser: IncludeParser,
    is_main: bool,
    source_key: str,
) -> Tuple[ParsedInclude, ...]:
    """Return cards opened by ngspice before ``.lib`` section selection.

    File-selecting ``.lib`` cards are intentionally excluded.  They belong to
    the selected semantic view, whereas the include-family preprocessor opens
    files across all physical library sections.  The first main-deck line is
    always the SPICE title and therefore cannot be a directive.
    """

    references: list[ParsedInclude] = []
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        if is_main and line_number == 1:
            continue
        if is_main and is_spice_end_directive(line):
            break
        stripped = line.strip()
        command = (
            stripped.split(None, 1)[0].casefold()
            if stripped.startswith(".")
            else ""
        )
        parsed = parser.parse_line(line, line_number)
        if parsed is not None:
            if parsed.statement_type != "lib":
                references.append(parsed)
            continue
        if command in {".include", ".inc", ".incpslt"}:
            raise SpiceSourceClosureError(
                f"无法安全解析文件引用: {source_key}:{line_number}: {stripped}"
            )
    return tuple(references)


def _scan_source_text(
    source_text: str,
    *,
    parser: IncludeParser,
    is_main: bool,
    source_key: str,
    source_id: str,
    selected_section: str,
) -> Tuple[
    Tuple[ParsedInclude, ...],
    Tuple[SpiceSourceCommand, ...],
    Tuple[SpiceSourceCommand, ...],
    Tuple[SpiceSourceLine, ...],
]:
    active_lines = _select_active_source_lines(
        source_text,
        selected_section=selected_section,
        source_key=source_key,
    )
    references: list[ParsedInclude] = []
    analysis_commands: list[SpiceSourceCommand] = []
    control_commands: list[SpiceSourceCommand] = []
    in_control = False
    continued_analysis_index: Optional[int] = None
    for source_line in active_lines:
        line_number = source_line.line_number
        line = source_line.text
        if is_main and line_number == 1:
            continued_analysis_index = None
            continue
        stripped = line.strip()
        if stripped.startswith("+"):
            if continued_analysis_index is not None:
                continuation = stripped[1:].strip()
                previous = analysis_commands[continued_analysis_index]
                analysis_commands[continued_analysis_index] = SpiceSourceCommand(
                    source_id=previous.source_id,
                    line_number=previous.line_number,
                    statement=(
                        f"{previous.statement} {continuation}".rstrip()
                    ),
                    analysis_type=previous.analysis_type,
                )
            continue

        continued_analysis_index = None
        tokens = tokenize_spice_directive(line)
        command = tokens[0].casefold() if tokens else ""
        if command == ".control":
            control_commands.append(
                SpiceSourceCommand(
                    source_id=source_id,
                    line_number=line_number,
                    statement=stripped,
                )
            )
            in_control = True
            continue
        if command == ".endc":
            control_commands.append(
                SpiceSourceCommand(
                    source_id=source_id,
                    line_number=line_number,
                    statement=stripped,
                )
            )
            in_control = False
            continue
        if in_control:
            continue
        if is_spice_end_directive(line):
            break
        if is_main and _is_library_section_card(command, stripped):
            raise SpiceSourceClosureError(
                "主网表不支持内联 .lib section 定义；"
                "请将 section 放入独立库文件并用 .lib filename section 选择: "
                f"{source_key}:{line_number}: {stripped}"
            )
        if command in _ANALYSIS_COMMANDS:
            analysis_commands.append(
                SpiceSourceCommand(
                    source_id=source_id,
                    line_number=line_number,
                    statement=stripped,
                    analysis_type=command[1:],
                )
            )
            continued_analysis_index = len(analysis_commands) - 1

        parsed = parser.parse_line(line, line_number)
        if parsed is not None:
            references.append(parsed)
            continue
        if command in _REFERENCE_COMMANDS and not _is_library_section_card(
            command,
            stripped,
        ):
            raise SpiceSourceClosureError(
                f"无法安全解析文件引用: {source_key}:{line_number}: {stripped}"
            )
    return (
        tuple(references),
        tuple(analysis_commands),
        tuple(control_commands),
        active_lines,
    )


def _is_library_section_card(command: str, stripped_line: str) -> bool:
    if command != ".lib":
        return False
    tokens = tokenize_spice_directive(stripped_line)
    return len(tokens) == 2 and tokens[0].casefold() == ".lib"


def _build_closure_digest(
    blobs: Tuple[SpiceSourceBlob, ...],
    references: Tuple[SpiceSourceReference, ...],
) -> str:
    payload = {
        "files": [
            {
                "id": blob.source_id,
                "sha256": hashlib.sha256(blob.raw_bytes).hexdigest(),
            }
            for blob in blobs
        ],
        "main": "@main",
        "references": [
            {
                "from": reference.parent_id,
                "kind": reference.statement_type,
                "line": reference.line_number,
                "section": reference.library_section,
                "to": reference.target_id,
            }
            for reference in references
        ],
        "version": 1,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(_CLOSURE_DOMAIN + canonical).hexdigest()


def _write_runtime_mirror(
    graph: SpiceSourceClosureGraph,
    snapshot_root: Path,
) -> str:
    sources_root = snapshot_root / "sources"
    sources_root.mkdir(parents=True, exist_ok=False)
    mirror_path_by_key: Dict[str, Path] = {}
    for blob in graph.blobs:
        name_digest = hashlib.sha256(blob.source_id.encode("utf-8")).hexdigest()
        basename = Path(blob.key).name or "source.inc"
        safe_basename = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
        mirror_path_by_key[blob.key] = (
            sources_root / f"{name_digest}_{safe_basename}"
        )

    references_by_line: Dict[Tuple[str, int], SpiceSourceReference] = {}
    for reference in graph.references:
        line_key = (reference.parent_key, reference.line_number)
        existing = references_by_line.get(line_key)
        if existing is not None and existing != reference:
            raise SpiceSourceClosureError(
                "同一 source line 解析出多个依赖，无法构建确定镜像: "
                f"{reference.parent_key}:{reference.line_number}"
            )
        references_by_line[line_key] = reference

    rewritten_by_key: Dict[str, str] = {}
    for blob in graph.blobs:
        mirror_path = mirror_path_by_key[blob.key]
        rewritten_lines: list[str] = []
        for line_number, line in enumerate(blob.source_text.splitlines(), start=1):
            reference = references_by_line.get((blob.key, line_number))
            if reference is None:
                rewritten_lines.append(line)
                continue
            target_path = mirror_path_by_key[reference.target_key].as_posix()
            if reference.statement_type == "lib":
                rewritten_lines.append(
                    f'.lib "{target_path}" {reference.library_section}'
                )
            elif reference.statement_type == "incpslt":
                rewritten_lines.append(f'.incpslt "{target_path}"')
            else:
                rewritten_lines.append(f'.include "{target_path}"')
        rewritten = "\n".join(rewritten_lines)
        if blob.source_text.endswith(("\n", "\r")):
            rewritten += "\n"
        mirror_path.write_text(rewritten, encoding="utf-8", newline="")
        rewritten_by_key[blob.key] = rewritten

    main_text = rewritten_by_key.get(graph.main_key)
    if main_text is None:
        raise SpiceSourceClosureError("主网表未生成运行时镜像")
    return main_text


def _require_live_file(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SpiceSourceClosureError(f"SPICE source 文件不存在: {path}") from exc
    if not resolved.is_file():
        raise SpiceSourceClosureError(f"SPICE source 依赖不是普通文件: {resolved}")
    return resolved


def _require_key(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SpiceSourceClosureError("source closure key 必须是非空字符串")
    return value


def _normalize_source_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpiceSourceClosureError("source-id 必须是非空字符串")
    normalized = value.replace("\\", "/").strip()
    if "\x00" in normalized:
        raise SpiceSourceClosureError("source-id 不允许 NUL 字符")
    return normalized


__all__ = [
    "SPICE_SOURCE_CLOSURE_ALGORITHM",
    "RuntimeSpiceSourceClosure",
    "SpiceSourceBlob",
    "SpiceSourceCommand",
    "SpiceSourceClosureError",
    "SpiceSourceClosureGraph",
    "SpiceSourceLine",
    "SpiceSourceReference",
    "SpiceSourceView",
    "build_spice_source_closure",
    "collect_spice_source_closure",
    "snapshot_spice_source_closure",
]
