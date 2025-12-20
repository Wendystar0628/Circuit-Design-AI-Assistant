# Tab Controller
"""
标签页控制器

职责：
- 管理右栏标签页的切换逻辑
- 徽章显示（未读消息等）
- 自动切换策略

设计原则：
- 标签页通过 tab_id 唯一标识
- 支持徽章显示和自动清除
- 可配置的自动切换策略

被调用方：
- main_window.py
- 各面板 ViewModel
"""

from typing import Optional, Dict, Callable, Any
from enum import Enum, auto

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QTabWidget, QWidget


# ============================================================
# 标签页 ID 常量
# ============================================================

TAB_CONVERSATION = "TAB_CONVERSATION"
TAB_INFO = "TAB_INFO"
TAB_DEVTOOLS = "TAB_DEVTOOLS"
TAB_COMPONENT = "TAB_COMPONENT"


# ============================================================
# 自动切换策略
# ============================================================

class AutoSwitchPolicy(Enum):
    """自动切换策略"""
    NONE = auto()                    # 不自动切换
    ON_NEW_MESSAGE = auto()          # 收到新消息时切换到对话
    ON_SIMULATION_COMPLETE = auto()  # 仿真完成时切换到信息
    ON_SEARCH_RESULT = auto()        # 搜索结果返回时切换到信息


class TabController(QObject):
    """
    标签页控制器
    
    管理右栏标签页的切换、徽章显示、自动切换策略
    
    使用示例：
        tab_controller = TabController()
        tab_controller.bind_tab_widget(tab_widget)
        tab_controller.register_tab(TAB_CONVERSATION, chat_panel, "对话", "icons/chat.svg")
        tab_controller.switch_to_tab(TAB_CONVERSATION)
        tab_controller.set_badge(TAB_INFO, 3)
    """
    
    # 标签页切换信号（previous_tab, current_tab）
    tab_changed = pyqtSignal(str, str)
    
    def __init__(self):
        super().__init__()
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 绑定的 QTabWidget
        self._tab_widget: Optional[QTabWidget] = None
        
        # 标签页注册表：tab_id -> TabInfo
        self._tabs: Dict[str, "TabInfo"] = {}
        
        # tab_id 到 QTabWidget 索引的映射
        self._tab_indices: Dict[str, int] = {}
        
        # 当前标签页 ID
        self._current_tab: Optional[str] = None
        
        # 徽章计数：tab_id -> count
        self._badges: Dict[str, int] = {}
        
        # 自动切换策略集合
        self._auto_switch_policies: set = set()
    
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
                self._logger = get_logger("tab_controller")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 绑定 QTabWidget
    # ============================================================
    
    def bind_tab_widget(self, tab_widget: QTabWidget):
        """
        绑定 QTabWidget 实例
        
        Args:
            tab_widget: 要绑定的 QTabWidget
        """
        if self._tab_widget is not None:
            # 断开旧连接
            try:
                self._tab_widget.currentChanged.disconnect(self._on_tab_index_changed)
            except Exception:
                pass
        
        self._tab_widget = tab_widget
        
        # 连接信号
        self._tab_widget.currentChanged.connect(self._on_tab_index_changed)
        
        if self.logger:
            self.logger.debug("TabWidget bound to TabController")
    
    def _on_tab_index_changed(self, index: int):
        """QTabWidget 索引变化处理"""
        # 查找对应的 tab_id
        new_tab_id = None
        for tab_id, tab_index in self._tab_indices.items():
            if tab_index == index:
                new_tab_id = tab_id
                break
        
        if new_tab_id is None:
            return
        
        previous_tab = self._current_tab
        self._current_tab = new_tab_id
        
        # 切换到该标签页时自动清除徽章
        self.clear_badge(new_tab_id)
        
        # 发射信号
        self.tab_changed.emit(previous_tab or "", new_tab_id)
        
        # 发布事件
        self._publish_tab_changed(previous_tab, new_tab_id)
    
    # ============================================================
    # 标签页注册
    # ============================================================
    
    def register_tab(
        self,
        tab_id: str,
        widget: QWidget,
        title: str,
        icon_path: str = "",
    ):
        """
        注册标签页
        
        Args:
            tab_id: 标签页唯一标识
            widget: 标签页内容 QWidget
            title: 标签页标题
            icon_path: 标签页图标路径
        """
        if self._tab_widget is None:
            if self.logger:
                self.logger.warning("Cannot register tab: TabWidget not bound")
            return
        
        # 创建标签页信息
        tab_info = TabInfo(
            tab_id=tab_id,
            widget=widget,
            title=title,
            icon_path=icon_path,
        )
        
        # 添加到 QTabWidget
        if icon_path:
            try:
                from PyQt6.QtGui import QIcon
                icon = QIcon(icon_path)
                index = self._tab_widget.addTab(widget, icon, title)
            except Exception:
                index = self._tab_widget.addTab(widget, title)
        else:
            index = self._tab_widget.addTab(widget, title)
        
        # 记录映射
        self._tabs[tab_id] = tab_info
        self._tab_indices[tab_id] = index
        
        # 初始化徽章
        self._badges[tab_id] = 0
        
        # 设置第一个注册的标签页为当前标签页
        if self._current_tab is None:
            self._current_tab = tab_id
        
        if self.logger:
            self.logger.debug(f"Tab '{tab_id}' registered at index {index}")
    
    def unregister_tab(self, tab_id: str):
        """
        注销标签页
        
        Args:
            tab_id: 标签页唯一标识
        """
        if tab_id not in self._tabs:
            return
        
        if self._tab_widget is not None:
            index = self._tab_indices.get(tab_id)
            if index is not None:
                self._tab_widget.removeTab(index)
                # 更新其他标签页的索引
                self._rebuild_tab_indices()
        
        del self._tabs[tab_id]
        self._tab_indices.pop(tab_id, None)
        self._badges.pop(tab_id, None)
        
        if self._current_tab == tab_id:
            self._current_tab = next(iter(self._tabs.keys()), None)
        
        if self.logger:
            self.logger.debug(f"Tab '{tab_id}' unregistered")
    
    def _rebuild_tab_indices(self):
        """重建标签页索引映射"""
        if self._tab_widget is None:
            return
        
        self._tab_indices.clear()
        for i in range(self._tab_widget.count()):
            widget = self._tab_widget.widget(i)
            for tab_id, tab_info in self._tabs.items():
                if tab_info.widget is widget:
                    self._tab_indices[tab_id] = i
                    break
    
    # ============================================================
    # 标签页切换
    # ============================================================
    
    def switch_to_tab(self, tab_id: str) -> bool:
        """
        切换到指定标签页
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            是否切换成功
        """
        if tab_id not in self._tabs:
            if self.logger:
                self.logger.warning(f"Tab '{tab_id}' not found")
            return False
        
        if self._tab_widget is None:
            return False
        
        index = self._tab_indices.get(tab_id)
        if index is None:
            return False
        
        self._tab_widget.setCurrentIndex(index)
        return True
    
    def get_current_tab(self) -> Optional[str]:
        """
        获取当前标签页 ID
        
        Returns:
            当前标签页 ID，无则返回 None
        """
        return self._current_tab
    
    def get_tab_widget(self, tab_id: str) -> Optional[QWidget]:
        """
        获取标签页的 QWidget
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            标签页 QWidget，不存在则返回 None
        """
        tab_info = self._tabs.get(tab_id)
        return tab_info.widget if tab_info else None
    
    # ============================================================
    # 徽章管理
    # ============================================================
    
    def set_badge(self, tab_id: str, count: int):
        """
        设置标签页徽章数字
        
        Args:
            tab_id: 标签页唯一标识
            count: 徽章数字（0 表示清除）
        """
        if tab_id not in self._tabs:
            return
        
        self._badges[tab_id] = max(0, count)
        self._update_tab_text(tab_id)
        
        if self.logger and count > 0:
            self.logger.debug(f"Tab '{tab_id}' badge set to {count}")
    
    def increment_badge(self, tab_id: str, delta: int = 1):
        """
        增加标签页徽章数字
        
        Args:
            tab_id: 标签页唯一标识
            delta: 增加量
        """
        current = self._badges.get(tab_id, 0)
        self.set_badge(tab_id, current + delta)
    
    def clear_badge(self, tab_id: str):
        """
        清除标签页徽章
        
        Args:
            tab_id: 标签页唯一标识
        """
        if self._badges.get(tab_id, 0) > 0:
            self._badges[tab_id] = 0
            self._update_tab_text(tab_id)
            
            if self.logger:
                self.logger.debug(f"Tab '{tab_id}' badge cleared")
    
    def get_badge(self, tab_id: str) -> int:
        """
        获取标签页徽章数字
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            徽章数字
        """
        return self._badges.get(tab_id, 0)
    
    def _update_tab_text(self, tab_id: str):
        """更新标签页显示文本（含徽章）"""
        if self._tab_widget is None:
            return
        
        tab_info = self._tabs.get(tab_id)
        if not tab_info:
            return
        
        index = self._tab_indices.get(tab_id)
        if index is None:
            return
        
        badge_count = self._badges.get(tab_id, 0)
        
        if badge_count > 0:
            # 显示带徽章的标题
            display_text = f"{tab_info.title} ({badge_count})"
        else:
            display_text = tab_info.title
        
        self._tab_widget.setTabText(index, display_text)
    
    # ============================================================
    # 自动切换策略
    # ============================================================
    
    def set_auto_switch_policy(self, policy: AutoSwitchPolicy, enabled: bool = True):
        """
        设置自动切换策略
        
        Args:
            policy: 自动切换策略
            enabled: 是否启用
        """
        if enabled:
            self._auto_switch_policies.add(policy)
        else:
            self._auto_switch_policies.discard(policy)
        
        if self.logger:
            action = "enabled" if enabled else "disabled"
            self.logger.debug(f"Auto switch policy {policy.name} {action}")
    
    def is_policy_enabled(self, policy: AutoSwitchPolicy) -> bool:
        """
        检查策略是否启用
        
        Args:
            policy: 自动切换策略
            
        Returns:
            是否启用
        """
        return policy in self._auto_switch_policies
    
    def trigger_auto_switch(self, policy: AutoSwitchPolicy):
        """
        触发自动切换（如果策略启用）
        
        Args:
            policy: 触发的策略
        """
        if policy not in self._auto_switch_policies:
            return
        
        target_tab = self._get_target_tab_for_policy(policy)
        if target_tab and target_tab != self._current_tab:
            self.switch_to_tab(target_tab)
            
            if self.logger:
                self.logger.debug(f"Auto switched to '{target_tab}' by policy {policy.name}")
    
    def _get_target_tab_for_policy(self, policy: AutoSwitchPolicy) -> Optional[str]:
        """根据策略获取目标标签页"""
        policy_targets = {
            AutoSwitchPolicy.ON_NEW_MESSAGE: TAB_CONVERSATION,
            AutoSwitchPolicy.ON_SIMULATION_COMPLETE: TAB_INFO,
            AutoSwitchPolicy.ON_SEARCH_RESULT: TAB_INFO,
        }
        return policy_targets.get(policy)
    
    # ============================================================
    # 事件发布
    # ============================================================
    
    def _publish_tab_changed(self, previous_tab: Optional[str], current_tab: str):
        """发布标签页切换事件"""
        if not self.event_bus:
            return
        
        from shared.event_types import EVENT_TAB_CHANGED
        
        self.event_bus.publish(EVENT_TAB_CHANGED, {
            "previous_tab": previous_tab or "",
            "current_tab": current_tab,
        })
    
    # ============================================================
    # 标签页标题更新
    # ============================================================
    
    def update_tab_title(self, tab_id: str, title: str):
        """
        更新标签页标题
        
        Args:
            tab_id: 标签页唯一标识
            title: 新标题
        """
        tab_info = self._tabs.get(tab_id)
        if not tab_info:
            return
        
        tab_info.title = title
        self._update_tab_text(tab_id)
    
    def retranslate_tabs(self, title_getter: Callable[[str], str]):
        """
        刷新所有标签页标题（国际化）
        
        Args:
            title_getter: 获取标题的函数，接收 title_key 返回翻译后的标题
        """
        for tab_id, tab_info in self._tabs.items():
            if tab_info.title_key:
                new_title = title_getter(tab_info.title_key)
                tab_info.title = new_title
                self._update_tab_text(tab_id)


class TabInfo:
    """标签页信息"""
    
    def __init__(
        self,
        tab_id: str,
        widget: QWidget,
        title: str,
        icon_path: str = "",
        title_key: str = "",
    ):
        self.tab_id = tab_id
        self.widget = widget
        self.title = title
        self.icon_path = icon_path
        self.title_key = title_key


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TabController",
    "TabInfo",
    "AutoSwitchPolicy",
    "TAB_CONVERSATION",
    "TAB_INFO",
    "TAB_DEVTOOLS",
    "TAB_COMPONENT",
]
