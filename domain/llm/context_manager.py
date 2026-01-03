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

职责边界：
- 消息管理：委托给 MessageStore
- Token 监控：委托给 TokenMonitor
- 上下文压缩：委托给 ContextCompressor
- 缓存统计：委托给 CacheStatsTracker
- 会话管理：由 SessionStateManager 负责（不在本类职责范围内）

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

from langchain_core.messages import BaseMessage

from domain.llm.message_store import MessageStore
from domain.llm.token_monitor import TokenMonitor
from domain.llm.context_compressor import ContextCompressor, CompressPreview
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
    
    协调 MessageStore、TokenMonitor、ContextCompressor、CacheStatsTracker
    提供统一的对外接口。
    
    注意：会话管理（保存、加载、切换会话）由 SessionStateManager 负责，
    不在本类职责范围内。
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
        web_search_results: Optional[List[Dict[str, Any]]] = None,
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
            web_search_results: 联网搜索结果（仅助手消息）
            
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
            web_search_results=web_search_results,
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
        return self._message_store.get_langchain_messages(state, limit)
    
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
        web_search_results: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        添加助手消息（有状态版本，供 UI 层使用）
        
        Args:
            content: 消息内容
            reasoning_content: 思考内容
            tool_calls: 工具调用列表
            usage: Token 使用统计
            web_search_results: 联网搜索结果
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
            web_search_results=web_search_results,
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
        
        处理附件：
        - 图片：转换为 base64 编码的多模态内容
        - 文件：读取文件内容并添加到消息文本中
        
        Returns:
            消息列表，格式为 [{"role": str, "content": str|list}, ...]
        """
        state = self._get_internal_state()
        messages = self.get_messages(state)
        
        # 转换为 LLM API 格式
        result = []
        for msg in messages:
            llm_msg = self._convert_message_for_llm(msg)
            result.append(llm_msg)
        
        return result
    
    def _convert_message_for_llm(self, msg: BaseMessage) -> Dict[str, Any]:
        """
        将 LangChain 消息转换为 LLM API 格式
        
        Args:
            msg: LangChain BaseMessage 对象
            
        Returns:
            LLM API 格式的消息字典
        """
        from domain.llm.message_helpers import get_role, get_attachments
        
        role = get_role(msg)
        content = msg.content if isinstance(msg.content, str) else ""
        attachments = get_attachments(msg)
        
        # 如果没有附件，直接返回简单格式
        if not attachments:
            return {
                "role": role,
                "content": content,
            }
        
        # 有附件时，构建多模态内容
        content_parts = []
        file_contents = []
        
        for att in attachments:
            att_type = att.get("type", "")
            att_path = att.get("path", "")
            att_name = att.get("name", "")
            
            if att_type == "image":
                # 图片转换为 base64
                image_content = self._convert_image_to_base64(att_path)
                if image_content:
                    content_parts.append(image_content)
            elif att_type == "file":
                # 文件读取内容
                file_text = self._read_file_content(att_path, att_name)
                if file_text:
                    file_contents.append(file_text)
        
        # 构建最终内容
        if content_parts:
            # 有图片，使用多模态格式
            text_content = content
            if file_contents:
                text_content += "\n\n" + "\n\n".join(file_contents)
            
            # 图片在前，文本在后
            if text_content.strip():
                content_parts.append({"type": "text", "text": text_content})
            else:
                content_parts.append({"type": "text", "text": "请描述这张图片"})
            
            return {
                "role": role,
                "content": content_parts,
            }
        else:
            # 只有文件，添加到文本内容
            text_content = content
            if file_contents:
                text_content += "\n\n" + "\n\n".join(file_contents)
            
            return {
                "role": role,
                "content": text_content,
            }
    
    def _convert_image_to_base64(self, image_path: str) -> Optional[Dict[str, Any]]:
        """
        将图片转换为 base64 编码的多模态内容
        
        Args:
            image_path: 图片文件路径
            
        Returns:
            多模态内容字典，失败返回 None
        """
        import base64
        import os
        
        if not os.path.isfile(image_path):
            if self.logger:
                self.logger.warning(f"Image file not found: {image_path}")
            return None
        
        try:
            # 获取 MIME 类型
            ext = os.path.splitext(image_path)[1].lower()
            mime_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }
            mime_type = mime_types.get(ext, "image/png")
            
            # 检查文件大小（限制单张图片最大 10MB）
            file_size = os.path.getsize(image_path)
            if file_size > 10 * 1024 * 1024:
                if self.logger:
                    self.logger.warning(f"Image file too large: {file_size} bytes (max 10MB)")
                return None
            
            # 读取并编码
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            
            image_data = base64.b64encode(image_bytes).decode("ascii")
            data_url = f"data:{mime_type};base64,{image_data}"
            
            return {
                "type": "image_url",
                "image_url": {
                    "url": data_url
                }
            }
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to convert image to base64: {e}")
            return None
    
    def _read_file_content(self, file_path: str, file_name: str) -> Optional[str]:
        """
        读取文件内容
        
        Args:
            file_path: 文件路径
            file_name: 文件名（用于显示）
            
        Returns:
            格式化的文件内容字符串，失败返回 None
        """
        import os
        
        if not os.path.isfile(file_path):
            if self.logger:
                self.logger.warning(f"File not found: {file_path}")
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 限制文件大小
            max_chars = 50000
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (file truncated)"
            
            return f"--- File: {file_name} ---\n{content}\n--- End of {file_name} ---"
        except UnicodeDecodeError:
            return f"[Binary file attached: {file_name}]"
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to read file: {e}")
            return None
    
    def get_display_messages(self) -> List[BaseMessage]:
        """
        获取用于显示的消息列表（有状态版本）
        
        Returns:
            消息列表（LangChain BaseMessage 格式）
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
