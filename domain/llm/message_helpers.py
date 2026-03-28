# Message Helpers - LangChain Message Utility Functions
"""
消息辅助函数 - 提供 LangChain 消息扩展字段的读写辅助函数

架构决策：
- 项目全面使用 LangGraph，GraphState.messages 直接存储 LangChain 消息类型
- 不引入"内部消息格式"，避免不必要的转换层
- 扩展字段（reasoning_content、operations 等）存储在 additional_kwargs 中
- 本模块提供扩展字段的类型安全读写函数

使用示例：
    from domain.llm.message_helpers import (
        create_human_message,
        create_ai_message,
        get_reasoning_content,
        message_to_dict,
    )
    
    # 创建消息
    msg = create_human_message("帮我设计一个放大器")
    ai_msg = create_ai_message("好的", reasoning_content="首先分析需求...")
    
    # 读取扩展字段
    reasoning = get_reasoning_content(ai_msg)
    
    # 序列化
    data = message_to_dict(msg)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)


# ============================================================
# 角色常量
# ============================================================

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"

VALID_ROLES = {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL}

# 角色到消息类型的映射
ROLE_TO_MESSAGE_TYPE = {
    ROLE_USER: HumanMessage,
    "human": HumanMessage,
    ROLE_ASSISTANT: AIMessage,
    "ai": AIMessage,
    ROLE_SYSTEM: SystemMessage,
    ROLE_TOOL: ToolMessage,
}

# 消息类型到角色的映射
MESSAGE_TYPE_TO_ROLE = {
    HumanMessage: ROLE_USER,
    AIMessage: ROLE_ASSISTANT,
    SystemMessage: ROLE_SYSTEM,
    ToolMessage: ROLE_TOOL,
}


# ============================================================
# 消息创建辅助函数
# ============================================================

def create_human_message(
    content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    timestamp: Optional[str] = None,
) -> HumanMessage:
    """
    创建用户消息
    
    Args:
        content: 消息内容
        attachments: 附件列表，每个附件为字典 {"type", "path", "name", "mime_type", "size"}
        timestamp: ISO 时间戳，默认为当前时间
        
    Returns:
        HumanMessage 实例
    """
    additional_kwargs = {
        "timestamp": timestamp or datetime.now().isoformat(),
    }
    if attachments:
        additional_kwargs["attachments"] = attachments
    
    return HumanMessage(
        content=content,
        additional_kwargs=additional_kwargs,
    )


def create_ai_message(
    content: str,
    reasoning_content: str = "",
    operations: Optional[List[str]] = None,
    usage: Optional[Dict[str, int]] = None,
    is_partial: bool = False,
    stop_reason: str = "",
    tool_calls_pending: Optional[List[Dict[str, Any]]] = None,
    web_search_results: Optional[List[Dict[str, Any]]] = None,
    timestamp: Optional[str] = None,
) -> AIMessage:
    """
    创建助手消息
    
    Args:
        content: 消息内容
        reasoning_content: 深度思考内容
        operations: 操作摘要列表
        usage: Token 使用统计 {"total_tokens", "prompt_tokens", "completion_tokens", "cached_tokens"}
        is_partial: 是否为部分响应（用户中断）
        stop_reason: 停止原因
        tool_calls_pending: 中断时未完成的工具调用
        web_search_results: 联网搜索结果
        timestamp: ISO 时间戳，默认为当前时间
        
    Returns:
        AIMessage 实例
    """
    additional_kwargs = {
        "timestamp": timestamp or datetime.now().isoformat(),
        "reasoning_content": reasoning_content,
        "operations": operations or [],
    }
    
    if usage:
        additional_kwargs["usage"] = usage
    if is_partial:
        additional_kwargs["is_partial"] = is_partial
        additional_kwargs["stop_reason"] = stop_reason
    if tool_calls_pending:
        additional_kwargs["tool_calls_pending"] = tool_calls_pending
    if web_search_results:
        additional_kwargs["web_search_results"] = web_search_results
    
    return AIMessage(
        content=content,
        additional_kwargs=additional_kwargs,
    )


def create_system_message(
    content: str,
    timestamp: Optional[str] = None,
) -> SystemMessage:
    """
    创建系统消息
    
    Args:
        content: 消息内容
        timestamp: ISO 时间戳，默认为当前时间
        
    Returns:
        SystemMessage 实例
    """
    return SystemMessage(
        content=content,
        additional_kwargs={
            "timestamp": timestamp or datetime.now().isoformat(),
        },
    )


def create_tool_message(
    content: str,
    tool_call_id: str,
    name: str = "",
    timestamp: Optional[str] = None,
) -> ToolMessage:
    """
    创建工具消息
    
    Args:
        content: 工具执行结果
        tool_call_id: 工具调用 ID
        name: 工具名称
        timestamp: ISO 时间戳，默认为当前时间
        
    Returns:
        ToolMessage 实例
    """
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=name,
        additional_kwargs={
            "timestamp": timestamp or datetime.now().isoformat(),
        },
    )


# ============================================================
# 扩展字段读取辅助函数
# ============================================================

def _get_additional_kwargs(msg: BaseMessage) -> Dict[str, Any]:
    """获取消息的 additional_kwargs，确保返回字典"""
    return getattr(msg, "additional_kwargs", {}) or {}


def get_reasoning_content(msg: BaseMessage) -> str:
    """获取深度思考内容（仅 AIMessage 有效）"""
    return _get_additional_kwargs(msg).get("reasoning_content", "")


def get_operations(msg: BaseMessage) -> List[str]:
    """获取操作摘要列表（仅 AIMessage 有效）"""
    return _get_additional_kwargs(msg).get("operations", [])


def get_usage(msg: BaseMessage) -> Optional[Dict[str, int]]:
    """获取 Token 使用统计（仅 AIMessage 有效）"""
    return _get_additional_kwargs(msg).get("usage")


def get_attachments(msg: BaseMessage) -> List[Dict[str, Any]]:
    """获取附件列表（仅 HumanMessage 有效）"""
    return _get_additional_kwargs(msg).get("attachments", [])


def get_timestamp(msg: BaseMessage) -> str:
    """获取时间戳"""
    return _get_additional_kwargs(msg).get("timestamp", "")


def is_partial_response(msg: BaseMessage) -> bool:
    """是否为部分响应（用户中断）"""
    return _get_additional_kwargs(msg).get("is_partial", False)


def get_stop_reason(msg: BaseMessage) -> str:
    """获取停止原因（仅 is_partial=True 时有效）"""
    return _get_additional_kwargs(msg).get("stop_reason", "")


def get_tool_calls_pending(msg: BaseMessage) -> List[Dict[str, Any]]:
    """获取中断时未完成的工具调用"""
    return _get_additional_kwargs(msg).get("tool_calls_pending", [])


def get_web_search_results(msg: BaseMessage) -> List[Dict[str, Any]]:
    """获取联网搜索结果"""
    return _get_additional_kwargs(msg).get("web_search_results", [])


# ============================================================
# 扩展字段写入辅助函数
# ============================================================

def _update_additional_kwargs(
    msg: BaseMessage,
    updates: Dict[str, Any],
) -> BaseMessage:
    """
    更新消息的 additional_kwargs 并返回新消息
    
    注意：LangChain 消息是不可变的，此函数创建新实例
    """
    current_kwargs = _get_additional_kwargs(msg).copy()
    current_kwargs.update(updates)
    
    # 根据消息类型创建新实例
    msg_type = type(msg)
    
    if msg_type == HumanMessage:
        return HumanMessage(
            content=msg.content,
            additional_kwargs=current_kwargs,
        )
    elif msg_type == AIMessage:
        return AIMessage(
            content=msg.content,
            additional_kwargs=current_kwargs,
        )
    elif msg_type == SystemMessage:
        return SystemMessage(
            content=msg.content,
            additional_kwargs=current_kwargs,
        )
    elif msg_type == ToolMessage:
        return ToolMessage(
            content=msg.content,
            tool_call_id=getattr(msg, "tool_call_id", ""),
            name=getattr(msg, "name", ""),
            additional_kwargs=current_kwargs,
        )
    else:
        # 未知类型，尝试通用方式
        return msg_type(
            content=msg.content,
            additional_kwargs=current_kwargs,
        )


def set_reasoning_content(msg: AIMessage, content: str) -> AIMessage:
    """设置深度思考内容"""
    return _update_additional_kwargs(msg, {"reasoning_content": content})


def set_operations(msg: AIMessage, operations: List[str]) -> AIMessage:
    """设置操作摘要"""
    return _update_additional_kwargs(msg, {"operations": operations})


def mark_as_partial(msg: AIMessage, stop_reason: str) -> AIMessage:
    """标记为部分响应"""
    return _update_additional_kwargs(msg, {
        "is_partial": True,
        "stop_reason": stop_reason,
    })


def mark_as_complete(msg: AIMessage) -> AIMessage:
    """标记为完成（清除部分响应标记）"""
    return _update_additional_kwargs(msg, {
        "is_partial": False,
        "stop_reason": "",
    })


# ============================================================
# 消息类型判断
# ============================================================

def is_human_message(msg: Any) -> bool:
    """是否为用户消息"""
    return isinstance(msg, HumanMessage)


def is_ai_message(msg: Any) -> bool:
    """是否为助手消息"""
    return isinstance(msg, AIMessage)


def is_system_message(msg: Any) -> bool:
    """是否为系统消息"""
    return isinstance(msg, SystemMessage)


def is_tool_message(msg: Any) -> bool:
    """是否为工具消息"""
    return isinstance(msg, ToolMessage)


def get_role(msg: BaseMessage) -> str:
    """
    获取消息角色
    
    Returns:
        "user" | "assistant" | "system" | "tool"
    """
    return MESSAGE_TYPE_TO_ROLE.get(type(msg), ROLE_USER)



# ============================================================
# 序列化辅助函数（用于文件持久化）
# ============================================================

def message_to_dict(msg: BaseMessage) -> Dict[str, Any]:
    """
    将 LangChain 消息序列化为字典（用于 JSON 存储）
    
    Args:
        msg: LangChain 消息实例
        
    Returns:
        可 JSON 序列化的字典
    """
    role = get_role(msg)
    kwargs = _get_additional_kwargs(msg)
    
    # 处理内容（可能是字符串或多模态列表）
    content = msg.content
    if isinstance(content, list):
        # 多模态内容，提取文本部分
        content = " ".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    
    result = {
        "type": role,
        "content": content,
        "additional_kwargs": {},
    }
    
    # 复制 additional_kwargs 中的字段
    if kwargs.get("timestamp"):
        result["additional_kwargs"]["timestamp"] = kwargs["timestamp"]
    
    # 用户消息特有字段
    if role == ROLE_USER:
        if kwargs.get("attachments"):
            result["additional_kwargs"]["attachments"] = kwargs["attachments"]
    
    # 助手消息特有字段
    elif role == ROLE_ASSISTANT:
        if kwargs.get("reasoning_content"):
            result["additional_kwargs"]["reasoning_content"] = kwargs["reasoning_content"]
        if kwargs.get("operations"):
            result["additional_kwargs"]["operations"] = kwargs["operations"]
        if kwargs.get("usage"):
            result["additional_kwargs"]["usage"] = kwargs["usage"]
        if kwargs.get("is_partial"):
            result["additional_kwargs"]["is_partial"] = kwargs["is_partial"]
            result["additional_kwargs"]["stop_reason"] = kwargs.get("stop_reason", "")
        if kwargs.get("tool_calls_pending"):
            result["additional_kwargs"]["tool_calls_pending"] = kwargs["tool_calls_pending"]
        if kwargs.get("web_search_results"):
            result["additional_kwargs"]["web_search_results"] = kwargs["web_search_results"]
    
    # 工具消息特有字段
    elif role == ROLE_TOOL:
        result["tool_call_id"] = getattr(msg, "tool_call_id", "")
        result["name"] = getattr(msg, "name", "")
    
    return result


def dict_to_message(data: Dict[str, Any]) -> BaseMessage:
    """
    从字典反序列化为 LangChain 消息
    
    Args:
        data: 字典数据，必须包含 "type" 字段
        
    Returns:
        LangChain 消息实例
        
    Raises:
        ValueError: 如果 type 字段缺失或无效
    """
    msg_type = data.get("type")
    if not msg_type:
        raise ValueError("Message data must contain 'type' field")
    
    content = data.get("content", "")
    kwargs = data.get("additional_kwargs", {})
    
    if msg_type in (ROLE_USER, "human"):
        return HumanMessage(
            content=content,
            additional_kwargs=kwargs,
        )
    elif msg_type in (ROLE_ASSISTANT, "ai"):
        return AIMessage(
            content=content,
            additional_kwargs=kwargs,
        )
    elif msg_type == ROLE_SYSTEM:
        return SystemMessage(
            content=content,
            additional_kwargs=kwargs,
        )
    elif msg_type == ROLE_TOOL:
        return ToolMessage(
            content=content,
            tool_call_id=data.get("tool_call_id", ""),
            name=data.get("name", ""),
            additional_kwargs=kwargs,
        )
    else:
        raise ValueError(f"Unknown message type: {msg_type}")


def messages_to_dicts(msgs: List[BaseMessage]) -> List[Dict[str, Any]]:
    """批量序列化消息列表"""
    return [message_to_dict(msg) for msg in msgs]


def dicts_to_messages(data: List[Dict[str, Any]]) -> List[BaseMessage]:
    """批量反序列化消息列表"""
    return [dict_to_message(d) for d in data]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 角色常量
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_TOOL",
    "VALID_ROLES",
    # 消息创建
    "create_human_message",
    "create_ai_message",
    "create_system_message",
    "create_tool_message",
    # 扩展字段读取
    "get_reasoning_content",
    "get_operations",
    "get_usage",
    "get_attachments",
    "get_timestamp",
    "is_partial_response",
    "get_stop_reason",
    "get_tool_calls_pending",
    "get_web_search_results",
    # 扩展字段写入
    "set_reasoning_content",
    "set_operations",
    "mark_as_partial",
    "mark_as_complete",
    # 消息类型判断
    "is_human_message",
    "is_ai_message",
    "is_system_message",
    "is_tool_message",
    "get_role",
    # 序列化
    "message_to_dict",
    "dict_to_message",
    "messages_to_dicts",
    "dicts_to_messages",
]
