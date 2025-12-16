# Context Manager - Facade for Context Management
"""
上下文管理器 - 门面类，协调各子模块

职责：
- 作为门面类协调各子模块
- 提供统一的对外接口
- 管理消息、Token、压缩、缓存统计

设计原则：
- 延迟获取原则：不在 __init__ 中调用 ServiceLocator.get()
- 状态不可变：消息操作返回更新后的 state 副本
- 线程安全：内部使用 RLock 保护共享状态

压缩与清理：
- compress() 方法执行上下文压缩，含增强清理策略
- 增强清理策略：清理 reasoning_content、合并 operations、截断旧消息、替换摘要
- 配置项定义在 settings.py（KEEP_REASONING_RECENT_COUNT 等）

使用示例：
    from domain.llm.context_manager import ContextManager
    
    manager = ContextManager()
    
    # 添加消息
    new_state = manager.add_message(state, "user", "Hello")
    
    # 检查是否需要压缩
    if manager.should_compress(state, model):
        new_state = await manager.compress(state, llm_worker)
    
    # 记录缓存统计
    manager.record_cache_stats(usage_info)
"""

import threading
from typing import Any, Dict, List, Optional, Tuple

from domain.llm.message_store import MessageStore
from domain.llm.token_monitor import TokenMonitor
from domain.llm.context_compressor import ContextCompressor, CompressPreview
from domain.llm.cache_stats_tracker import CacheStatsTracker, SessionCacheStats
from domain.llm.message_types import Message


# ============================================================
# 上下文管理器
# ============================================================

class ContextManager:
    """
    上下文管理器 - 门面类
    
    协调 MessageStore、TokenMonitor、ContextCompressor、CacheStatsTracker
    提供统一的对外接口。
    """
    
    def __init__(self, compress_threshold: float = 0.8):
        """
        初始化上下文管理器
        
        Args:
            compress_threshold: 触发压缩的阈值（0.0 - 1.0）
        """
        self._lock = threading.RLock()
        
        # 初始化子模块
        self._message_store = MessageStore()
        self._token_monitor = TokenMonitor(compress_threshold)
        self._context_compressor = ContextCompressor()
        self._cache_stats_tracker = CacheStatsTracker()
        
        # 延迟获取的服务
        self._logger = None
        self._event_bus = None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_manager")
            except Exception:
                pass
        return self._logger
    
    @property
    def event_bus(self):
        """延迟获取事件总线"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    # ============================================================
    # 消息管理（委托给 MessageStore）
    # ============================================================
    
    def add_message(
        self,
        state: Dict[str, Any],
        role: str,
        content: str,
        attachments: Optional[List[Any]] = None,
        operations: Optional[List[str]] = None,
        reasoning_content: str = "",
        usage: Optional[Dict[str, int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
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
            metadata: 额外元数据
            
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
            metadata=metadata,
        )
    
    def get_messages(
        self,
        state: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[Message]:
        """
        获取消息历史
        
        Args:
            state: 当前状态
            limit: 返回数量限制
            
        Returns:
            消息列表（内部格式）
        """
        return self._message_store.get_messages(state, limit)
    
    def get_recent_messages(
        self,
        state: Dict[str, Any],
        n: int = 10
    ) -> List[Message]:
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
        return self._message_store.get_langchain_messages(state, limit)
    
    def classify_messages(
        self,
        state: Dict[str, Any]
    ) -> Dict[str, List[Message]]:
        """
        对消息进行重要性分级
        
        Args:
            state: 当前状态
            
        Returns:
            分级后的消息字典 {"high": [...], "medium": [...], "low": [...]}
        """
        return self._message_store.classify_messages(state)
    
    def get_summary(self, state: Dict[str, Any]) -> str:
        """
        获取当前对话摘要
        
        Args:
            state: 当前状态
            
        Returns:
            摘要文本
        """
        return self._message_store.get_summary(state)
    
    def has_summary(self, state: Dict[str, Any]) -> bool:
        """
        是否存在摘要
        
        Args:
            state: 当前状态
            
        Returns:
            是否有摘要
        """
        return self._message_store.has_summary(state)
    
    def reset_messages(
        self,
        state: Dict[str, Any],
        keep_system: bool = True
    ) -> Dict[str, Any]:
        """
        重置消息列表
        
        Args:
            state: 当前状态
            keep_system: 是否保留系统消息
            
        Returns:
            更新后的状态副本
        """
        return self._message_store.reset_messages(state, keep_system)
    
    # ============================================================
    # 会话归档（委托给 MessageStore）
    # ============================================================
    
    def archive_current_session(
        self,
        state: Dict[str, Any],
        project_path: str
    ) -> Tuple[bool, str]:
        """
        归档当前对话
        
        Args:
            state: 当前状态
            project_path: 项目路径
            
        Returns:
            (是否成功, 消息或会话ID)
        """
        return self._message_store.archive_current_session(state, project_path)
    
    def get_archived_sessions(self, project_path: str) -> List[Dict[str, Any]]:
        """
        获取已归档的对话列表
        
        Args:
            project_path: 项目路径
            
        Returns:
            归档会话列表
        """
        return self._message_store.get_archived_sessions(project_path)
    
    def restore_session(
        self,
        session_id: str,
        project_path: str,
        state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        从归档恢复对话
        
        Args:
            session_id: 会话 ID
            project_path: 项目路径
            state: 当前状态
            
        Returns:
            (更新后的状态, 是否成功, 消息)
        """
        return self._message_store.restore_session(session_id, project_path, state)
    
    def export_session(
        self,
        state: Dict[str, Any],
        path: str,
        format: str = "json"
    ) -> Tuple[bool, str]:
        """
        导出会话
        
        Args:
            state: 当前状态
            path: 导出路径
            format: 导出格式
            
        Returns:
            (是否成功, 消息)
        """
        return self._message_store.export_session(state, path, format)
    
    def import_session(
        self,
        path: str,
        state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        导入历史会话
        
        Args:
            path: 导入路径
            state: 当前状态
            
        Returns:
            (更新后的状态, 是否成功, 消息)
        """
        return self._message_store.import_session(path, state)
    
    # ============================================================
    # Token 监控（委托给 TokenMonitor）
    # ============================================================
    
    def calculate_usage(
        self,
        state: Dict[str, Any],
        model: str = "default"
    ) -> Dict[str, Any]:
        """
        计算当前 Token 占用
        
        Args:
            state: 当前状态
            model: 模型名称
            
        Returns:
            使用情况字典
        """
        return self._token_monitor.calculate_usage(state, model)
    
    def get_usage_ratio(
        self,
        state: Dict[str, Any],
        model: str = "default"
    ) -> float:
        """
        获取占用比例
        
        Args:
            state: 当前状态
            model: 模型名称
            
        Returns:
            占用比例（0.0 - 1.0）
        """
        return self._token_monitor.get_usage_ratio(state, model)
    
    def should_compress(
        self,
        state: Dict[str, Any],
        model: str = "default",
        threshold: Optional[float] = None
    ) -> bool:
        """
        判断是否需要压缩上下文
        
        Args:
            state: 当前状态
            model: 模型名称
            threshold: 自定义阈值
            
        Returns:
            是否需要压缩
        """
        return self._token_monitor.should_compress(state, model, threshold)
    
    def get_model_limit(self, model: str = "default") -> int:
        """
        获取模型上下文限制
        
        Args:
            model: 模型名称
            
        Returns:
            上下文限制（tokens）
        """
        return self._token_monitor.get_model_limit(model)
    
    # ============================================================
    # 上下文压缩（委托给 ContextCompressor）
    # ============================================================
    
    def generate_compress_preview(
        self,
        state: Dict[str, Any],
        keep_recent: int = 5,
        model: str = "default"
    ) -> CompressPreview:
        """
        生成压缩预览
        
        Args:
            state: 当前状态
            keep_recent: 保留的最近消息数
            model: 模型名称
            
        Returns:
            CompressPreview: 压缩预览信息
        """
        return self._context_compressor.generate_compress_preview(
            state, keep_recent, model
        )
    
    async def compress(
        self,
        state: Dict[str, Any],
        llm_worker: Any,
        keep_recent: int = 5
    ) -> Dict[str, Any]:
        """
        执行压缩操作
        
        Args:
            state: 当前状态
            llm_worker: LLM Worker 实例
            keep_recent: 保留的最近消息数
            
        Returns:
            更新后的状态副本
        """
        return await self._context_compressor.compress(
            state, llm_worker, keep_recent
        )
    
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
    
    # ============================================================
    # 便捷方法（基于 state 参数）
    # ============================================================
    
    def get_context_status(
        self,
        state: Dict[str, Any],
        model: str = "default"
    ) -> Dict[str, Any]:
        """
        获取上下文状态摘要
        
        Args:
            state: 当前状态
            model: 模型名称
            
        Returns:
            状态摘要字典
        """
        usage = self.calculate_usage(state, model)
        cache_stats = self.get_session_cache_stats()
        messages = self.get_messages(state)
        
        return {
            "message_count": len(messages),
            "token_usage": usage,
            "has_summary": self.has_summary(state),
            "should_compress": self.should_compress(state, model),
            "cache_stats": cache_stats.to_dict(),
        }

    # ============================================================
    # 有状态便捷方法（供 UI 层使用）
    # ============================================================
    # 以下方法内部维护一个默认 state，供不需要 LangGraph 集成的场景使用
    # 这些方法是对基于 state 参数方法的封装，简化 UI 层调用
    
    def _get_internal_state(self) -> Dict[str, Any]:
        """获取内部状态（线程安全）"""
        with self._lock:
            if not hasattr(self, '_internal_state'):
                self._internal_state = {"messages": []}
            return self._internal_state
    
    def _set_internal_state(self, state: Dict[str, Any]) -> None:
        """设置内部状态（线程安全）"""
        with self._lock:
            self._internal_state = state
    
    def add_user_message(
        self,
        content: str,
        attachments: Optional[List[Any]] = None
    ) -> None:
        """
        添加用户消息（有状态版本，供 UI 层使用）
        
        Args:
            content: 消息内容
            attachments: 附件列表
        """
        state = self._get_internal_state()
        new_state = self.add_message(
            state=state,
            role="user",
            content=content,
            attachments=attachments,
        )
        self._set_internal_state(new_state)
        
        if self.logger:
            self.logger.debug(f"Added user message: {content[:50]}...")
    
    def add_assistant_message(
        self,
        content: str,
        reasoning_content: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        添加助手消息（有状态版本，供 UI 层使用）
        
        Args:
            content: 消息内容
            reasoning_content: 思考内容
            tool_calls: 工具调用列表
            usage: Token 使用统计
        """
        state = self._get_internal_state()
        
        # 提取 operations（如果有 tool_calls）
        operations = []
        if tool_calls:
            for tc in tool_calls:
                func_name = tc.get("function", {}).get("name", "unknown")
                operations.append(f"Called: {func_name}")
        
        new_state = self.add_message(
            state=state,
            role="assistant",
            content=content,
            reasoning_content=reasoning_content,
            operations=operations if operations else None,
            usage=usage,
        )
        self._set_internal_state(new_state)
        
        # 记录缓存统计
        if usage:
            self.record_cache_stats(usage)
        
        if self.logger:
            self.logger.debug(f"Added assistant message: {content[:50]}...")
    
    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """
        获取用于 LLM 调用的消息列表（有状态版本）
        
        Returns:
            消息列表，格式为 [{"role": str, "content": str}, ...]
        """
        state = self._get_internal_state()
        messages = self.get_messages(state)
        
        # 转换为 LLM API 格式
        result = []
        for msg in messages:
            result.append({
                "role": msg.role,
                "content": msg.content,
            })
        
        return result
    
    def get_display_messages(self) -> List[Message]:
        """
        获取用于显示的消息列表（有状态版本）
        
        Returns:
            消息列表（内部 Message 格式）
        """
        state = self._get_internal_state()
        return self.get_messages(state)
    
    def get_usage_ratio_stateful(self, model: str = "default") -> float:
        """
        获取占用比例（有状态版本）
        
        Args:
            model: 模型名称
            
        Returns:
            占用比例（0.0 - 1.0）
        """
        state = self._get_internal_state()
        return self.get_usage_ratio(state, model)
    
    def request_compress(self) -> None:
        """
        请求压缩上下文（发布事件，由 UI 层处理）
        
        此方法发布 EVENT_CONTEXT_COMPRESS_REQUESTED 事件，
        由 MainWindow 或其他组件监听并打开压缩对话框。
        """
        if self.event_bus:
            try:
                from shared.event_types import EVENT_CONTEXT_COMPRESS_REQUESTED
                self.event_bus.publish(EVENT_CONTEXT_COMPRESS_REQUESTED, {
                    "source": "context_manager",
                })
            except ImportError:
                if self.logger:
                    self.logger.warning("EVENT_CONTEXT_COMPRESS_REQUESTED not defined")
        
        if self.logger:
            self.logger.info("Context compress requested")
    
    def archive_and_reset(self) -> bool:
        """
        归档当前对话并重置（有状态版本）
        
        Returns:
            是否成功
        """
        state = self._get_internal_state()
        
        # 获取项目路径
        project_path = ""
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_APP_STATE
            app_state = ServiceLocator.get_optional(SVC_APP_STATE)
            if app_state:
                project_path = app_state.current_project_path or ""
        except Exception:
            pass
        
        # 归档
        if project_path:
            success, msg = self.archive_current_session(state, project_path)
            if not success:
                if self.logger:
                    self.logger.warning(f"Archive failed: {msg}")
        
        # 重置
        new_state = self.reset_messages(state, keep_system=True)
        self._set_internal_state(new_state)
        
        if self.logger:
            self.logger.info("Conversation archived and reset")
        
        return True
    
    def refresh_display(self) -> None:
        """
        刷新显示（发布事件通知 UI 更新）
        """
        if self.event_bus:
            try:
                from shared.event_types import EVENT_CONVERSATION_UPDATED
                self.event_bus.publish(EVENT_CONVERSATION_UPDATED, {
                    "source": "context_manager",
                })
            except ImportError:
                pass


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ContextManager",
]
