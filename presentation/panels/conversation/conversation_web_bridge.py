from __future__ import annotations

from typing import Any, Dict, List

from PyQt6.QtCore import QObject, QJsonValue, pyqtSignal, pyqtSlot


class ConversationWebBridge(QObject):
    ready = pyqtSignal()
    surface_activation_requested = pyqtSignal(str)
    send_requested = pyqtSignal(str, dict)
    stop_requested = pyqtSignal()
    new_conversation_requested = pyqtSignal()
    history_requested = pyqtSignal()
    history_close_requested = pyqtSignal()
    history_session_selected = pyqtSignal(str)
    history_session_open_requested = pyqtSignal(str)
    history_export_dialog_open_requested = pyqtSignal(str)
    history_export_dialog_close_requested = pyqtSignal()
    history_export_format_changed = pyqtSignal(str)
    history_export_path_pick_requested = pyqtSignal()
    history_session_export_requested = pyqtSignal(str, str, str)
    history_session_delete_requested = pyqtSignal(str)
    confirm_dialog_resolved = pyqtSignal(bool)
    notice_dialog_close_requested = pyqtSignal()
    compress_requested = pyqtSignal()
    session_name_changed = pyqtSignal(str)
    suggestion_selected = pyqtSignal(str)
    rollback_requested = pyqtSignal(str)
    rollback_preview_close_requested = pyqtSignal()
    rollback_confirm_requested = pyqtSignal()
    pending_edit_accept_all_requested = pyqtSignal()
    pending_edit_reject_all_requested = pyqtSignal()
    pending_edit_file_requested = pyqtSignal(str)
    file_open_requested = pyqtSignal(str)
    link_open_requested = pyqtSignal(str)
    image_preview_requested = pyqtSignal(str)
    upload_image_requested = pyqtSignal()
    select_file_requested = pyqtSignal()
    model_config_requested = pyqtSignal()
    rag_reindex_requested = pyqtSignal()
    rag_clear_requested = pyqtSignal()
    rag_search_requested = pyqtSignal(str)
    attachments_selected = pyqtSignal(list)

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def activateSurface(self, surface_id: str) -> None:
        normalized_surface = str(surface_id or "conversation")
        if normalized_surface not in {"conversation", "rag"}:
            normalized_surface = "conversation"
        self.surface_activation_requested.emit(normalized_surface)

    def _normalize_json_payload(self, payload: Any) -> Any:
        if isinstance(payload, QJsonValue):
            payload = payload.toVariant()
        return payload

    @pyqtSlot(str, QJsonValue)
    @pyqtSlot(str, dict)
    def sendMessage(self, text: str, composer_state: Any) -> None:
        normalized_state = self._normalize_json_payload(composer_state)
        payload = normalized_state if isinstance(normalized_state, dict) else {}
        self.send_requested.emit(str(text or ""), payload)

    @pyqtSlot()
    def requestStop(self) -> None:
        self.stop_requested.emit()

    @pyqtSlot()
    def requestNewConversation(self) -> None:
        self.new_conversation_requested.emit()

    @pyqtSlot()
    def requestHistory(self) -> None:
        self.history_requested.emit()

    @pyqtSlot()
    def closeHistory(self) -> None:
        self.history_close_requested.emit()

    @pyqtSlot(str)
    def selectHistorySession(self, session_id: str) -> None:
        self.history_session_selected.emit(str(session_id or ""))

    @pyqtSlot(str)
    def openHistorySession(self, session_id: str) -> None:
        self.history_session_open_requested.emit(str(session_id or ""))

    @pyqtSlot(str)
    def openHistoryExportDialog(self, session_id: str) -> None:
        self.history_export_dialog_open_requested.emit(str(session_id or ""))

    @pyqtSlot()
    def closeHistoryExportDialog(self) -> None:
        self.history_export_dialog_close_requested.emit()

    @pyqtSlot(str)
    def setHistoryExportFormat(self, export_format: str) -> None:
        self.history_export_format_changed.emit(str(export_format or ""))

    @pyqtSlot()
    def chooseHistoryExportPath(self) -> None:
        self.history_export_path_pick_requested.emit()

    @pyqtSlot(str, str, str)
    def requestExportHistorySession(self, session_id: str, export_format: str, file_path: str) -> None:
        self.history_session_export_requested.emit(
            str(session_id or ""),
            str(export_format or ""),
            str(file_path or ""),
        )

    @pyqtSlot(str)
    def requestDeleteHistorySession(self, session_id: str) -> None:
        self.history_session_delete_requested.emit(str(session_id or ""))

    @pyqtSlot(bool)
    def resolveConfirmDialog(self, accepted: bool) -> None:
        self.confirm_dialog_resolved.emit(bool(accepted))

    @pyqtSlot()
    def closeNoticeDialog(self) -> None:
        self.notice_dialog_close_requested.emit()

    @pyqtSlot()
    def requestCompressContext(self) -> None:
        self.compress_requested.emit()

    @pyqtSlot(str)
    def renameSession(self, name: str) -> None:
        self.session_name_changed.emit(str(name or ""))

    @pyqtSlot(str)
    def selectSuggestion(self, suggestion_id: str) -> None:
        self.suggestion_selected.emit(str(suggestion_id or ""))

    @pyqtSlot(str)
    def requestRollback(self, message_id: str) -> None:
        self.rollback_requested.emit(str(message_id or ""))

    @pyqtSlot()
    def closeRollbackPreview(self) -> None:
        self.rollback_preview_close_requested.emit()

    @pyqtSlot()
    def confirmRollback(self) -> None:
        self.rollback_confirm_requested.emit()

    @pyqtSlot()
    def acceptAllPendingEdits(self) -> None:
        self.pending_edit_accept_all_requested.emit()

    @pyqtSlot()
    def rejectAllPendingEdits(self) -> None:
        self.pending_edit_reject_all_requested.emit()

    @pyqtSlot(str)
    def openPendingEditFile(self, file_path: str) -> None:
        self.pending_edit_file_requested.emit(str(file_path or ""))

    @pyqtSlot(str)
    def openFile(self, file_path: str) -> None:
        self.file_open_requested.emit(str(file_path or ""))

    @pyqtSlot(str)
    def openLink(self, url: str) -> None:
        self.link_open_requested.emit(str(url or ""))

    @pyqtSlot(str)
    def previewImage(self, image_path: str) -> None:
        self.image_preview_requested.emit(str(image_path or ""))

    @pyqtSlot()
    def requestUploadImage(self) -> None:
        self.upload_image_requested.emit()

    @pyqtSlot()
    def requestSelectFile(self) -> None:
        self.select_file_requested.emit()

    @pyqtSlot()
    def requestModelConfig(self) -> None:
        self.model_config_requested.emit()

    @pyqtSlot()
    def requestReindexKnowledge(self) -> None:
        self.rag_reindex_requested.emit()

    @pyqtSlot()
    def requestClearKnowledge(self) -> None:
        self.rag_clear_requested.emit()

    @pyqtSlot(str)
    def requestRagSearch(self, query: str) -> None:
        self.rag_search_requested.emit(str(query or ""))

    @pyqtSlot(QJsonValue)
    @pyqtSlot(list)
    def attachFiles(self, paths: List[Any]) -> None:
        normalized_input = self._normalize_json_payload(paths)
        normalized_paths = []
        for path in normalized_input or []:
            normalized = str(path or "")
            if normalized:
                normalized_paths.append(normalized)
        self.attachments_selected.emit(normalized_paths)


__all__ = ["ConversationWebBridge"]
