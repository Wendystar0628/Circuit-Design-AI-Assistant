# Message Types - Message Structure Definitions
"""
消息类型定义 - 定义对话消息的数据结构

职责：
- 定义内部消息结构
- 提供与 LangChain 消息类型的相互转换
- 确保消息格式一致性

消息结构：
{
    "role": str,           # "user" | "assistant" | "system"
    "content": str,        # 文本内容
    "attachments": list,   # 附件列表（图片/文件引用）
    "timestamp": str,      # ISO时间戳
    "metadata": dict,      # 额外元数据
    "operations": list,    # 操作摘要（仅助手消息）
    "reasoning_content": str,  # 深度思考内容（仅助手消息，可选）
    "usage": dict,         # Token 使用统计（仅助手消息，可选）
}

使用示例：
    from domain.llm.message_types import Message, create_user_message
    
    msg = create_user_message("Hello, help me design a circuit")
    lc_msg = to_langchain_message(msg)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union



# ============================================================
# 常量定义
# ============================================================

# 消息角色
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"

# 有效角色列表
VALID_ROLES = {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class TokenUsage:
    """Token 使用统计"""
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    
    def to_dict(self) -> Dict[str, int]:
        """转换为字典"""
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional['TokenUsage']:
        """从字典创建"""
        if not data:
            return None
        return cls(
            total_tokens=data.get("total_tokens", 0),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            cached_tokens=data.get("cached_tokens", 0),
        )


@dataclass
class Attachment:
    """消息附件"""
    type: str              # "image" | "file"
    path: str              # 文件路径
    name: str              # 显示名称
    mime_type: str = ""    # MIME 类型
    size: int = 0          # 文件大小（字节）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type,
            "path": self.path,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Attachment':
        """从字典创建"""
        return cls(
            type=data.get("type", "file"),
            path=data.get("path", ""),
            name=data.get("name", ""),
            mime_type=data.get("mime_type", ""),
            size=data.get("size", 0),
        )



@dataclass
class Message:
    """
    对话消息
    
    统一的消息数据结构，支持用户消息、助手消息和系统消息。
    """
    role: str                                    # "user" | "assistant" | "system"
    content: str                                 # 文本内容
    attachments: List[Attachment] = field(default_factory=list)  # 附件列表
    timestamp: str = ""                          # ISO 时间戳
    metadata: Dict[str, Any] = field(default_factory=dict)       # 额外元数据
    operations: List[str] = field(default_factory=list)          # 操作摘要（仅助手）
    reasoning_content: str = ""                  # 深度思考内容（仅助手）
    usage: Optional[TokenUsage] = None           # Token 使用统计（仅助手）
    
    def __post_init__(self):
        """初始化后处理"""
        # 验证角色
        if self.role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {self.role}. Must be one of {VALID_ROLES}")
        
        # 自动设置时间戳
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "role": self.role,
            "content": self.content,
            "attachments": [a.to_dict() for a in self.attachments],
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
        
        # 仅助手消息包含的字段
        if self.role == ROLE_ASSISTANT:
            result["operations"] = self.operations
            result["reasoning_content"] = self.reasoning_content
            if self.usage:
                result["usage"] = self.usage.to_dict()
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """从字典创建"""
        attachments = [
            Attachment.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("attachments", [])
        ]
        
        usage = None
        if "usage" in data and data["usage"]:
            usage = TokenUsage.from_dict(data["usage"])
        
        return cls(
            role=data.get("role", ROLE_USER),
            content=data.get("content", ""),
            attachments=attachments,
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            operations=data.get("operations", []),
            reasoning_content=data.get("reasoning_content", ""),
            usage=usage,
        )
    
    def is_user(self) -> bool:
        """是否为用户消息"""
        return self.role == ROLE_USER
    
    def is_assistant(self) -> bool:
        """是否为助手消息"""
        return self.role == ROLE_ASSISTANT
    
    def is_system(self) -> bool:
        """是否为系统消息"""
        return self.role == ROLE_SYSTEM



# ============================================================
# 工厂函数
# ============================================================

def create_user_message(
    content: str,
    attachments: Optional[List[Attachment]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Message:
    """
    创建用户消息
    
    Args:
        content: 消息内容
        attachments: 附件列表
        metadata: 额外元数据
        
    Returns:
        Message: 用户消息对象
    """
    return Message(
        role=ROLE_USER,
        content=content,
        attachments=attachments or [],
        metadata=metadata or {},
    )


def create_assistant_message(
    content: str,
    reasoning_content: str = "",
    operations: Optional[List[str]] = None,
    usage: Optional[TokenUsage] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Message:
    """
    创建助手消息
    
    Args:
        content: 消息内容
        reasoning_content: 深度思考内容
        operations: 操作摘要列表
        usage: Token 使用统计
        metadata: 额外元数据
        
    Returns:
        Message: 助手消息对象
    """
    return Message(
        role=ROLE_ASSISTANT,
        content=content,
        reasoning_content=reasoning_content,
        operations=operations or [],
        usage=usage,
        metadata=metadata or {},
    )


def create_system_message(
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Message:
    """
    创建系统消息
    
    Args:
        content: 消息内容
        metadata: 额外元数据
        
    Returns:
        Message: 系统消息对象
    """
    return Message(
        role=ROLE_SYSTEM,
        content=content,
        metadata=metadata or {},
    )



# ============================================================
# LangChain 消息转换（向后兼容）
# ============================================================
# 注意：转换逻辑已移至 message_adapter.py
# 这里保留导入以保持向后兼容性

def to_langchain_message(msg: Message) -> Any:
    """
    将内部消息转换为 LangChain 消息对象
    
    注意：此函数已移至 message_adapter.py，这里保留以保持向后兼容。
    建议使用 MessageAdapter 类进行转换。
    
    Args:
        msg: 内部消息对象
        
    Returns:
        LangChain 消息对象（HumanMessage/AIMessage/SystemMessage）
    """
    from domain.llm.message_adapter import to_langchain_message as _to_lc
    return _to_lc(msg)


def from_langchain_message(lc_msg: Any) -> Message:
    """
    将 LangChain 消息转换为内部格式
    
    注意：此函数已移至 message_adapter.py，这里保留以保持向后兼容。
    建议使用 MessageAdapter 类进行转换。
    
    Args:
        lc_msg: LangChain 消息对象
        
    Returns:
        Message: 内部消息对象
    """
    from domain.llm.message_adapter import from_langchain_message as _from_lc
    return _from_lc(lc_msg)


def messages_to_langchain(messages: List[Message]) -> List[Any]:
    """
    批量转换消息列表为 LangChain 格式
    
    注意：此函数已移至 message_adapter.py，这里保留以保持向后兼容。
    
    Args:
        messages: 内部消息列表
        
    Returns:
        LangChain 消息列表
    """
    from domain.llm.message_adapter import messages_to_langchain as _to_lc
    return _to_lc(messages)


def messages_from_langchain(lc_messages: List[Any]) -> List[Message]:
    """
    批量转换 LangChain 消息列表为内部格式
    
    注意：此函数已移至 message_adapter.py，这里保留以保持向后兼容。
    
    Args:
        lc_messages: LangChain 消息列表
        
    Returns:
        内部消息列表
    """
    from domain.llm.message_adapter import messages_from_langchain as _from_lc
    return _from_lc(lc_messages)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 常量
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "VALID_ROLES",
    # 数据结构
    "TokenUsage",
    "Attachment",
    "Message",
    # 工厂函数
    "create_user_message",
    "create_assistant_message",
    "create_system_message",
    # LangChain 转换
    "to_langchain_message",
    "from_langchain_message",
    "messages_to_langchain",
    "messages_from_langchain",
]
