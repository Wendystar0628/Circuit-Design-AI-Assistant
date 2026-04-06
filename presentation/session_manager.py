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
from typing import Optional, Dict, Any, Tuple

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
        self._session_state = None
        self._project_service = None
        self._context_manager = None
        self._event_bus = None
        self._logger = None
        self._session_state_manager = None
        
        # 初始化仿真结果监控器
        self._initialize_simulation_result_watcher()

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
    def session_state(self):
        """延迟获取 SessionState（只读）"""
        if self._session_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                self._session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            except Exception:
                pass
        return self._session_state

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

    @property
    def session_state_manager(self):
        """延迟获取 SessionStateManager"""
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER
                self._session_state_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            except Exception:
                pass
        return self._session_state_manager

    def save_session_state(self):
        """保存会话状态（项目路径、打开的文件、对话会话）"""
        if not self.config_manager:
            return
        
        # 保存当前项目路径
        project_path = None
        if self.session_state:
            project_path = self.session_state.project_root
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

    # ============================================================
    # 完整会话恢复流程
    # ============================================================

    def restore_full_session(self):
        """
        完整的会话恢复流程（委托给 SessionStateManager）
        
        在 EVENT_STATE_PROJECT_OPENED 后调用，SessionStateManager 执行以下步骤：
        1. 读取 sessions.json 获取 current_session_id
        2. 若存在当前会话，加载会话消息并同步到 ContextManager
        3. 若不存在当前会话，创建新会话
        4. 发布 EVENT_SESSION_CHANGED 事件
        
        注意：SessionStateManager.switch_session() 和 create_session() 已内置状态同步，
        无需在此处手动同步。
        """
        if not self.session_state_manager:
            if self.logger:
                self.logger.error("SessionStateManager not available")
            return
        
        try:
            # 获取项目路径
            project_root = None
            if self.session_state:
                project_root = self.session_state.project_root
            
            if not project_root:
                if self.logger:
                    self.logger.warning("No project root available for session restore")
                return
            
            # 调用 on_app_startup 恢复会话
            # SessionStateManager 内部会同步状态到 ContextManager
            initial_state = {}
            self.session_state_manager.on_app_startup(project_root, initial_state)
            
            session_id = self.session_state_manager.get_current_session_id()
            if session_id:
                if self.logger:
                    self.logger.info(f"Session restored: {session_id}")
            else:
                if self.logger:
                    self.logger.warning("Session restore completed but no session ID")
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error restoring session: {e}")

    # ============================================================
    # 软件关闭时保存会话
    # ============================================================

    def save_current_conversation(self):
        """
        保存当前对话会话（委托给 SessionStateManager）
        
        在软件关闭时调用
        """
        if not self.session_state_manager:
            if self.logger:
                self.logger.error("SessionStateManager not available")
            return
        
        try:
            # 获取项目路径
            project_root = None
            if self.session_state:
                project_root = self.session_state.project_root
            
            if not project_root:
                if self.logger:
                    self.logger.warning("No project root available for saving conversation")
                return
            
            # 从 ContextManager 获取当前状态
            current_state = {}
            if self.context_manager:
                try:
                    current_state = self.context_manager.get_current_state()
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to get state from ContextManager: {e}")
            
            # 强制标记为脏，确保保存
            self.session_state_manager.mark_dirty()
            
            # 调用 on_app_shutdown 保存会话
            self.session_state_manager.on_app_shutdown(current_state, project_root)
            
            if self.logger:
                self.logger.info("Conversation saved")
                    
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error saving conversation: {e}")

    # ============================================================
    # 会话重命名
    # ============================================================

    def rename_session(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        """
        重命名会话（委托给 SessionStateManager）
        
        Args:
            old_name: 旧会话名称（实际上是 session_id）
            new_name: 新会话名称
            
        Returns:
            (是否成功, 消息)
        """
        if self.session_state_manager:
            try:
                # 获取项目路径
                project_root = None
                if self.session_state:
                    project_root = self.session_state.project_root
                
                if not project_root:
                    return False, "No project root available"
                
                # old_name 实际上是 session_id
                success = self.session_state_manager.rename_session(
                    project_root, old_name, new_name
                )
                
                if success:
                    if self.logger:
                        self.logger.info(f"Session renamed via SessionStateManager: {old_name} -> {new_name}")
                    return True, "Session renamed successfully"
                else:
                    return False, "Failed to rename session"
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error renaming session: {e}")
                return False, str(e)
        
        return False, "SessionStateManager not available"

    # ============================================================
    # 仿真结果监控器生命周期管理
    # ============================================================

    def _initialize_simulation_result_watcher(self):
        """
        初始化仿真结果监控器
        
        在 SessionManager 初始化时调用，启动监控器的事件订阅。
        监控器会自动响应项目打开/关闭事件。
        """
        try:
            from domain.simulation.service.simulation_result_watcher import (
                simulation_result_watcher
            )
            simulation_result_watcher.initialize()
            if self.logger:
                self.logger.info("SimulationResultWatcher initialized via SessionManager")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to initialize SimulationResultWatcher: {e}")

    def dispose(self):
        """
        释放资源
        
        在应用关闭时调用，清理所有管理的资源。
        """
        try:
            # 释放仿真结果监控器
            from domain.simulation.service.simulation_result_watcher import (
                simulation_result_watcher
            )
            simulation_result_watcher.dispose()
            if self.logger:
                self.logger.info("SimulationResultWatcher disposed via SessionManager")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to dispose SimulationResultWatcher: {e}")


__all__ = ["SessionManager"]
