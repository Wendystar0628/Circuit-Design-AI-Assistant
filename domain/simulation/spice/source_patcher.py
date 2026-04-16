from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from domain.simulation.spice.file_codec import SpiceSourceFile, read_spice_source_file, write_spice_source_file
from domain.simulation.spice.models import SpiceComponent, SpiceDocument, SpiceEditableField
from domain.simulation.spice.schematic_builder import make_schematic_document_id, make_schematic_revision


@dataclass
class SpiceSourcePatchResult:
    success: bool
    result_type: str
    error_message: str
    document_id: str
    revision: str
    request_id: str
    component_id: str
    field_key: str
    source_text: str
    changed: bool


class SpiceSourcePatcher:
    def patch_value(
        self,
        *,
        file_path: str,
        spice_document: SpiceDocument,
        document_id: str,
        revision: str,
        component_id: str,
        field_key: str,
        new_text: str,
        request_id: str,
        dependency_snapshots: Optional[Dict[str, str]] = None,
        persist: bool = True,
    ) -> SpiceSourcePatchResult:
        normalized_request_id = str(request_id or "")
        normalized_component_id = str(component_id or "")
        normalized_field_key = str(field_key or "")
        current_document_id = make_schematic_document_id(file_path)
        if normalized_field_key != "value":
            return self._reject_without_source_file(
                document_id=current_document_id,
                revision="",
                request_id=normalized_request_id,
                component_id=normalized_component_id,
                field_key=normalized_field_key,
                result_type="error",
                error_message="当前只支持写回数值字段",
            )
        try:
            source_file = read_spice_source_file(file_path)
        except FileNotFoundError:
            return self._reject_without_source_file(
                document_id=current_document_id,
                revision="",
                request_id=normalized_request_id,
                component_id=normalized_component_id,
                field_key=normalized_field_key,
                result_type="error",
                error_message="未找到源电路文件",
            )
        except PermissionError:
            return self._reject_without_source_file(
                document_id=current_document_id,
                revision="",
                request_id=normalized_request_id,
                component_id=normalized_component_id,
                field_key=normalized_field_key,
                result_type="error",
                error_message="源电路文件不可读或不可写",
            )
        except OSError as exc:
            return self._reject_without_source_file(
                document_id=current_document_id,
                revision="",
                request_id=normalized_request_id,
                component_id=normalized_component_id,
                field_key=normalized_field_key,
                result_type="error",
                error_message=f"读取源电路文件失败: {exc}",
            )
        if str(document_id or "") != current_document_id:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=make_schematic_revision(file_path, source_file.source_text, dependency_snapshots),
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="conflict",
                error_message="schematic document 已失效，请刷新后重试",
            )

        current_revision = make_schematic_revision(file_path, source_file.source_text, dependency_snapshots)
        if str(revision or "") != current_revision:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="conflict",
                error_message="revision 已过期，请刷新后重试",
            )

        component = self._find_component(spice_document, component_id)
        if component is None:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message="未找到目标元件",
            )

        field = self._find_field(component.editable_fields, field_key)
        if field is None:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message="未找到目标字段",
            )

        if not field.editable:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message=field.readonly_reason or "该字段当前不可编辑",
            )

        if field.token_span is None:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message="缺少可写回的 token span",
            )

        normalized_new_text = str(new_text or "")
        if not self._is_safe_single_token_text(normalized_new_text):
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="error",
                error_message="新文本必须是单个 token，且不能包含空白或换行",
            )

        span = field.token_span
        original_token = source_file.source_text[span.absolute_start:span.absolute_end]
        if original_token != field.raw_text:
            return self._reject(
                source_file=source_file,
                document_id=current_document_id,
                revision=current_revision,
                request_id=request_id,
                component_id=component_id,
                field_key=field_key,
                result_type="conflict",
                error_message="目标源码与解析快照不一致，已拒绝近似 patch",
            )

        if normalized_new_text == original_token:
            return SpiceSourcePatchResult(
                success=True,
                result_type="success",
                error_message="",
                document_id=current_document_id,
                revision=current_revision,
                request_id=str(request_id or ""),
                component_id=str(component_id or ""),
                field_key=str(field_key or ""),
                source_text=source_file.source_text,
                changed=False,
            )

        patched_text = "".join(
            [
                source_file.source_text[:span.absolute_start],
                normalized_new_text,
                source_file.source_text[span.absolute_end:],
            ]
        )

        if persist:
            try:
                write_spice_source_file(source_file, patched_text)
            except PermissionError:
                return self._reject(
                    source_file=source_file,
                    document_id=current_document_id,
                    revision=current_revision,
                    request_id=request_id,
                    component_id=component_id,
                    field_key=field_key,
                    result_type="error",
                    error_message="源电路文件不可写",
                )
            except OSError as exc:
                return self._reject(
                    source_file=source_file,
                    document_id=current_document_id,
                    revision=current_revision,
                    request_id=request_id,
                    component_id=component_id,
                    field_key=field_key,
                    result_type="error",
                    error_message=f"写入源电路文件失败: {exc}",
                )

        return SpiceSourcePatchResult(
            success=True,
            result_type="success",
            error_message="",
            document_id=current_document_id,
            revision=make_schematic_revision(file_path, patched_text, dependency_snapshots),
            request_id=str(request_id or ""),
            component_id=str(component_id or ""),
            field_key=str(field_key or ""),
            source_text=patched_text,
            changed=True,
        )

    def _find_component(self, spice_document: SpiceDocument, component_id: str) -> Optional[SpiceComponent]:
        for component in spice_document.components:
            if component.id == component_id:
                return component
        for subcircuit in spice_document.subcircuits:
            for component in subcircuit.components:
                if component.id == component_id:
                    return component
        return None

    def _find_field(self, fields: Iterable[SpiceEditableField], field_key: str) -> Optional[SpiceEditableField]:
        for field in fields:
            if field.field_key == field_key:
                return field
        return None

    def _is_safe_single_token_text(self, text: str) -> bool:
        if not text:
            return False
        return not any(character.isspace() for character in text)

    def _reject_without_source_file(
        self,
        *,
        document_id: str,
        revision: str,
        request_id: str,
        component_id: str,
        field_key: str,
        result_type: str,
        error_message: str,
    ) -> SpiceSourcePatchResult:
        return SpiceSourcePatchResult(
            success=False,
            result_type=str(result_type or "error"),
            error_message=str(error_message or "写回失败"),
            document_id=str(document_id or ""),
            revision=str(revision or ""),
            request_id=str(request_id or ""),
            component_id=str(component_id or ""),
            field_key=str(field_key or ""),
            source_text="",
            changed=False,
        )

    def _reject(
        self,
        *,
        source_file: SpiceSourceFile,
        document_id: str,
        revision: str,
        request_id: str,
        component_id: str,
        field_key: str,
        result_type: str,
        error_message: str,
    ) -> SpiceSourcePatchResult:
        return SpiceSourcePatchResult(
            success=False,
            result_type=str(result_type or "error"),
            error_message=str(error_message or "写回失败"),
            document_id=str(document_id or ""),
            revision=str(revision or ""),
            request_id=str(request_id or ""),
            component_id=str(component_id or ""),
            field_key=str(field_key or ""),
            source_text=source_file.source_text,
            changed=False,
        )


__all__ = ["SpiceSourcePatcher", "SpiceSourcePatchResult"]
