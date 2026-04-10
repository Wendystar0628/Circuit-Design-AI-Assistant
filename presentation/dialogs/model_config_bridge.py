from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QJsonValue, pyqtSignal, pyqtSlot


class ModelConfigWebBridge(QObject):
    ready = pyqtSignal()
    draft_update_requested = pyqtSignal(str, str, object)
    tab_change_requested = pyqtSignal(str)
    test_requested = pyqtSignal()
    save_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    confirm_dialog_resolved = pyqtSignal(bool)
    notice_dialog_close_requested = pyqtSignal()

    def _normalize_json_payload(self, payload: Any) -> Any:
        if isinstance(payload, QJsonValue):
            return payload.toVariant()
        return payload

    @pyqtSlot()
    def markReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str, str, QJsonValue)
    @pyqtSlot(str, str, object)
    def updateDraft(self, section: str, field: str, value: Any) -> None:
        self.draft_update_requested.emit(
            str(section or ""),
            str(field or ""),
            self._normalize_json_payload(value),
        )

    @pyqtSlot(str)
    def selectTab(self, tab_id: str) -> None:
        normalized_tab_id = str(tab_id or "chat")
        if normalized_tab_id not in {"chat", "embedding"}:
            normalized_tab_id = "chat"
        self.tab_change_requested.emit(normalized_tab_id)

    @pyqtSlot()
    def requestTestConnection(self) -> None:
        self.test_requested.emit()

    @pyqtSlot()
    def requestSave(self) -> None:
        self.save_requested.emit()

    @pyqtSlot()
    def requestCancel(self) -> None:
        self.cancel_requested.emit()

    @pyqtSlot(bool)
    def resolveConfirmDialog(self, accepted: bool) -> None:
        self.confirm_dialog_resolved.emit(bool(accepted))

    @pyqtSlot()
    def closeNoticeDialog(self) -> None:
        self.notice_dialog_close_requested.emit()


__all__ = ["ModelConfigWebBridge"]
