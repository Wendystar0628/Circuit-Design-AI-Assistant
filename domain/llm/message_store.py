# Message Store - Message Storage and Retrieval
"""
消息存储 - 消息的存储、检索和分类

职责：
- 添加消息到状态
- 获取消息历史
- 消息重要性分级
- 部分响应处理
- 摘要管理

设计原则：
- 状态不可变：消息操作返回更新后的 state 副本
- 线程安全：内部使用 RLock 保护共享状态
- 解耦设计：通过 MessageAdapter 与 GraphState 交互，不直接操作 state["messages"]
- 禁止文件 I/O：所有文件操作由 context_service 负责

使用示例：
    from domain.llm.message_store import MessageStore
    
    store = MessageStore()
    new_state = store.add_message(state, "user", "Hello")
    messages = store.get_messages(state)
"""

import copy
import threading
from typing import Any, Dict, List, Optional, Tuple

from domain.llm.message_types import (
    Message,
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    create_user_message,
    create_assistant_message,
    create_system_message,
)
from domain.llm.message_adapter import MessageAdapter


# ============================================================
# 常量
# ============================================================

# 消息重要性级别
IMPORTANCE_HIGH = "high"
IMPORTANCE_MEDIUM = "medium"
IMPORTANCE_LOW = "low"


# ============================================================
# 消息存储
# ============================================================

class MessageStore:
    """
    消息存储管理器
    
    管理消息的存储、检索和分类。
    遵循状态不可变原则，所有操作返回新的 state 副本。
    
    解耦设计：
    - 内部操作使用 InternalMessage 格式
    - 通过 MessageAdapter 与 GraphState 交互
    - 不直接操作 state["messages"]，保持与 LangGraph 的解耦
    
    职责边界：
    - 专注 GraphState.messages 的内存操作
    - 禁止任何文件 I/O 操作（由 context_service 负责）
    """
    
    def __init__(self):
        """初始化消息存储"""
        self._lock = threading.RLock()
        self._logger = None
        self._message_adapter = MessageAdapter()
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("message_store")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 消息添加
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
        is_partial: bool = False,
        stop_reason: str = "",
        tool_calls_pending: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        添加消息到状态
        
        通过 MessageAdapter 与 GraphState 交互，保持解耦。
        
        Args:
            state: 当前状态
            role: 消息角色
            content: 消息内容
            attachments: 附件列表
            operations: 操作摘要（仅助手消息）
            reasoning_content: 思考内容（仅助手消息）
            usage: Token 使用统计（仅助手消息）
            metadata: 额外元数据
            web_search_results: 联网搜索结果（仅助手消息）
            is_partial: 是否为部分响应
            stop_reason: 停止原因
            tool_calls_pending: 中断时未完成的工具调用
            
        Returns:
            更新后的状态副本
        """
        with self._lock:
            # 创建消息（内部格式）
            if role == ROLE_USER:
                msg = create_user_message(
                    content=content,
                    attachments=attachments,
                    metadata=metadata,
                )
            elif role == ROLE_ASSISTANT:
                from domain.llm.message_types import TokenUsage
                token_usage = None
                if usage:
                    token_usage = TokenUsage.from_dict(usage)
                msg = create_assistant_message(
                    content=content,
                    reasoning_content=reasoning_content,
                    operations=operations,
                    usage=token_usage,
                    metadata=metadata,
                    web_search_results=web_search_results,
                    is_partial=is_partial,
                    stop_reason=stop_reason,
                    tool_calls_pending=tool_calls_pending,
                )
            elif role == ROLE_SYSTEM:
                msg = create_system_message(
                    content=content,
                    metadata=metadata,
                )
            else:
                raise ValueError(f"Invalid role: {role}")
            
            # 通过 MessageAdapter 追加消息到状态
            new_state = self._message_adapter.append_message_to_state(state, msg)
            
            if self.logger:
                self.logger.debug(
                    f"添加消息: role={role}, content_len={len(content)}, "
                    f"is_partial={is_partial}"
                )
            
            return new_state
    
    # ============================================================
    # 消息检索
    # ============================================================
    
    def get_messages(
        self,
        state: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[Message]:
        """
        获取消息历史
        
        通过 MessageAdapter 从 GraphState 提取消息。
        
        Args:
            state: 当前状态
            limit: 返回数量限制
            
        Returns:
            消息列表（内部格式）
        """
        with self._lock:
            # 通过 MessageAdapter 提取消息
            messages = self._message_adapter.extract_messages_from_state(state)
            
            if limit:
                messages = messages[-limit:]
            
            return messages
    
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
        return self.get_messages(state, limit=n)
    
    def get_langchain_messages(
        self,
        state: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[Any]:
        """
        获取 LangChain 格式的消息
        
        注意：此方法直接返回 GraphState 中的消息，用于需要 LangChain 格式的场景。
        
        Args:
            state: 当前状态
            limit: 返回数量限制
            
        Returns:
            LangChain 消息列表
        """
        with self._lock:
            # 获取内部消息后转换为 LangChain 格式
            messages = self._message_adapter.extract_messages_from_state(state)
            if limit:
                messages = messages[-limit:]
            return self._message_adapter.to_langchain_messages(messages)

    # ============================================================
    # 消息分类
    # ============================================================
    
    def classify_messages(
        self,
        state: Dict[str, Any]
    ) -> Dict[str, List[Message]]:
        """
        对消息进行重要性分级
        
        分级规则：
        - HIGH: 系统消息、包含操作的助手消息、最近 3 条消息
        - MEDIUM: 包含代码块的消息、较长的消息
        - LOW: 其他消息
        
        Args:
            state: 当前状态
            
        Returns:
            分级后的消息字典
        """
        with self._lock:
            messages = self.get_messages(state)
            
            result = {
                IMPORTANCE_HIGH: [],
                IMPORTANCE_MEDIUM: [],
                IMPORTANCE_LOW: [],
            }
            
            total = len(messages)
            
            for i, msg in enumerate(messages):
                importance = self._classify_single_message(msg, i, total)
                result[importance].append(msg)
            
            return result
    
    def _classify_single_message(
        self,
        msg: Message,
        index: int,
        total: int
    ) -> str:
        """分类单条消息"""
        # 系统消息始终重要
        if msg.is_system():
            return IMPORTANCE_HIGH
        
        # 最近 3 条消息重要
        if index >= total - 3:
            return IMPORTANCE_HIGH
        
        # 包含操作的助手消息重要
        if msg.is_assistant() and msg.operations:
            return IMPORTANCE_HIGH
        
        # 包含代码块的消息中等重要
        if "```" in msg.content:
            return IMPORTANCE_MEDIUM
        
        # 较长的消息中等重要
        if len(msg.content) > 500:
            return IMPORTANCE_MEDIUM
        
        return IMPORTANCE_LOW
    
    # ============================================================
    # 部分响应处理
    # ============================================================
    
    def add_partial_response(
        self,
        state: Dict[str, Any],
        content: str,
        reasoning_content: str = "",
        stop_reason: str = "user_requested",
        tool_calls_pending: Optional[List[Dict[str, Any]]] = None,
        min_length: int = 50,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        添加部分响应消息
        
        根据内容长度决定是否保存：
        - 已生成内容长度 > min_length：保存为部分响应消息
        - 已生成内容长度 ≤ min_length：丢弃，不保存
        
        Args:
            state: 当前状态
            content: 部分响应内容
            reasoning_content: 部分思考内容
            stop_reason: 停止原因
            tool_calls_pending: 中断时未完成的工具调用
            min_length: 最小保存长度（默认 50 字符）
            
        Returns:
            (更新后的状态, 是否保存)
        """
        # 检查内容长度
        if len(content) <= min_length:
            if self.logger:
                self.logger.debug(
                    f"部分响应内容过短 ({len(content)} 字符)，丢弃"
                )
            return state, False
        
        # 添加部分响应消息
        new_state = self.add_message(
            state=state,
            role=ROLE_ASSISTANT,
            content=content,
            reasoning_content=reasoning_content,
            is_partial=True,
            stop_reason=stop_reason,
            tool_calls_pending=tool_calls_pending,
        )
        
        if self.logger:
            self.logger.info(
                f"保存部分响应: content_len={len(content)}, "
                f"reasoning_len={len(reasoning_content)}, "
                f"stop_reason={stop_reason}"
            )
        
        return new_state, True
    
    def get_last_partial_message(
        self,
        state: Dict[str, Any]
    ) -> Optional[Message]:
        """
        获取最后一条部分响应消息
        
        Args:
            state: 当前状态
            
        Returns:
            Message: 部分响应消息，不存在返回 None
        """
        messages = self.get_messages(state)
        
        for msg in reversed(messages):
            if msg.is_assistant() and msg.is_partial:
                return msg
        
        return None
    
    def has_pending_partial_response(
        self,
        state: Dict[str, Any]
    ) -> bool:
        """
        检查是否有待处理的部分响应
        
        Args:
            state: 当前状态
            
        Returns:
            bool: 是否有部分响应
        """
        return self.get_last_partial_message(state) is not None
    
    def mark_partial_as_complete(
        self,
        state: Dict[str, Any],
        additional_content: str = ""
    ) -> Dict[str, Any]:
        """
        将最后一条部分响应标记为完成
        
        用于"继续生成"功能完成后。
        
        Args:
            state: 当前状态
            additional_content: 追加的内容
            
        Returns:
            更新后的状态副本
        """
        messages = self._message_adapter.extract_messages_from_state(state)
        
        # 找到最后一条部分响应
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.is_assistant() and msg.is_partial:
                # 更新消息
                msg.is_partial = False
                msg.stop_reason = ""
                if additional_content:
                    msg.content += additional_content
                break
        
        # 更新状态
        new_state = self._message_adapter.update_state_messages(state, messages)
        
        if self.logger:
            self.logger.info("部分响应已标记为完成")
        
        return new_state
    
    def remove_last_partial_response(
        self,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        移除最后一条部分响应
        
        用于"重新生成"功能。
        
        Args:
            state: 当前状态
            
        Returns:
            更新后的状态副本
        """
        messages = self._message_adapter.extract_messages_from_state(state)
        
        # 找到并移除最后一条部分响应
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.is_assistant() and msg.is_partial:
                messages.pop(i)
                break
        
        # 更新状态
        new_state = self._message_adapter.update_state_messages(state, messages)
        
        if self.logger:
            self.logger.info("部分响应已移除")
        
        return new_state

    # ============================================================
    # 摘要管理
    # ============================================================
    
    def get_summary(self, state: Dict[str, Any]) -> str:
        """
        获取当前对话摘要
        
        Args:
            state: 当前状态
            
        Returns:
            摘要文本
        """
        return state.get("conversation_summary", "")
    
    def has_summary(self, state: Dict[str, Any]) -> bool:
        """
        是否存在摘要
        
        Args:
            state: 当前状态
            
        Returns:
            是否有摘要
        """
        summary = self.get_summary(state)
        return bool(summary and summary.strip())
    
    def set_summary(
        self,
        state: Dict[str, Any],
        summary: str
    ) -> Dict[str, Any]:
        """
        设置对话摘要
        
        Args:
            state: 当前状态
            summary: 摘要文本
            
        Returns:
            更新后的状态副本
        """
        with self._lock:
            new_state = copy.deepcopy(state)
            new_state["conversation_summary"] = summary
            return new_state
    
    # ============================================================
    # 会话重置
    # ============================================================
    
    def reset_messages(
        self,
        state: Dict[str, Any],
        keep_system: bool = True
    ) -> Dict[str, Any]:
        """
        重置消息列表
        
        通过 MessageAdapter 更新 GraphState。
        
        Args:
            state: 当前状态
            keep_system: 是否保留系统消息
            
        Returns:
            更新后的状态副本
        """
        with self._lock:
            if keep_system:
                # 提取所有消息，过滤保留系统消息
                all_messages = self._message_adapter.extract_messages_from_state(state)
                system_msgs = [msg for msg in all_messages if msg.is_system()]
                # 通过 MessageAdapter 更新状态
                new_state = self._message_adapter.update_state_messages(state, system_msgs)
            else:
                # 清空所有消息
                new_state = self._message_adapter.update_state_messages(state, [])
            
            # 清空摘要
            new_state["conversation_summary"] = ""
            
            if self.logger:
                self.logger.info("消息列表已重置")
            
            return new_state


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MessageStore",
    "IMPORTANCE_HIGH",
    "IMPORTANCE_MEDIUM",
    "IMPORTANCE_LOW",
]
