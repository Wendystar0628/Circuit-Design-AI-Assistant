# Message Types - Data Structure Definitions
"""
消息相关数据结构定义

本模块定义消息相关的辅助数据结构：
- TokenUsage: Token 使用统计
- Attachment: 消息附件

注意：消息本身直接使用 LangChain 消息类型（HumanMessage、AIMessage 等），
不再定义内部 Message 类。消息操作请使用 message_helpers 模块。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class TokenUsage:
    """
    Token 使用统计
    
    用于记录 LLM 调用的 Token 消耗情况。
    """
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
    """
    消息附件
    
    用于表示用户消息中的附件（图片、文件等）。
    """
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


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TokenUsage",
    "Attachment",
]
