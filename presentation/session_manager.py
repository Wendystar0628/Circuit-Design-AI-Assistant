# Session Manager - 会话管理器
"""
会话管理器 - 负责项目路径、打开文件和对话会话的保存与恢复

职责：
- 保存上次打开的项目路径
- 保存编辑器中打开的文件列表
- 保存和恢复对话会话状态
- 恢复会话状态

设计原则：
- 单一职责：仅负责会话状态的持久化
- 延迟获取 ServiceLocator 中的服务
- 编辑器会话在阶段一实现，对话会话在阶段三扩展
"""

import os
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import QTimer


class SessionManager:
    """
    会话管理器
    
    负责会话状态（项目路径、打开的文件、对话会话）的保存与恢复
    """

    def __init__(self, main_window: QMainWindow, panels: Dict[str, Any]):
        """
        初始化会话管理器
        
        Args:
            main_window: 主窗口引用
            panels: 面板字典
        """
        self._main_window = main_window
        self._panels = panels
        self._config_manager = None
        self._app_state = None
        self._project_service = None
        self._context_manager = None
        self._event_bus = None
        self._logger = None

    @property
    def config_manager(self):
        """延迟获取 ConfigManager"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager


    @property
    def app_state(self):
        """延迟获取 AppState"""
        if self._app_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_APP_STATE
                self._app_state = ServiceLocator.get_optional(SVC_APP_STATE)
            except Exception:
                pass
        return self._app_state

    @property
    def project_service(self):
        """延迟获取 ProjectService"""
        if self._project_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_PROJECT_SERVICE
                self._project_service = ServiceLocator.get_optional(SVC_PROJECT_SERVICE)
            except Exception:
                pass
        return self._project_service

    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("session_manager")
            except Exception:
                pass
        return self._logger

    @property
    def context_manager(self):
        """延迟获取 ContextManager"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager

    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    def save_session_state(self):
        """保存会话状态（项目路径、打开的文件、对话会话）"""
        if not self.config_manager:
            return
        
        # 保存当前项目路径
        project_path = None
        if self.app_state:
            from shared.app_state import STATE_PROJECT_PATH
            project_path = self.app_state.get(STATE_PROJECT_PATH)
        self.config_manager.set("last_project_path", project_path)
        
        # 保存编辑器中打开的文件列表和当前激活的标签页
        if "code_editor" in self._panels:
            editor_panel = self._panels["code_editor"]
            if hasattr(editor_panel, 'get_open_files'):
                open_files = editor_panel.get_open_files()
                self.config_manager.set("open_files", open_files)
            if hasattr(editor_panel, 'get_current_file'):
                current_file = editor_panel.get_current_file()
                self.config_manager.set("active_file", current_file)
        
        # 保存对话会话信息
        self._save_conversation_session()

    def restore_session_state(self, open_project_callback):
        """
        恢复会话状态（项目路径、打开的文件）
        
        Args:
            open_project_callback: 打开项目的回调函数
        """
        if not self.config_manager:
            return
        
        # 恢复上次打开的项目
        last_project = self.config_manager.get("last_project_path")
        if last_project and os.path.isdir(last_project):
            open_project_callback(last_project)
            
            # 延迟恢复打开的文件（等待项目初始化完成）
            QTimer.singleShot(200, self._restore_open_files)
        else:
            # 无项目时清空保存的文件列表
            self.config_manager.set("open_files", [])
            self.config_manager.set("active_file", None)

    def _restore_open_files(self):
        """恢复编辑器中打开的文件"""
        if not self.config_manager:
            return
        
        # 获取保存的文件列表
        open_files = self.config_manager.get("open_files", [])
        active_file = self.config_manager.get("active_file")
        
        if not open_files or "code_editor" not in self._panels:
            return
        
        editor_panel = self._panels["code_editor"]
        
        # 依次打开文件
        for file_path in open_files:
            if file_path and os.path.isfile(file_path):
                editor_panel.load_file(file_path)
        
        # 切换到上次激活的文件
        if active_file and os.path.isfile(active_file):
            if hasattr(editor_panel, 'switch_to_file'):
                editor_panel.switch_to_file(active_file)
        
        # 延迟重置所有文件的修改状态（确保 UI 完全加载后执行）
        QTimer.singleShot(100, lambda: self._reset_all_modification_states(editor_panel))

    def _reset_all_modification_states(self, editor_panel):
        """重置所有打开文件的修改状态"""
        if hasattr(editor_panel, 'reset_all_modification_states'):
            editor_panel.reset_all_modification_states()

    # ============================================================
    # 对话会话管理（阶段三扩展）
    # ============================================================

    def _save_conversation_session(self):
        """保存对话会话信息"""
        if not self.config_manager:
            return
        
        # 获取当前会话信息
        chat_panel = self._panels.get("chat")
        if chat_panel and hasattr(chat_panel, 'view_model'):
            view_model = chat_panel.view_model
            if view_model:
                session_id = getattr(view_model, 'current_session_id', None)
                session_name = getattr(view_model, 'current_session_name', None)
                if session_id:
                    self.config_manager.set("current_conversation_id", session_id)
                if session_name:
                    self.config_manager.set("current_conversation_name", session_name)

    def restore_conversation_session(self):
        """
        恢复对话会话状态
        
        在 EVENT_INIT_COMPLETE 后调用，此时 ContextManager 已可用
        """
        if not self.config_manager:
            return
        
        # 获取保存的会话信息
        session_id = self.config_manager.get("current_conversation_id")
        session_name = self.config_manager.get("current_conversation_name")
        
        if not session_id:
            if self.logger:
                self.logger.debug("No saved conversation session to restore")
            return
        
        # 获取项目路径
        project_path = None
        if self.app_state:
            from shared.app_state import STATE_PROJECT_PATH
            project_path = self.app_state.get(STATE_PROJECT_PATH)
        
        if not project_path:
            if self.logger:
                self.logger.debug("No project path, skip conversation restore")
            return
        
        # 通过 ContextManager 恢复会话
        if self.context_manager:
            try:
                state = self.context_manager._get_internal_state()
                new_state, success, msg = self.context_manager.restore_session(
                    session_id, project_path, state
                )
                if success:
                    self.context_manager._set_internal_state(new_state)
                    if self.logger:
                        self.logger.info(f"Conversation session restored: {session_id}")
                    
                    # 发布会话加载事件
                    self._publish_session_loaded_event(session_id, session_name)
                    
                    # 刷新对话面板
                    self._refresh_chat_panel()
                else:
                    if self.logger:
                        self.logger.warning(f"Failed to restore session: {msg}")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error restoring conversation session: {e}")

    def _publish_session_loaded_event(self, session_id: str, session_name: Optional[str]):
        """发布会话加载事件"""
        if self.event_bus:
            try:
                from shared.event_types import EVENT_SESSION_LOADED
                self.event_bus.publish(EVENT_SESSION_LOADED, {
                    "session_id": session_id,
                    "session_name": session_name or "新对话",
                    "message_count": 0,
                    "is_new": False,
                })
            except ImportError:
                pass

    def _refresh_chat_panel(self):
        """刷新对话面板显示"""
        chat_panel = self._panels.get("chat")
        if chat_panel and hasattr(chat_panel, 'refresh_display'):
            chat_panel.refresh_display()

    def get_current_session_name(self) -> Optional[str]:
        """获取当前会话名称"""
        chat_panel = self._panels.get("chat")
        if chat_panel and hasattr(chat_panel, 'view_model'):
            view_model = chat_panel.view_model
            if view_model:
                return getattr(view_model, 'current_session_name', None)
        return None

    def set_current_session_name(self, name: str):
        """设置当前会话名称"""
        chat_panel = self._panels.get("chat")
        if chat_panel and hasattr(chat_panel, 'view_model'):
            view_model = chat_panel.view_model
            if view_model and hasattr(view_model, 'set_session_name'):
                view_model.set_session_name(name)


__all__ = ["SessionManager"]
