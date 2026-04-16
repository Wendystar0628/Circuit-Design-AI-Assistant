import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from shared.path_utils import normalize_absolute_path, normalize_identity_path
from shared.workspace_file_types import (
    is_image_extension,
    is_markdown_extension,
    is_pdf_extension,
    is_tabular_extension,
    is_word_extension,
)

VIEW_KIND_CODE = "code"
VIEW_KIND_IMAGE = "image"
VIEW_KIND_MARKDOWN = "markdown"
VIEW_KIND_WORD = "word"
VIEW_KIND_PDF = "pdf"
VIEW_KIND_TABLE = "table"


def resolve_editor_view_kind(path: str) -> str:
    normalized_path = normalize_absolute_path(path)
    if is_image_extension(normalized_path):
        return VIEW_KIND_IMAGE
    if is_markdown_extension(normalized_path):
        return VIEW_KIND_MARKDOWN
    if is_word_extension(normalized_path):
        return VIEW_KIND_WORD
    if is_pdf_extension(normalized_path):
        return VIEW_KIND_PDF
    if is_tabular_extension(normalized_path):
        return VIEW_KIND_TABLE
    return VIEW_KIND_CODE


def is_view_kind_editable(view_kind: str) -> bool:
    return str(view_kind or "") == VIEW_KIND_CODE


@dataclass
class WorkspaceEditorSessionEntry:
    path: str
    identity_path: str
    name: str
    view_kind: str
    is_readonly: bool
    buffer_content: Optional[str] = None
    is_dirty: bool = False
    cursor_line: int = 1
    cursor_column: int = 1

    def to_workspace_item(
        self,
        *,
        active_identity_path: str,
        is_active_dirty: Optional[bool] = None,
    ) -> Dict[str, Any]:
        dirty = self.is_dirty if is_active_dirty is None else bool(is_active_dirty)
        return {
            "path": self.path,
            "identity_path": self.identity_path,
            "name": self.name,
            "is_dirty": dirty,
            "is_readonly": self.is_readonly,
            "is_active": self.identity_path == str(active_identity_path or ""),
        }


def build_workspace_editor_session_entry(path: str) -> WorkspaceEditorSessionEntry:
    normalized_path = normalize_absolute_path(path)
    view_kind = resolve_editor_view_kind(normalized_path)
    return WorkspaceEditorSessionEntry(
        path=normalized_path,
        identity_path=normalize_identity_path(normalized_path),
        name=os.path.basename(normalized_path),
        view_kind=view_kind,
        is_readonly=not is_view_kind_editable(view_kind),
    )
