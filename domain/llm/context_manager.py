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
    # 便捷方法
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
# 模块导出
# ============================================================

__all__ = [
    "ContextManager",
]
