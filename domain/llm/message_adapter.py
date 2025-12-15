# Message Adapter - Message Format Adapter Layer
"""
消息格式适配层 - 内部消息格式与 LangChain/GraphState 消息格式之间的适配

职责：
- 隔离 ContextManager 与 LangGraph 的实现细节
- 提供内部消息格式与 LangChain 消息格式的双向转换
- 当 LangGraph API 变化时，只需修改此适配层

设计目标：
- ContextManager 及其子模块只操作内部消息格式（InternalMessage/Message）
- 与 GraphState 交互时，通过 MessageAdapter 进行双向转换
- LangGraph API 变化时，只需修改此适配层，不影响其他模块

使用示例：
    from domain.llm.message_adapter import MessageAdapter
    
    adapter = MessageAdapter()
    
    # 从 GraphState 提取消息
    internal_msgs = adapter.extract_messages_from_state(state)
    
    # 更新 GraphState 中的消息
    new_state = adapter.update_state_messages(state, internal_msgs)
    
    # 单条消息转换
    lc_msg = adapter.to_langchain_message(internal_msg)
    internal_msg = adapter.from_langchain_message(lc_msg)
"""

import copy
from typing import Any, Dict, List, Optional

from domain.llm.message_types import (
    Message,
    TokenUsage,
    Attachment,
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
)


# ============================================================
# 消息适配器
# ============================================================

class MessageAdapter:
    """
    消息格式适配器
    
    作为内部消息格式与 LangChain/GraphState 消息格式之间的桥梁，
    隔离 LangGraph 的实现细节。
    """
    
    def __init__(self):
        """初始化适配器"""
        self._logger = None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("message_adapter")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # GraphState 交互方法
    # ============================================================
    
    def extract_messages_from_state(
        self,
        state: Dict[str, Any]
    ) -> List[Message]:
        """
        从 GraphState 提取消息并转换为内部格式
        
        Args:
            state: GraphState 状态字典
            
        Returns:
            内部格式的消息列表
        """
        lc_messages = state.get("messages", [])
        return self.from_langchain_messages(lc_messages)
    
    def update_state_messages(
        self,
        state: Dict[str, Any],
        internal_messages: List[Message]
    ) -> Dict[str, Any]:
        """
        将内部消息转换并更新到 GraphState
        
        Args:
            state: 当前 GraphState 状态
            internal_messages: 内部格式的消息列表
            
        Returns:
            更新后的状态副本
        """
        new_state = copy.deepcopy(state)
        new_state["messages"] = self.to_langchain_messages(internal_messages)
        return new_state
    
    def append_message_to_state(
        self,
        state: Dict[str, Any],
        message: Message
    ) -> Dict[str, Any]:
        """
        向 GraphState 追加一条消息
        
        Args:
            state: 当前 GraphState 状态
            message: 要追加的内部格式消息
            
        Returns:
            更新后的状态副本
        """
        new_state = copy.deepcopy(state)
        
        if "messages" not in new_state:
            new_state["messages"] = []
        
        lc_msg = self.to_langchain_message(message)
        new_state["messages"].append(lc_msg)
        
        return new_state
    
    # ============================================================
    # 批量转换方法
    # ============================================================
    
    def to_langchain_messages(
        self,
        internal_messages: List[Message]
    ) -> List[Any]:
        """
        批量转换内部消息为 LangChain 消息列表
        
        Args:
            internal_messages: 内部格式的消息列表
            
        Returns:
            LangChain 消息列表
        """
        return [self.to_langchain_message(msg) for msg in internal_messages]
    
    def from_langchain_messages(
        self,
        lc_messages: List[Any]
    ) -> List[Message]:
        """
        批量转换 LangChain 消息为内部消息列表
        
        Args:
            lc_messages: LangChain 消息列表
            
        Returns:
            内部格式的消息列表
        """
        return [self.from_langchain_message(msg) for msg in lc_messages]
    
    # ============================================================
    # 单条消息转换方法
    # ============================================================
    
    def to_langchain_message(self, msg: Message) -> Any:
        """
        单条消息转换（内部 → LangChain）
        
        Args:
            msg: 内部消息对象
            
        Returns:
            LangChain 消息对象（HumanMessage/AIMessage/SystemMessage）
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        # 构建 additional_kwargs 保存扩展字段
        additional_kwargs = {
            "timestamp": msg.timestamp,
            "metadata": msg.metadata,
        }
        
        # 附件
        if msg.attachments:
            additional_kwargs["attachments"] = [a.to_dict() for a in msg.attachments]
        
        # 助手消息特有字段
        if msg.role == ROLE_ASSISTANT:
            additional_kwargs["operations"] = msg.operations
            additional_kwargs["reasoning_content"] = msg.reasoning_content
            if msg.usage:
                additional_kwargs["usage"] = msg.usage.to_dict()
        
        # 根据角色创建对应的 LangChain 消息
        if msg.role == ROLE_USER:
            return HumanMessage(
                content=msg.content,
                additional_kwargs=additional_kwargs,
            )
        elif msg.role == ROLE_ASSISTANT:
            return AIMessage(
                content=msg.content,
                additional_kwargs=additional_kwargs,
            )
        elif msg.role == ROLE_SYSTEM:
            return SystemMessage(
                content=msg.content,
                additional_kwargs=additional_kwargs,
            )
        else:
            raise ValueError(f"Unknown role: {msg.role}")
    
    def from_langchain_message(self, lc_msg: Any) -> Message:
        """
        单条消息转换（LangChain → 内部）
        
        Args:
            lc_msg: LangChain 消息对象
            
        Returns:
            内部消息对象
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        # 获取 additional_kwargs
        kwargs = getattr(lc_msg, "additional_kwargs", {}) or {}
        
        # 确定角色
        if isinstance(lc_msg, HumanMessage):
            role = ROLE_USER
        elif isinstance(lc_msg, AIMessage):
            role = ROLE_ASSISTANT
        elif isinstance(lc_msg, SystemMessage):
            role = ROLE_SYSTEM
        else:
            # 尝试从 type 属性获取
            msg_type = getattr(lc_msg, "type", "human")
            role = {
                "human": ROLE_USER,
                "ai": ROLE_ASSISTANT,
                "system": ROLE_SYSTEM,
            }.get(msg_type, ROLE_USER)
        
        # 提取内容
        content = getattr(lc_msg, "content", "")
        if isinstance(content, list):
            # 处理多模态内容
            content = " ".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        
        # 提取附件
        attachments = []
        if "attachments" in kwargs:
            attachments = [Attachment.from_dict(a) for a in kwargs["attachments"]]
        
        # 提取 usage
        usage = None
        if "usage" in kwargs and kwargs["usage"]:
            usage = TokenUsage.from_dict(kwargs["usage"])
        
        return Message(
            role=role,
            content=content,
            attachments=attachments,
            timestamp=kwargs.get("timestamp", ""),
            metadata=kwargs.get("metadata", {}),
            operations=kwargs.get("operations", []),
            reasoning_content=kwargs.get("reasoning_content", ""),
            usage=usage,
        )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def get_message_count(self, state: Dict[str, Any]) -> int:
        """
        获取 GraphState 中的消息数量
        
        Args:
            state: GraphState 状态
            
        Returns:
            消息数量
        """
        return len(state.get("messages", []))
    
    def has_messages(self, state: Dict[str, Any]) -> bool:
        """
        检查 GraphState 是否有消息
        
        Args:
            state: GraphState 状态
            
        Returns:
            是否有消息
        """
        return self.get_message_count(state) > 0
    
    def get_last_message(
        self,
        state: Dict[str, Any]
    ) -> Optional[Message]:
        """
        获取最后一条消息
        
        Args:
            state: GraphState 状态
            
        Returns:
            最后一条消息，如果没有则返回 None
        """
        messages = state.get("messages", [])
        if not messages:
            return None
        return self.from_langchain_message(messages[-1])
    
    def filter_by_role(
        self,
        state: Dict[str, Any],
        role: str
    ) -> List[Message]:
        """
        按角色过滤消息
        
        Args:
            state: GraphState 状态
            role: 角色名称
            
        Returns:
            指定角色的消息列表
        """
        all_messages = self.extract_messages_from_state(state)
        return [msg for msg in all_messages if msg.role == role]


# ============================================================
# 模块级便捷函数（向后兼容）
# ============================================================

# 创建默认适配器实例
_default_adapter = MessageAdapter()


def to_langchain_message(msg: Message) -> Any:
    """将内部消息转换为 LangChain 消息（便捷函数）"""
    return _default_adapter.to_langchain_message(msg)


def from_langchain_message(lc_msg: Any) -> Message:
    """将 LangChain 消息转换为内部格式（便捷函数）"""
    return _default_adapter.from_langchain_message(lc_msg)


def messages_to_langchain(messages: List[Message]) -> List[Any]:
    """批量转换消息列表为 LangChain 格式（便捷函数）"""
    return _default_adapter.to_langchain_messages(messages)


def messages_from_langchain(lc_messages: List[Any]) -> List[Message]:
    """批量转换 LangChain 消息列表为内部格式（便捷函数）"""
    return _default_adapter.from_langchain_messages(lc_messages)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 适配器类
    "MessageAdapter",
    # 便捷函数（向后兼容）
    "to_langchain_message",
    "from_langchain_message",
    "messages_to_langchain",
    "messages_from_langchain",
]
