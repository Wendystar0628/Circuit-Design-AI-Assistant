# Context Service - Stateless Conversation History Management
"""
对话历史服务 - 无状态对话历史读写

职责：
- 管理对话历史的读写
- 支持消息追加和查询
- 不持有任何内存状态

设计原则：
- 纯函数式：输入 → 处理 → 输出到文件 → 返回结果
- 无状态：对话历史存储在文件中
- 幂等性：相同输入产生相同输出

存储路径：
- 对话历史：{project_root}/.circuit_ai/conversations/{session_id}.json

被调用方：
- 所有需要对话历史的图节点
- UI 对话面板

注意：
- 完整实现在阶段三
- 本模块提供接口骨架

使用示例：
    from domain.services import context_service
    
    # 保存消息
    context_service.save_messages(
        project_root="/path/to/project",
        session_id="20240101_120000",
        messages=[{"role": "user", "content": "Hello"}]
    )
    
    # 加载消息
    messages = context_service.load_messages(
        project_root="/path/to/project",
        session_id="20240101_120000"
    )
    
    # 追加消息
    context_service.append_message(
        project_root="/path/to/project",
        session_id="20240101_120000",
        message={"role": "assistant", "content": "Hi!"}
    )
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 对话历史目录相对路径
CONVERSATIONS_DIR = ".circuit_ai/conversations"


def save_messages(
    project_root: str,
    session_id: str,
    messages: List[Dict[str, Any]]
) -> None:
    """
    保存消息列表到文件（覆盖模式）
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        messages: 消息列表
        
    Raises:
        ValueError: 消息格式无效
        IOError: 文件写入失败
    """
    if not session_id:
        raise ValueError("Session ID cannot be empty")
    
    root = Path(project_root)
    file_path = root / CONVERSATIONS_DIR / f"{session_id}.json"
    
    # 确保目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 构建会话数据
    session_data = {
        "session_id": session_id,
        "updated_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }
    
    _write_json_file(file_path, session_data)


def load_messages(
    project_root: str,
    session_id: str
) -> List[Dict[str, Any]]:
    """
    从文件加载消息列表
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        List[Dict]: 消息列表，文件不存在时返回空列表
    """
    if not session_id:
        return []
    
    root = Path(project_root)
    file_path = root / CONVERSATIONS_DIR / f"{session_id}.json"
    
    if not file_path.exists():
        return []
    
    data = _read_json_file(file_path)
    return data.get("messages", [])


def append_message(
    project_root: str,
    session_id: str,
    message: Dict[str, Any]
) -> None:
    """
    追加单条消息到会话
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        message: 消息字典，必须包含 role 和 content
        
    Raises:
        ValueError: 消息格式无效
    """
    if not message.get("role") or "content" not in message:
        raise ValueError("Message must have 'role' and 'content' fields")
    
    # 加载现有消息
    messages = load_messages(project_root, session_id)
    
    # 添加时间戳
    if "timestamp" not in message:
        message["timestamp"] = datetime.now().isoformat()
    
    # 追加消息
    messages.append(message)
    
    # 保存
    save_messages(project_root, session_id, messages)


def get_recent_messages(
    project_root: str,
    session_id: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    获取最近 N 条消息
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 最近的消息列表
    """
    messages = load_messages(project_root, session_id)
    return messages[-limit:] if messages else []


def get_message_count(
    project_root: str,
    session_id: str
) -> int:
    """
    获取会话消息数量
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        int: 消息数量
    """
    messages = load_messages(project_root, session_id)
    return len(messages)


def list_sessions(
    project_root: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    列出所有会话
    
    Args:
        project_root: 项目根目录路径
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 会话摘要列表，按更新时间倒序
    """
    root = Path(project_root)
    conv_dir = root / CONVERSATIONS_DIR
    
    if not conv_dir.exists():
        return []
    
    # 获取所有 JSON 文件
    json_files = list(conv_dir.glob("*.json"))
    
    # 按修改时间排序
    json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    sessions = []
    for file_path in json_files[:limit]:
        data = _read_json_file(file_path)
        if data:
            sessions.append({
                "session_id": data.get("session_id", file_path.stem),
                "updated_at": data.get("updated_at", ""),
                "message_count": data.get("message_count", 0),
            })
    
    return sessions


def delete_session(
    project_root: str,
    session_id: str
) -> bool:
    """
    删除会话
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        bool: 是否删除成功
    """
    root = Path(project_root)
    file_path = root / CONVERSATIONS_DIR / f"{session_id}.json"
    
    if file_path.exists():
        try:
            file_path.unlink()
            return True
        except Exception:
            return False
    return False


def clear_messages(
    project_root: str,
    session_id: str
) -> None:
    """
    清空会话消息（保留会话文件）
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
    """
    save_messages(project_root, session_id, [])


def get_conversation_path(
    project_root: str,
    session_id: str
) -> str:
    """
    获取会话文件路径
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        str: 会话文件完整路径
    """
    return str(Path(project_root) / CONVERSATIONS_DIR / f"{session_id}.json")


# ============================================================
# 内部辅助函数
# ============================================================

def _read_json_file(file_path: Path) -> Dict[str, Any]:
    """读取 JSON 文件"""
    try:
        content = file_path.read_text(encoding="utf-8")
        return json.loads(content) if content.strip() else {}
    except (json.JSONDecodeError, Exception):
        return {}


def _write_json_file(file_path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 文件"""
    content = json.dumps(data, indent=2, ensure_ascii=False)
    file_path.write_text(content, encoding="utf-8")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "save_messages",
    "load_messages",
    "append_message",
    "get_recent_messages",
    "get_message_count",
    "list_sessions",
    "delete_session",
    "clear_messages",
    "get_conversation_path",
    "CONVERSATIONS_DIR",
]
