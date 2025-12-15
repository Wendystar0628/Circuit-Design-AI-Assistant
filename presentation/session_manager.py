# Session Manager - 会话管理器
"""
会话管理器 - 负责项目路径和打开文件的保存与恢复

职责：
- 保存上次打开的项目路径
- 保存编辑器中打开的文件列表
- 恢复会话状态

设计原则：
- 单一职责：仅负责会话状态的持久化
- 延迟获取 ServiceLocator 中的服务
"""

import os
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import QTimer


class SessionManager:
    """
    会话管理器
    
    负责会话状态（项目路径、打开的文件）的保存与恢复
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

    def save_session_state(self):
        """保存会话状态（项目路径、打开的文件）"""
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


__all__ = ["SessionManager"]
