# Tab Controller - 标签页控制器
"""
标签页控制器 - 管理右栏标签页的切换逻辑、徽章显示、自动切换策略

职责：
- 注册和管理标签页
- 控制标签页切换
- 管理徽章显示（未读消息等）
- 实现自动切换策略

设计原则：
- 统一标签页管理：右栏标签页通过 TabController 统一管理
- 事件驱动：标签切换时发布事件
- 策略模式：支持多种自动切换策略

被调用方：main_window.py、各面板 ViewModel
"""

from enum import Enum
from typing import Optional, Dict, Any, Callable
from PyQt6.QtWidgets import QTabWidget, QWidget
from PyQt6.QtGui import QIcon


class TabId(Enum):
    """标签页 ID 定义"""
    CONVERSATION = "conversation"   # 对话标签页
    INFO = "info"                   # 信息标签页
    COMPONENT = "component"         # 元器件标签页（阶段十）


class AutoSwitchPolicy(Enum):
    """自动切换策略"""
    NONE = "none"                           # 不自动切换
    ON_NEW_MESSAGE = "on_new_message"       # 收到新消息时切换到对话
    ON_SIMULATION_COMPLETE = "on_sim_complete"  # 仿真完成时切换到信息
    ON_SEARCH_RESULT = "on_search_result"   # 搜索结果返回时切换到信息


class TabController:
    """
    标签页控制器
    
    管理右栏标签页的切换逻辑、徽章显示、自动切换策略。
    """
    
    def __init__(self, tab_widget: Optional[QTabWidget] = None):
        """
        初始化标签页控制器
        
        Args:
            tab_widget: QTabWidget 实例（可延迟设置）
        """
        self._tab_widget = tab_widget
        
        # 标签页注册表：tab_id -> (widget, title, icon, index)
        self._tabs: Dict[str, tuple] = {}
        
        # 徽章计数：tab_id -> count
        self._badges: Dict[str, int] = {}
        
        # 自动切换策略
        self._auto_switch_policy = AutoSwitchPolicy.NONE
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 连接标签切换信号
        if self._tab_widget:
            self._tab_widget.currentChanged.connect(self._on_tab_changed)
    
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
    # 标签页管理
    # ============================================================
    
    def set_tab_widget(self, tab_widget: QTabWidget) -> None:
        """
        设置 QTabWidget 实例
        
        Args:
            tab_widget: QTabWidget 实例
        """
        self._tab_widget = tab_widget
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
    
    def register_tab(
        self, 
        tab_id: str, 
        widget: QWidget, 
        title: str, 
        icon: Optional[QIcon] = None
    ) -> int:
        """
        注册标签页
        
        Args:
            tab_id: 标签页唯一标识
            widget: 标签页内容组件
            title: 标签页标题
            icon: 标签页图标（可选）
            
        Returns:
            标签页索引
        """
        if not self._tab_widget:
            return -1
        
        # 添加到 QTabWidget
        if icon:
            index = self._tab_widget.addTab(widget, icon, title)
        else:
            index = self._tab_widget.addTab(widget, title)
        
        # 注册到内部表
        self._tabs[tab_id] = (widget, title, icon, index)
        self._badges[tab_id] = 0
        
        if self.logger:
            self.logger.debug(f"Tab registered: {tab_id} at index {index}")
        
        return index
    
    def unregister_tab(self, tab_id: str) -> bool:
        """
        注销标签页
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            是否成功
        """
        if tab_id not in self._tabs:
            return False
        
        if self._tab_widget:
            _, _, _, index = self._tabs[tab_id]
            self._tab_widget.removeTab(index)
            
            # 更新其他标签页的索引
            for tid, (w, t, i, idx) in self._tabs.items():
                if idx > index:
                    self._tabs[tid] = (w, t, i, idx - 1)
        
        del self._tabs[tab_id]
        del self._badges[tab_id]
        
        if self.logger:
            self.logger.debug(f"Tab unregistered: {tab_id}")
        
        return True
    
    # ============================================================
    # 标签页切换
    # ============================================================
    
    def switch_to_tab(self, tab_id: str) -> bool:
        """
        切换到指定标签页
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            是否成功
        """
        if tab_id not in self._tabs or not self._tab_widget:
            return False
        
        _, _, _, index = self._tabs[tab_id]
        self._tab_widget.setCurrentIndex(index)
        
        # 切换时清除徽章
        self.clear_badge(tab_id)
        
        return True
    
    def get_current_tab(self) -> Optional[str]:
        """
        获取当前标签页 ID
        
        Returns:
            当前标签页 ID，无则返回 None
        """
        if not self._tab_widget:
            return None
        
        current_index = self._tab_widget.currentIndex()
        for tab_id, (_, _, _, index) in self._tabs.items():
            if index == current_index:
                return tab_id
        
        return None
    
    def _on_tab_changed(self, index: int) -> None:
        """标签页切换事件处理"""
        # 查找切换前后的标签页 ID
        previous_tab = None
        current_tab = None
        
        for tab_id, (_, _, _, idx) in self._tabs.items():
            if idx == index:
                current_tab = tab_id
                break
        
        # 清除当前标签页的徽章
        if current_tab:
            self.clear_badge(current_tab)
        
        # 发布事件
        if self.event_bus:
            try:
                from shared.event_types import EVENT_TAB_CHANGED
                self.event_bus.publish(EVENT_TAB_CHANGED, {
                    "previous_tab": previous_tab,
                    "current_tab": current_tab,
                })
            except Exception:
                pass
    
    # ============================================================
    # 徽章管理
    # ============================================================
    
    def set_badge(self, tab_id: str, count: int) -> None:
        """
        设置标签页徽章数字
        
        Args:
            tab_id: 标签页唯一标识
            count: 徽章数字（0 表示清除）
        """
        if tab_id not in self._tabs:
            return
        
        self._badges[tab_id] = count
        self._update_tab_text(tab_id)
    
    def increment_badge(self, tab_id: str) -> int:
        """
        增加标签页徽章数字
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            新的徽章数字
        """
        if tab_id not in self._tabs:
            return 0
        
        # 如果当前标签页是活跃的，不增加徽章
        if self.get_current_tab() == tab_id:
            return 0
        
        self._badges[tab_id] = self._badges.get(tab_id, 0) + 1
        self._update_tab_text(tab_id)
        
        return self._badges[tab_id]
    
    def clear_badge(self, tab_id: str) -> None:
        """
        清除标签页徽章
        
        Args:
            tab_id: 标签页唯一标识
        """
        if tab_id not in self._tabs:
            return
        
        self._badges[tab_id] = 0
        self._update_tab_text(tab_id)
    
    def get_badge(self, tab_id: str) -> int:
        """
        获取标签页徽章数字
        
        Args:
            tab_id: 标签页唯一标识
            
        Returns:
            徽章数字
        """
        return self._badges.get(tab_id, 0)
    
    def _update_tab_text(self, tab_id: str) -> None:
        """更新标签页文本（含徽章）"""
        if tab_id not in self._tabs or not self._tab_widget:
            return
        
        _, title, _, index = self._tabs[tab_id]
        count = self._badges.get(tab_id, 0)
        
        if count > 0:
            display_text = f"{title} ({count})"
        else:
            display_text = title
        
        self._tab_widget.setTabText(index, display_text)
    
    # ============================================================
    # 自动切换策略
    # ============================================================
    
    def set_auto_switch_policy(self, policy: AutoSwitchPolicy) -> None:
        """
        设置自动切换策略
        
        Args:
            policy: 自动切换策略
        """
        self._auto_switch_policy = policy
    
    def get_auto_switch_policy(self) -> AutoSwitchPolicy:
        """
        获取当前自动切换策略
        
        Returns:
            当前策略
        """
        return self._auto_switch_policy
    
    def handle_event_for_auto_switch(self, event_type: str) -> None:
        """
        根据事件类型执行自动切换
        
        Args:
            event_type: 事件类型
        """
        if self._auto_switch_policy == AutoSwitchPolicy.NONE:
            return
        
        # 根据策略和事件类型决定是否切换
        try:
            from shared.event_types import (
                EVENT_MESSAGE_RECEIVED,
                EVENT_SIMULATION_COMPLETE,
                EVENT_RAG_SEARCH_COMPLETE,
            )
            
            if (self._auto_switch_policy == AutoSwitchPolicy.ON_NEW_MESSAGE 
                and event_type == EVENT_MESSAGE_RECEIVED):
                self.switch_to_tab(TabId.CONVERSATION.value)
            
            elif (self._auto_switch_policy == AutoSwitchPolicy.ON_SIMULATION_COMPLETE 
                  and event_type == EVENT_SIMULATION_COMPLETE):
                self.switch_to_tab(TabId.INFO.value)
            
            elif (self._auto_switch_policy == AutoSwitchPolicy.ON_SEARCH_RESULT 
                  and event_type == EVENT_RAG_SEARCH_COMPLETE):
                self.switch_to_tab(TabId.INFO.value)
                
        except Exception:
            pass
    
    # ============================================================
    # 标签页标题更新（国际化支持）
    # ============================================================
    
    def update_tab_title(self, tab_id: str, title: str) -> None:
        """
        更新标签页标题
        
        Args:
            tab_id: 标签页唯一标识
            title: 新标题
        """
        if tab_id not in self._tabs:
            return
        
        widget, _, icon, index = self._tabs[tab_id]
        self._tabs[tab_id] = (widget, title, icon, index)
        self._update_tab_text(tab_id)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TabController",
    "TabId",
    "AutoSwitchPolicy",
]
