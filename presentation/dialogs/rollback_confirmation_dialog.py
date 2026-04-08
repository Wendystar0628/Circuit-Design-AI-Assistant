from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.llm.conversation_rollback_service import ConversationRollbackPreview
from domain.services.snapshot_service import SnapshotFileChange


class RollbackConfirmationDialog(QDialog):
    def __init__(
        self,
        preview: ConversationRollbackPreview,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._preview = preview
        self._i18n = None
        self._workspace_changes: Dict[str, SnapshotFileChange] = {
            change.relative_path: change
            for change in preview.workspace_changed_files
        }

        self._summary_intro: Optional[QLabel] = None
        self._anchor_label: Optional[QLabel] = None
        self._message_count_label: Optional[QLabel] = None
        self._file_count_label: Optional[QLabel] = None
        self._line_stats_label: Optional[QLabel] = None
        self._file_tree: Optional[QTreeWidget] = None
        self._message_text: Optional[QTextEdit] = None
        self._detail_text: Optional[QTextEdit] = None
        self._confirm_btn: Optional[QPushButton] = None
        self._cancel_btn: Optional[QPushButton] = None

        self._setup_dialog()
        self._setup_ui()
        self.retranslate_ui()
        self._populate_data()

    @property
    def i18n(self):
        if self._i18n is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_I18N_MANAGER

                self._i18n = ServiceLocator.get_optional(SVC_I18N_MANAGER)
            except Exception:
                pass
        return self._i18n

    def _get_text(self, key: str, default: str = "") -> str:
        if self.i18n:
            return self.i18n.get_text(key, default)
        return default

    def _setup_dialog(self) -> None:
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setModal(True)
        self.setMinimumSize(980, 700)
        self.resize(1080, 760)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        summary_group = QGroupBox(self)
        summary_group.setProperty("group_type", "summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setSpacing(6)

        self._summary_intro = QLabel()
        self._summary_intro.setWordWrap(True)
        self._summary_intro.setStyleSheet(
            "QLabel { font-size: 13px; color: #1f2937; font-weight: 600; }"
        )
        summary_layout.addWidget(self._summary_intro)

        self._anchor_label = QLabel()
        self._anchor_label.setWordWrap(True)
        summary_layout.addWidget(self._anchor_label)

        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(16)

        self._message_count_label = QLabel()
        self._file_count_label = QLabel()
        self._line_stats_label = QLabel()
        for label in (
            self._message_count_label,
            self._file_count_label,
            self._line_stats_label,
        ):
            label.setStyleSheet(
                "QLabel { color: #4b5563; font-size: 12px; background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px 10px; }"
            )
            stats_row.addWidget(label)

        stats_row.addStretch()
        summary_layout.addLayout(stats_row)
        main_layout.addWidget(summary_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        files_group = QGroupBox(left_widget)
        files_group.setProperty("group_type", "files")
        files_layout = QVBoxLayout(files_group)

        self._file_tree = QTreeWidget()
        self._file_tree.setColumnCount(4)
        self._file_tree.setRootIsDecorated(False)
        self._file_tree.setAlternatingRowColors(True)
        self._file_tree.setUniformRowHeights(True)
        self._file_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._file_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._file_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._file_tree.itemSelectionChanged.connect(self._on_file_selection_changed)
        header = self._file_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        files_layout.addWidget(self._file_tree)
        left_layout.addWidget(files_group, 1)

        messages_group = QGroupBox(left_widget)
        messages_group.setProperty("group_type", "messages")
        messages_layout = QVBoxLayout(messages_group)

        self._message_text = QTextEdit()
        self._message_text.setReadOnly(True)
        self._message_text.setStyleSheet(
            "QTextEdit { background-color: #fafafa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        messages_layout.addWidget(self._message_text)
        left_layout.addWidget(messages_group, 1)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        detail_group = QGroupBox(right_widget)
        detail_group.setProperty("group_type", "detail")
        detail_layout = QVBoxLayout(detail_group)

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(
            'QTextEdit { background-color: #fafafa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace; font-size: 12px; }'
        )
        detail_layout.addWidget(self._detail_text)
        right_layout.addWidget(detail_group, 1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([420, 620])
        main_layout.addWidget(splitter, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch()

        self._cancel_btn = QPushButton(self)
        self._cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_btn)

        self._confirm_btn = QPushButton(self)
        self._confirm_btn.setDefault(True)
        self._confirm_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; border: none; border-radius: 6px; padding: 8px 16px; } QPushButton:hover { background-color: #1d4ed8; } QPushButton:pressed { background-color: #1e40af; }"
        )
        self._confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(self._confirm_btn)

        main_layout.addLayout(button_row)

    def _populate_data(self) -> None:
        self._update_summary_texts()
        self._populate_workspace_changes()
        self._populate_removed_messages()

    def _update_summary_texts(self) -> None:
        if self._summary_intro:
            self._summary_intro.setText(
                self._get_text(
                    "dialog.rollback_confirm.intro",
                    "确认后将执行节点锚点回滚，并恢复工作区与会话状态。",
                )
            )
        if self._anchor_label:
            self._anchor_label.setText(
                self._get_text(
                    "dialog.rollback_confirm.anchor",
                    "回滚锚点: {anchor}",
                ).format(anchor=self._preview.anchor_label or self._preview.anchor_message_id)
            )
        if self._message_count_label:
            self._message_count_label.setText(
                self._get_text(
                    "dialog.rollback_confirm.messages",
                    "将移除 {count} 条消息",
                ).format(count=self._preview.removed_message_count)
            )
        if self._file_count_label:
            self._file_count_label.setText(
                self._get_text(
                    "dialog.rollback_confirm.files",
                    "工作区文件变更 {count} 个",
                ).format(count=self._preview.workspace_changed_file_count)
            )
        if self._line_stats_label:
            self._line_stats_label.setText(
                self._get_text(
                    "dialog.rollback_confirm.lines",
                    "+{added} / -{deleted}",
                ).format(
                    added=self._preview.workspace_total_added_lines,
                    deleted=self._preview.workspace_total_deleted_lines,
                )
            )

    def _populate_workspace_changes(self) -> None:
        if self._file_tree is None:
            return

        self._file_tree.clear()
        if not self._preview.workspace_changed_files:
            self._detail_text.setPlainText(
                self._get_text(
                    "dialog.rollback_confirm.no_workspace_changes",
                    "此轮回滚不会修改工作区文件，只会恢复会话状态。",
                )
            )
            return

        for change in self._preview.workspace_changed_files:
            item = QTreeWidgetItem(
                [
                    change.relative_path,
                    self._format_change_type(change.change_type),
                    f"+{change.added_lines}",
                    f"-{change.deleted_lines}",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, change.relative_path)
            self._file_tree.addTopLevelItem(item)

        self._file_tree.setCurrentItem(self._file_tree.topLevelItem(0))
        self._on_file_selection_changed()

    def _populate_removed_messages(self) -> None:
        if self._message_text is None:
            return

        if not self._preview.removed_messages:
            self._message_text.setPlainText(
                self._get_text(
                    "dialog.rollback_confirm.no_messages",
                    "此轮回滚不会额外移除消息。",
                )
            )
            return

        lines = []
        for message in self._preview.removed_messages:
            role = self._format_message_role(message.role)
            timestamp = f" [{message.timestamp}]" if message.timestamp else ""
            preview = message.content_preview or self._get_text(
                "dialog.rollback_confirm.empty_message",
                "<空消息>",
            )
            lines.append(f"{role}{timestamp}\n{preview}")

        self._message_text.setPlainText("\n\n".join(lines))

    def _on_file_selection_changed(self) -> None:
        if self._file_tree is None or self._detail_text is None:
            return

        selected_items = self._file_tree.selectedItems()
        if not selected_items:
            if not self._preview.workspace_changed_files:
                return
            first_item = self._file_tree.topLevelItem(0)
            if first_item is None:
                return
            self._file_tree.setCurrentItem(first_item)
            selected_items = [first_item]

        relative_path = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        change = self._workspace_changes.get(str(relative_path or ""))
        if change is None:
            self._detail_text.clear()
            return

        detail_parts = [
            change.relative_path,
            self._format_change_type(change.change_type),
            change.summary,
            self._get_text(
                "dialog.rollback_confirm.lines",
                "+{added} / -{deleted}",
            ).format(added=change.added_lines, deleted=change.deleted_lines),
            "",
        ]
        if change.is_text and change.diff_preview:
            detail_parts.append(change.diff_preview)
        elif change.is_text:
            detail_parts.append(
                self._get_text(
                    "dialog.rollback_confirm.no_diff",
                    "该文件没有可展示的文本 diff。",
                )
            )
        else:
            detail_parts.append(
                self._get_text(
                    "dialog.rollback_confirm.binary_file",
                    "该文件不是可安全展示的文本文件，但会按快照进行恢复。",
                )
            )

        self._detail_text.setPlainText("\n".join(detail_parts))

    def _format_change_type(self, change_type: str) -> str:
        mapping = {
            "modified": self._get_text("dialog.rollback_confirm.change.modified", "修改"),
            "added": self._get_text("dialog.rollback_confirm.change.added", "恢复"),
            "deleted": self._get_text("dialog.rollback_confirm.change.deleted", "删除"),
        }
        return mapping.get(change_type, change_type)

    def _format_message_role(self, role: str) -> str:
        mapping = {
            "user": self._get_text("dialog.rollback_confirm.role.user", "用户"),
            "assistant": self._get_text("dialog.rollback_confirm.role.assistant", "助手"),
            "system": self._get_text("dialog.rollback_confirm.role.system", "系统"),
            "tool": self._get_text("dialog.rollback_confirm.role.tool", "工具"),
        }
        return mapping.get(role, role or self._get_text("dialog.rollback_confirm.role.unknown", "消息"))

    def retranslate_ui(self) -> None:
        self.setWindowTitle(
            self._get_text(
                "dialog.rollback_confirm.title",
                "确认撤回",
            )
        )

        for group in self.findChildren(QGroupBox):
            group_type = group.property("group_type")
            if group_type == "summary":
                group.setTitle(self._get_text("dialog.rollback_confirm.summary_group", "回滚概览"))
            elif group_type == "files":
                group.setTitle(self._get_text("dialog.rollback_confirm.files_group", "工作区文件变更"))
            elif group_type == "messages":
                group.setTitle(self._get_text("dialog.rollback_confirm.messages_group", "将被移除的消息"))
            elif group_type == "detail":
                group.setTitle(self._get_text("dialog.rollback_confirm.detail_group", "差异预览"))

        if self._file_tree:
            self._file_tree.setHeaderLabels(
                [
                    self._get_text("dialog.rollback_confirm.header.path", "文件"),
                    self._get_text("dialog.rollback_confirm.header.type", "类型"),
                    self._get_text("dialog.rollback_confirm.header.added", "+"),
                    self._get_text("dialog.rollback_confirm.header.deleted", "-"),
                ]
            )

        if self._cancel_btn:
            self._cancel_btn.setText(self._get_text("btn.cancel", "取消"))
        if self._confirm_btn:
            self._confirm_btn.setText(self._get_text("btn.confirm", "确认撤回"))

        self._update_summary_texts()
        self._populate_removed_messages()
        self._on_file_selection_changed()


__all__ = ["RollbackConfirmationDialog"]
