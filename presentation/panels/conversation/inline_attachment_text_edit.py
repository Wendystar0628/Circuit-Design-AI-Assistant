from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QTextCharFormat, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QTextEdit

from domain.llm.attachment_references import build_inline_attachment_marker
from domain.llm.message_types import Attachment

ATTACHMENT_REFERENCE_PROPERTY = int(QTextFormat.Property.UserProperty) + 1
ATTACHMENT_NAME_PROPERTY = int(QTextFormat.Property.UserProperty) + 2
ATTACHMENT_PATH_PROPERTY = int(QTextFormat.Property.UserProperty) + 3


class InlineAttachmentTextEdit(QTextEdit):
    inline_attachment_removed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_cursor_position = 0
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)

    def insert_inline_attachment(self, attachment: Attachment) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        if cursor.position() > 0:
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 1)
            previous_text = cursor.selectedText()
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.MoveOperation.Right)
            if previous_text and not previous_text.isspace():
                cursor.insertText(" ")
        char_format = QTextCharFormat()
        char_format.setForeground(QColor("#1f4b99"))
        char_format.setBackground(QColor("#dbeafe"))
        char_format.setProperty(ATTACHMENT_REFERENCE_PROPERTY, attachment.reference_id)
        char_format.setProperty(ATTACHMENT_NAME_PROPERTY, attachment.name)
        char_format.setProperty(ATTACHMENT_PATH_PROPERTY, attachment.path)
        char_format.setToolTip(attachment.path)
        text = f"[{attachment.name}]"
        cursor.insertText(text, char_format)
        cursor.insertText(" ")
        self.setTextCursor(cursor)

    def serialize_content(self) -> str:
        document = self.document()
        parts: list[str] = []
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    ref_id = fragment.charFormat().property(ATTACHMENT_REFERENCE_PROPERTY)
                    if isinstance(ref_id, str) and ref_id:
                        name = fragment.charFormat().property(ATTACHMENT_NAME_PROPERTY)
                        parts.append(build_inline_attachment_marker(ref_id, str(name or fragment.text().strip("[]"))))
                    else:
                        parts.append(fragment.text())
                iterator += 1
            block = block.next()
            if block.isValid():
                parts.append("\n")
        return "".join(parts)

    def remove_inline_attachment(self, reference_id: str) -> bool:
        attachment_range = self._find_attachment_range(reference_id)
        if attachment_range is None:
            return False
        start, end, _ = attachment_range
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        if cursor.position() < self.document().characterCount() - 1:
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
            if cursor.selectedText() == " ":
                cursor.removeSelectedText()
        self.setTextCursor(cursor)
        cursor.endEditBlock()
        return True

    def clear_inline_attachments(self) -> None:
        reference_ids: list[str] = []
        document = self.document()
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    ref_id = fragment.charFormat().property(ATTACHMENT_REFERENCE_PROPERTY)
                    if isinstance(ref_id, str) and ref_id and ref_id not in reference_ids:
                        reference_ids.append(ref_id)
                iterator += 1
            block = block.next()
        for reference_id in reference_ids:
            self.remove_inline_attachment(reference_id)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in {Qt.Key.Key_Backspace, Qt.Key.Key_Delete}:
            if self._remove_attachment_near_cursor(backspace=key == Qt.Key.Key_Backspace):
                return
        cursor = self.textCursor()
        attachment_range = self._get_attachment_range_at_position(cursor.position())
        if attachment_range is not None and event.text() and not cursor.hasSelection():
            cursor.setPosition(attachment_range[1])
            self.setTextCursor(cursor)
        super().keyPressEvent(event)

    def _remove_attachment_near_cursor(self, *, backspace: bool) -> bool:
        cursor = self.textCursor()
        position = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        if backspace and position > 0:
            attachment_range = self._get_attachment_range_at_position(position - 1)
        else:
            attachment_range = self._get_attachment_range_at_position(position)
        if attachment_range is None:
            return False
        start, end, reference_id = attachment_range
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        if cursor.position() < self.document().characterCount() - 1:
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
            if cursor.selectedText() == " ":
                cursor.removeSelectedText()
        self.setTextCursor(cursor)
        cursor.endEditBlock()
        if reference_id:
            self.inline_attachment_removed.emit(reference_id)
        return True

    def _on_cursor_position_changed(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            self._last_cursor_position = cursor.position()
            return
        attachment_range = self._get_attachment_range_at_position(cursor.position())
        if attachment_range is None:
            self._last_cursor_position = cursor.position()
            return
        start, end, _ = attachment_range
        new_position = end if cursor.position() >= self._last_cursor_position else start
        if cursor.position() == new_position:
            self._last_cursor_position = cursor.position()
            return
        cursor.setPosition(new_position)
        self.blockSignals(True)
        self.setTextCursor(cursor)
        self.blockSignals(False)
        self._last_cursor_position = new_position

    def _get_attachment_range_at_position(self, position: int):
        document = self.document()
        block = document.begin()
        global_pos = 0
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    length = len(fragment.text())
                    start = global_pos
                    end = global_pos + length
                    ref_id = fragment.charFormat().property(ATTACHMENT_REFERENCE_PROPERTY)
                    if isinstance(ref_id, str) and ref_id and start <= position < end:
                        return start, end, ref_id
                    global_pos = end
                iterator += 1
            if block.next().isValid():
                global_pos += 1
            block = block.next()
        return None

    def _find_attachment_range(self, reference_id: str):
        document = self.document()
        block = document.begin()
        global_pos = 0
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    length = len(fragment.text())
                    start = global_pos
                    end = global_pos + length
                    ref_id = fragment.charFormat().property(ATTACHMENT_REFERENCE_PROPERTY)
                    if ref_id == reference_id:
                        return start, end, ref_id
                    global_pos = end
                iterator += 1
            if block.next().isValid():
                global_pos += 1
            block = block.next()
        return None
