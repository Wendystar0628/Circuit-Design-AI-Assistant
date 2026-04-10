from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from presentation.dialogs.model_config_react_host import ModelConfigReactHost
from presentation.dialogs.model_config_state import ModelConfigDialogController
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_CONFIG_MANAGER,
    SVC_CREDENTIAL_MANAGER,
    SVC_EVENT_BUS,
    SVC_I18N_MANAGER,
    SVC_LLM_RUNTIME_CONFIG_MANAGER,
)


class ModelConfigDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._host: Optional[ModelConfigReactHost] = None
        self._controller: Optional[ModelConfigDialogController] = None
        self._setup_dialog()
        self._setup_ui()
        self._setup_controller()
        self._connect_bridge()
        if self._controller:
            self._controller.initialize()

    def _setup_dialog(self) -> None:
        self.setModal(True)
        self.setMinimumSize(QSize(860, 640))
        self.resize(960, 720)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        host = ModelConfigReactHost(self)
        layout.addWidget(host)
        self._host = host

    def _setup_controller(self) -> None:
        logger = None
        try:
            from infrastructure.utils.logger import get_logger

            logger = get_logger("model_config_dialog")
        except Exception:
            logger = None

        self._controller = ModelConfigDialogController(
            parent=self,
            config_manager=ServiceLocator.get_optional(SVC_CONFIG_MANAGER),
            llm_runtime_config_manager=ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER),
            credential_manager=ServiceLocator.get_optional(SVC_CREDENTIAL_MANAGER),
            event_bus=ServiceLocator.get_optional(SVC_EVENT_BUS),
            i18n_manager=ServiceLocator.get_optional(SVC_I18N_MANAGER),
            logger=logger,
            on_state_changed=self._set_state,
            on_accept_requested=self.accept,
            on_reject_requested=self.reject,
        )

    def _connect_bridge(self) -> None:
        if not self._host or not self._host.bridge or not self._controller:
            return
        bridge = self._host.bridge
        bridge.ready.connect(self._controller.emit_state)
        bridge.draft_update_requested.connect(self._controller.update_draft)
        bridge.tab_change_requested.connect(self._controller.select_tab)
        bridge.test_requested.connect(self._controller.request_test_connection)
        bridge.save_requested.connect(self._controller.request_save)
        bridge.cancel_requested.connect(self._controller.request_cancel)
        bridge.confirm_dialog_resolved.connect(self._controller.resolve_confirm_dialog)
        bridge.notice_dialog_close_requested.connect(self._controller.dismiss_notice)

    def _set_state(self, state: Dict[str, Any]) -> None:
        title = "Model Configuration"
        dialog_state = state.get("dialog", {}) if isinstance(state, dict) else {}
        if isinstance(dialog_state, dict):
            title = str(dialog_state.get("title") or title)
        self.setWindowTitle(title)
        if self._host:
            self._host.set_state(state)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._controller:
            self._controller.cleanup()
        if self._host:
            self._host.cleanup()
        super().closeEvent(event)


__all__ = ["ModelConfigDialog"]
