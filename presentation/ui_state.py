# UI State - Pure UI State Container
"""
纯 UI 状态容器

职责：
- 管理纯 UI 状态（窗口布局、面板可见性、编辑器状态）
- 不影响业务逻辑
- 状态变更自动发布事件

初始化顺序：
- Phase 2.2，在 MainWindow 创建时初始化

设计原则：
- 仅存储 UI 相关状态，不存储业务状态
- 业务状态（如当前项目、工作模式）由 SessionState 管理
- UI 组件可直接读写此状态

三层状态分离架构：
- Layer 1: UIState (Presentation) - 纯 UI 状态，本模块
- Layer 2: SessionState (Application) - GraphState 的只读投影
- Layer 3: GraphState (Domain) - LangGraph 工作流的唯一真理来源

使用示例：
    from presentation.ui_state import UIState
    
    ui_state = UIState()
    
    # 读取状态
    current_tab = ui_state.get("current_tab")
    
    # 设置状态
    ui_state.set("current_tab", "conversation")
    
    # 订阅状态变更
    ui_state.subscribe_change("current_tab", on_tab_changed)
"""

import threading
from typing import Any, Callable, Dict, List, Optional

from shared.event_types import (
    EVENT_PANEL_VISIBILITY_CHANGED,
    EVENT_TAB_CHANGED,
)


# ============================================================
# 状态字段常量
# ============================================================

# 窗口状态
UI_WINDOW_GEOMETRY = "window_geometry"
UI_WINDOW_STATE = "window_state"

# 面板可见性
UI_PANEL_VISIBILITY = "panel_visibility"

# 标签页状态
UI_CURRENT_TAB = "current_tab"
UI_PREVIOUS_TAB = "previous_tab"

# 编辑器状态
UI_EDITOR_CURSOR_POSITIONS = "editor_cursor_positions"
UI_EDITOR_SCROLL_POSITIONS = "editor_scroll_positions"
UI_EDITOR_OPEN_FILES = "editor_open_files"
UI_EDITOR_ACTIVE_FILE = "editor_active_file"

# 对话面板状态
UI_INPUT_DRAFT = "input_draft"
UI_IS_GENERATING = "is_generating"

# 文件浏览器状态
UI_FILE_BROWSER_EXPANDED = "file_browser_expanded"

# 调试面板状态
UI_DEVTOOLS_VISIBLE = "devtools_visible"


# 状态字段到事件的映射
UI_STATE_EVENT_MAP = {
    UI_PANEL_VISIBILITY: EVENT_PANEL_VISIBILITY_CHANGED,
    UI_CURRENT_TAB: EVENT_TAB_CHANGED,
}


# 状态变更处理器类型
UIStateChangeHandler = Callable[[str, Any, Any], None]  # (key, old_value, new_value)


# ============================================================
# UI 状态容器
# ============================================================

class UIState:
    """
    纯 UI 状态容器
    
    管理窗口布局、面板可见性、编辑器状态等纯 UI 状态。
    不影响业务逻辑，业务状态由 SessionState 管理。
    """

    def __init__(self):
        # 状态存储
        self._state: Dict[str, Any] = self._get_default_state()
        
        # 状态变更订阅者：{key: [handler1, handler2, ...]}
        self._subscribers: Dict[str, List[UIStateChangeHandler]] = {}
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 事件级联防护
        self._is_dispatching = False
        self._pending_changes: List[tuple] = []
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None

    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            # 窗口状态
            UI_WINDOW_GEOMETRY: None,
            UI_WINDOW_STATE: None,
            # 面板可见性
            UI_PANEL_VISIBILITY: {
                "file_browser": True,
                "code_editor": True,
                "conversation": True,
                "simulation_results": True,
            },
            # 标签页状态
            UI_CURRENT_TAB: "conversation",
            UI_PREVIOUS_TAB: None,
            # 编辑器状态
            UI_EDITOR_CURSOR_POSITIONS: {},  # {file_path: cursor_position}
            UI_EDITOR_SCROLL_POSITIONS: {},  # {file_path: scroll_position}
            UI_EDITOR_OPEN_FILES: [],  # [file_path, ...]
            UI_EDITOR_ACTIVE_FILE: None,
            # 对话面板状态
            UI_INPUT_DRAFT: "",
            UI_IS_GENERATING: False,
            # 文件浏览器状态
            UI_FILE_BROWSER_EXPANDED: {},  # {folder_path: is_expanded}
            # 调试面板状态
            UI_DEVTOOLS_VISIBLE: False,
        }

    # ============================================================
    # 延迟获取服务
    # ============================================================

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
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("ui_state")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 状态读取
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取状态值
        
        Args:
            key: 状态键
            default: 默认值（键不存在时返回）
            
        Returns:
            状态值
        """
        with self._lock:
            return self._state.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """获取所有状态（副本）"""
        with self._lock:
            return self._state.copy()

    # ============================================================
    # 状态写入
    # ============================================================

    def set(self, key: str, value: Any) -> None:
        """
        设置状态值
        
        自动发布状态变更事件。
        
        Args:
            key: 状态键
            value: 状态值
        """
        with self._lock:
            old_value = self._state.get(key)
            
            # 值未变化，跳过
            if old_value == value:
                return
            
            self._state[key] = value
            
            if self.logger:
                self.logger.debug(f"UIState '{key}' changed: {old_value} -> {value}")
        
        # 触发变更通知（锁外执行，避免死锁）
        self._notify_change(key, old_value, value)

    def update(self, updates: Dict[str, Any]) -> None:
        """
        批量更新状态
        
        Args:
            updates: 状态更新字典
        """
        changes = []
        
        with self._lock:
            for key, value in updates.items():
                old_value = self._state.get(key)
                if old_value != value:
                    self._state[key] = value
                    changes.append((key, old_value, value))
        
        # 批量触发变更通知
        for key, old_value, new_value in changes:
            self._notify_change(key, old_value, new_value)

    def reset(self) -> None:
        """重置所有状态为默认值"""
        with self._lock:
            self._state = self._get_default_state()
            
            if self.logger:
                self.logger.info("UIState reset to defaults")

    # ============================================================
    # 状态订阅
    # ============================================================

    def subscribe_change(self, key: str, handler: UIStateChangeHandler) -> None:
        """
        订阅特定状态变更
        
        Args:
            key: 状态键
            handler: 变更处理函数，签名为 (key, old_value, new_value) -> None
        """
        if not callable(handler):
            raise ValueError(f"Handler must be callable: {handler}")
        
        with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = []
            
            if handler not in self._subscribers[key]:
                self._subscribers[key].append(handler)

    def unsubscribe_change(self, key: str, handler: UIStateChangeHandler) -> bool:
        """
        取消订阅状态变更
        
        Args:
            key: 状态键
            handler: 要取消的处理函数
            
        Returns:
            bool: 是否成功取消
        """
        with self._lock:
            if key in self._subscribers:
                try:
                    self._subscribers[key].remove(handler)
                    return True
                except ValueError:
                    pass
        return False

    # ============================================================
    # 变更通知
    # ============================================================

    def _notify_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """
        通知状态变更
        
        包含事件级联防护机制。
        """
        # 事件级联防护
        if self._is_dispatching:
            self._pending_changes.append((key, old_value, new_value))
            return
        
        self._is_dispatching = True
        
        try:
            # 通知订阅者
            self._dispatch_to_subscribers(key, old_value, new_value)
            
            # 发布 EventBus 事件
            self._publish_state_event(key, old_value, new_value)
            
            # 处理待处理的变更
            while self._pending_changes:
                pending = self._pending_changes.copy()
                self._pending_changes.clear()
                
                for p_key, p_old, p_new in pending:
                    self._dispatch_to_subscribers(p_key, p_old, p_new)
                    self._publish_state_event(p_key, p_old, p_new)
        finally:
            self._is_dispatching = False

    def _dispatch_to_subscribers(self, key: str, old_value: Any, new_value: Any) -> None:
        """分发变更到订阅者"""
        with self._lock:
            handlers = self._subscribers.get(key, []).copy()
        
        for handler in handlers:
            try:
                handler(key, old_value, new_value)
            except Exception as e:
                if self.logger:
                    handler_name = getattr(handler, '__name__', str(handler))
                    self.logger.error(
                        f"UIState change handler '{handler_name}' failed for '{key}': {e}"
                    )

    def _publish_state_event(self, key: str, old_value: Any, new_value: Any) -> None:
        """发布状态变更事件到 EventBus"""
        if self.event_bus is None:
            return
        
        event_type = UI_STATE_EVENT_MAP.get(key)
        if event_type:
            try:
                self.event_bus.publish(
                    event_type,
                    {"key": key, "old_value": old_value, "new_value": new_value},
                    source="ui_state"
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to publish UI state event: {e}")

    # ============================================================
    # 便捷属性
    # ============================================================

    @property
    def current_tab(self) -> str:
        """当前标签页"""
        return self.get(UI_CURRENT_TAB, "conversation")

    @current_tab.setter
    def current_tab(self, value: str) -> None:
        """设置当前标签页"""
        old_tab = self.get(UI_CURRENT_TAB)
        self.set(UI_PREVIOUS_TAB, old_tab)
        self.set(UI_CURRENT_TAB, value)

    @property
    def is_generating(self) -> bool:
        """是否正在生成"""
        return self.get(UI_IS_GENERATING, False)

    @is_generating.setter
    def is_generating(self, value: bool) -> None:
        """设置生成状态"""
        self.set(UI_IS_GENERATING, value)

    @property
    def active_editor_file(self) -> Optional[str]:
        """当前编辑器打开的文件"""
        return self.get(UI_EDITOR_ACTIVE_FILE)

    @active_editor_file.setter
    def active_editor_file(self, value: Optional[str]) -> None:
        """设置当前编辑器打开的文件"""
        self.set(UI_EDITOR_ACTIVE_FILE, value)

    # ============================================================
    # 编辑器状态管理
    # ============================================================

    def save_editor_cursor(self, file_path: str, position: int) -> None:
        """保存编辑器光标位置"""
        positions = self.get(UI_EDITOR_CURSOR_POSITIONS, {}).copy()
        positions[file_path] = position
        self.set(UI_EDITOR_CURSOR_POSITIONS, positions)

    def get_editor_cursor(self, file_path: str) -> int:
        """获取编辑器光标位置"""
        positions = self.get(UI_EDITOR_CURSOR_POSITIONS, {})
        return positions.get(file_path, 0)

    def save_editor_scroll(self, file_path: str, position: int) -> None:
        """保存编辑器滚动位置"""
        positions = self.get(UI_EDITOR_SCROLL_POSITIONS, {}).copy()
        positions[file_path] = position
        self.set(UI_EDITOR_SCROLL_POSITIONS, positions)

    def get_editor_scroll(self, file_path: str) -> int:
        """获取编辑器滚动位置"""
        positions = self.get(UI_EDITOR_SCROLL_POSITIONS, {})
        return positions.get(file_path, 0)

    # ============================================================
    # 面板可见性管理
    # ============================================================

    def set_panel_visible(self, panel_id: str, visible: bool) -> None:
        """设置面板可见性"""
        visibility = self.get(UI_PANEL_VISIBILITY, {}).copy()
        visibility[panel_id] = visible
        self.set(UI_PANEL_VISIBILITY, visibility)

    def is_panel_visible(self, panel_id: str) -> bool:
        """获取面板可见性"""
        visibility = self.get(UI_PANEL_VISIBILITY, {})
        return visibility.get(panel_id, True)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "UIState",
    "UIStateChangeHandler",
    # 状态字段常量
    "UI_WINDOW_GEOMETRY",
    "UI_WINDOW_STATE",
    "UI_PANEL_VISIBILITY",
    "UI_CURRENT_TAB",
    "UI_PREVIOUS_TAB",
    "UI_EDITOR_CURSOR_POSITIONS",
    "UI_EDITOR_SCROLL_POSITIONS",
    "UI_EDITOR_OPEN_FILES",
    "UI_EDITOR_ACTIVE_FILE",
    "UI_INPUT_DRAFT",
    "UI_IS_GENERATING",
    "UI_FILE_BROWSER_EXPANDED",
    "UI_DEVTOOLS_VISIBLE",
]
