# Context Manager - Facade for Context Management
"""
上下文管理器 - 门面类，协调各子模块

职责：
- 作为门面类协调各子模块
- 提供统一的对外接口
- 管理消息、Token、缓存统计

设计原则：
- 延迟获取原则：不在 __init__ 中调用 ServiceLocator.get()
- 状态不可变：消息操作返回更新后的 state 副本
- 线程安全：内部使用 RLock 保护共享状态

职责边界：
- 消息管理：委托给 MessageStore
- Token 监控：委托给 TokenMonitor
- 缓存统计：委托给 CacheStatsTracker
- 会话文件生命周期（创建/切换/持久化）：由 SessionStateManager 负责
- 运行时内部状态（_internal_state）：由本类维护，提供无状态和有状态两种调用模式

双模式设计：
- 无状态模式：方法接受 state 参数并返回新状态副本，适用于 LangGraph 集成场景
- 有状态模式：方法直接操作内部 _internal_state，适用于 UI 层和协调器的便捷调用
  供调用方：UI 层对话面板、SessionStateManager 等需要便捷访问当前状态的场景

使用示例：
    from domain.llm.context_manager import ContextManager
    
    manager = ContextManager()
    
    # 添加消息
    new_state = manager.add_message(state, "user", "Hello")
    
    # 记录缓存统计
    manager.record_cache_stats(usage_info)
"""

import threading
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import BaseMessage

from domain.llm.message_store import MessageStore
from domain.llm.message_types import Attachment
from domain.llm.token_monitor import TokenMonitor
from domain.llm.working_context_builder import (
    WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
    WORKING_CONTEXT_KEEP_RECENT_KEY,
    WORKING_CONTEXT_SUMMARY_KEY,
    get_working_context_messages,
)
from domain.llm.cache_stats_tracker import (
    CacheStatsTracker, 
    SessionCacheStats,
    CacheEfficiencyReport,
)


# ============================================================
# 上下文管理器
# ============================================================

class ContextManager:
    """
    上下文管理器 - 门面类

    协调 MessageStore、TokenMonitor、CacheStatsTracker，
    提供统一的对外接口。

    提供两种调用模式（均可用，各自适合不同场景）：
    - 无状态模式：add_message(state, ...) 接受并返回 state，适用于 LangGraph 节点
    - 有状态模式：add_user_message() / add_assistant_message() 等直接操作内部
      _internal_state，适用于 UI 层和 SessionStateManager 等协调器

    注意：会话文件生命周期（持久化/切换/加载会话文件）由 SessionStateManager 负责；
    本类只负责运行时内存状态（_internal_state），不读写磁盘。
    """
    
    def __init__(self):
        """
        初始化上下文管理器
        """
        self._lock = threading.RLock()
        
        # 初始化子模块
        self._message_store = MessageStore()
        self._token_monitor = TokenMonitor()
        self._cache_stats_tracker = CacheStatsTracker()
        
        # 延迟获取的服务
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_manager")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to load custom logger, using stdlib: {e}")
                self._logger = logging.getLogger(__name__)
        return self._logger
    
    # ============================================================
    # 消息管理（委托给 MessageStore）
    # ============================================================
    
    def add_message(
        self,
        state: Dict[str, Any],
        role: str,
        content: str,
        attachments: Optional[List[Attachment]] = None,
        operations: Optional[List[str]] = None,
        reasoning_content: str = "",
        usage: Optional[Dict[str, int]] = None,
        web_search_results: Optional[List[Dict[str, Any]]] = None,
        is_partial: bool = False,
        stop_reason: str = "",
    ) -> Dict[str, Any]:
        """
        添加消息到状态
        
        Args:
            state: 当前状态
            role: 消息角色 ("user" | "assistant" | "system")
            content: 消息内容
            attachments: 附件列表
            operations: 操作摘要（仅助手消息）
            reasoning_content: 思考内容（仅助手消息）
            usage: Token 使用统计（仅助手消息）
            web_search_results: 联网搜索结果（仅助手消息）
            is_partial: 是否为部分响应
            stop_reason: 停止原因
            
        Returns:
            更新后的状态副本
        """
        return self._message_store.add_message(
            state=state,
            role=role,
            content=content,
            attachments=attachments,
            operations=operations,
            reasoning_content=reasoning_content,
            usage=usage,
            web_search_results=web_search_results,
            is_partial=is_partial,
            stop_reason=stop_reason,
        )
    
    def get_messages(
        self,
        state: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[BaseMessage]:
        """
        获取消息历史
        
        Args:
            state: 当前状态
            limit: 返回数量限制
            
        Returns:
            消息列表（LangChain BaseMessage 格式）
        """
        return self._message_store.get_messages(state, limit)
    
    def get_recent_messages(
        self,
        state: Dict[str, Any],
        n: int = 10
    ) -> List[BaseMessage]:
        """
        获取最近 N 条消息
        
        Args:
            state: 当前状态
            n: 返回数量
            
        Returns:
            消息列表
        """
        return self._message_store.get_recent_messages(state, n)
    
    def get_langchain_messages(
        self,
        state: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[Any]:
        """
        获取 LangChain 格式的消息
        
        Args:
            state: 当前状态
            limit: 返回数量限制
            
        Returns:
            LangChain 消息列表
        """
        # MessageStore.get_messages 已经返回 LangChain 消息
        return self._message_store.get_messages(state, limit)
    
    def classify_messages(
        self,
        state: Dict[str, Any]
    ) -> Dict[str, List[BaseMessage]]:
        """
        对消息进行重要性分级
        
        Args:
            state: 当前状态
            
        Returns:
            分级后的消息字典 {"high": [...], "medium": [...], "low": [...]} 
        """
        return self._message_store.classify_messages(state)

    # ============================================================
    # Token 监控（委托给 TokenMonitor）
    # ============================================================
    
    def calculate_usage(
        self,
        state: Dict[str, Any],
        model: str = "default",
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        计算当前 Token 占用
        
        Args:
            state: 当前状态
            model: 模型名称
            
        Returns:
            使用情况字典
        """
        return self._token_monitor.calculate_usage(state, model, provider)
    
    # ============================================================
    # 缓存统计（委托给 CacheStatsTracker）
    # ============================================================
    
    def record_cache_stats(self, usage_info: Dict[str, Any]) -> None:
        """
        记录单次请求的缓存统计
        
        Args:
            usage_info: API 返回的 usage 信息
        """
        self._cache_stats_tracker.record_cache_stats(usage_info)
    
    def get_session_cache_stats(self) -> SessionCacheStats:
        """
        获取会话级别的缓存统计
        
        Returns:
            SessionCacheStats: 会话统计对象
        """
        return self._cache_stats_tracker.get_session_cache_stats()
    
    def get_cache_hit_ratio(self) -> float:
        """
        计算缓存命中率
        
        Returns:
            缓存命中率（0.0 - 1.0）
        """
        return self._cache_stats_tracker.get_cache_hit_ratio()
    
    def reset_cache_stats(self) -> None:
        """重置缓存统计数据"""
        self._cache_stats_tracker.reset_stats()
    
    def get_cache_savings(self) -> Dict[str, Any]:
        """
        计算缓存节省的 token 数
        
        Returns:
            节省统计字典
        """
        return self._cache_stats_tracker.get_cache_savings()
    
    def get_cache_stats_by_time_window(self, seconds: float) -> SessionCacheStats:
        """
        按时间窗口统计缓存
        
        Args:
            seconds: 时间窗口大小（秒）
            
        Returns:
            时间窗口内的统计
        """
        return self._cache_stats_tracker.get_stats_by_time_window(seconds)
    
    def generate_cache_efficiency_report(
        self, 
        time_window_seconds: Optional[float] = None
    ) -> CacheEfficiencyReport:
        """
        生成缓存效率报告
        
        Args:
            time_window_seconds: 可选的时间窗口（秒）
            
        Returns:
            CacheEfficiencyReport: 效率报告
        """
        return self._cache_stats_tracker.generate_efficiency_report(time_window_seconds)

    # ============================================================
    # 有状态便捷方法（无 LangGraph 集成场景）
    # ============================================================
    # 以下方法内部维护 _internal_state，供 UI 层和协调器（如 SessionStateManager）使用。
    # 这些方法是对无状态 state 参数方法的封装，调用方无需自行持有和传递 state。
    # sync_state() 由 SessionStateManager 在会话切换/恢复时调用（领域层）；
    # add_user_message() / add_assistant_message() 等由 UI 层调用。
    
    def get_current_state(self) -> Dict[str, Any]:
        """
        获取当前内部状态（线程安全）
        
        Returns:
            当前内部状态字典，至少包含 "messages" 键
        """
        with self._lock:
            if not hasattr(self, '_internal_state'):
                self._internal_state = {
                    "messages": [],
                    WORKING_CONTEXT_SUMMARY_KEY: "",
                    WORKING_CONTEXT_COMPRESSED_COUNT_KEY: 0,
                    WORKING_CONTEXT_KEEP_RECENT_KEY: 0,
                }
            return self._internal_state
    
    def sync_state(self, state: Dict[str, Any]) -> None:
        """
        同步外部状态到内部（线程安全）
        
        供 SessionStateManager 等协调器在会话切换、恢复时调用，
        确保 ContextManager 内部状态与当前会话一致。
        
        Args:
            state: 要同步的状态字典
        """
        with self._lock:
            self._internal_state = state
    
    def add_user_message(
        self,
        content: str,
        attachments: Optional[List[Attachment]] = None
    ) -> None:
        """
        添加用户消息（有状态版本）
        
        Args:
            content: 消息内容
            attachments: 附件列表
        """
        state = self.get_current_state()
        new_state = self.add_message(
            state=state,
            role="user",
            content=content,
            attachments=attachments,
        )
        self.sync_state(new_state)
        
        if self.logger:
            self.logger.debug(f"Added user message: {content[:50]}...")
    
    def add_assistant_message(
        self,
        content: str,
        reasoning_content: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        usage: Optional[Dict[str, Any]] = None,
        web_search_results: Optional[List[Dict[str, Any]]] = None,
        is_partial: bool = False,
        stop_reason: str = "",
        operations: Optional[List[str]] = None,
    ) -> None:
        """
        添加助手消息（有状态版本）
        
        Args:
            content: 消息内容
            reasoning_content: 思考内容
            tool_calls: 工具调用列表
            usage: Token 使用统计
            web_search_results: 联网搜索结果
            is_partial: 是否为部分响应
            stop_reason: 停止原因
            operations: 操作摘要列表（直接传入，优先于 tool_calls 自动生成）
        """
        state = self.get_current_state()
        
        # 合并 operations：直接传入的优先，tool_calls 自动生成的追加
        final_operations = list(operations) if operations else []
        if tool_calls:
            for tc in tool_calls:
                func_name = tc.get("function", {}).get("name", "unknown")
                final_operations.append(f"Called: {func_name}")
        
        new_state = self.add_message(
            state=state,
            role="assistant",
            content=content,
            reasoning_content=reasoning_content,
            operations=final_operations if final_operations else None,
            usage=usage,
            web_search_results=web_search_results,
            is_partial=is_partial,
            stop_reason=stop_reason,
        )
        self.sync_state(new_state)
        
        # 记录缓存统计
        if usage:
            self.record_cache_stats(usage)
        
        if self.logger:
            self.logger.debug(f"Added assistant message: {content[:50]}...")

    def get_working_messages(self) -> List[BaseMessage]:
        state = self.get_current_state()
        return get_working_context_messages(state)

    def get_display_messages(self) -> List[BaseMessage]:
        """
        获取用于显示的消息列表（有状态版本）
        
        Returns:
            消息列表（LangChain BaseMessage 格式）
        """
        state = self.get_current_state()
        return self.get_messages(state)

# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ContextManager",
]
