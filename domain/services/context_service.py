# Context Service - Stateless Conversation History Management
"""
对话历史服务 - 无状态对话历史读写

职责：
- 管理对话历史的读写（会话文件 CRUD）
- 管理会话索引（sessions.json）
- 支持消息追加和查询
- 文件名安全处理
- 不持有任何内存状态

设计原则：
- 纯函数式：输入 → 处理 → 输出到文件 → 返回结果
- 无状态：对话历史存储在文件中
- 幂等性：相同输入产生相同输出

存储路径：
- 对话历史：{project_root}/.circuit_ai/conversations/{session_id}.json
- 会话索引：{project_root}/.circuit_ai/conversations/sessions.json

被调用方：
- SessionStateManager（会话生命周期协调）
- 所有需要对话历史的图节点
- UI 对话面板

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
    
    # 获取当前会话 ID
    current_id = context_service.get_current_session_id(project_root)
    
    # 更新会话索引
    context_service.update_session_index(
        project_root, session_id, {"name": "New Name"}
    )
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 对话历史目录相对路径
CONVERSATIONS_DIR = ".circuit_ai/conversations"

# 会话索引文件名
SESSIONS_INDEX_FILE = "sessions.json"


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
    
    优先从会话索引读取，同时与实际文件同步。
    
    Args:
        project_root: 项目根目录路径
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 会话摘要列表，按更新时间倒序
    """
    # 从索引读取
    index_data = _load_sessions_index(project_root)
    sessions = index_data.get("sessions", [])
    
    # 如果索引为空，扫描目录
    if not sessions:
        root = Path(project_root)
        conv_dir = root / CONVERSATIONS_DIR
        
        if conv_dir.exists():
            # 获取所有 JSON 文件（排除 sessions.json）
            json_files = [
                f for f in conv_dir.glob("*.json")
                if f.name != SESSIONS_INDEX_FILE
            ]
            
            # 按修改时间排序
            json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            
            for file_path in json_files[:limit]:
                data = _read_json_file(file_path)
                if data:
                    session_id = data.get("session_id", file_path.stem)
                    sessions.append({
                        "session_id": session_id,
                        "name": data.get("name", session_id),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "message_count": data.get("message_count", 0),
                        "preview": data.get("preview", ""),
                    })
            
            # 保存到索引
            if sessions:
                index_data["sessions"] = sessions
                _save_sessions_index(project_root, index_data)
    
    # 按更新时间排序
    sessions.sort(
        key=lambda s: s.get("updated_at", ""),
        reverse=True
    )
    
    return sessions[:limit]


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


def session_exists(
    project_root: str,
    session_id: str
) -> bool:
    """
    检查会话是否存在
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        bool: 会话文件是否存在
    """
    if not session_id:
        return False
    
    root = Path(project_root)
    file_path = root / CONVERSATIONS_DIR / f"{session_id}.json"
    return file_path.exists()


def rename_session(
    project_root: str,
    session_id: str,
    new_name: str
) -> bool:
    """
    重命名会话
    
    仅更新会话索引中的名称，不修改文件名。
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        new_name: 新名称
        
    Returns:
        bool: 是否重命名成功
    """
    if not session_id or not new_name:
        return False
    
    return update_session_index(
        project_root,
        session_id,
        {"name": new_name}
    )


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
# 会话索引管理
# ============================================================

def get_current_session_id(project_root: str) -> Optional[str]:
    """
    获取当前会话 ID
    
    从 sessions.json 索引文件读取 current_session_id。
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        str: 当前会话 ID，不存在返回 None
    """
    index_data = _load_sessions_index(project_root)
    return index_data.get("current_session_id") or None


def set_current_session_id(project_root: str, session_id: str) -> bool:
    """
    设置当前会话 ID
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        bool: 是否设置成功
    """
    index_data = _load_sessions_index(project_root)
    index_data["current_session_id"] = session_id
    return _save_sessions_index(project_root, index_data)


def get_session_metadata(
    project_root: str,
    session_id: str
) -> Optional[Dict[str, Any]]:
    """
    获取会话元数据
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        Dict: 会话元数据，不存在返回 None
    """
    index_data = _load_sessions_index(project_root)
    sessions = index_data.get("sessions", [])
    
    for session in sessions:
        if session.get("session_id") == session_id:
            return session
    
    return None


def update_session_index(
    project_root: str,
    session_id: str,
    updates: Dict[str, Any],
    set_current: bool = False
) -> bool:
    """
    更新会话索引
    
    如果会话不存在则创建，存在则更新。
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        updates: 要更新的字段
        set_current: 是否设置为当前会话
        
    Returns:
        bool: 是否更新成功
    """
    index_data = _load_sessions_index(project_root)
    sessions = index_data.get("sessions", [])
    
    # 查找是否已存在
    existing_idx = None
    for i, session in enumerate(sessions):
        if session.get("session_id") == session_id:
            existing_idx = i
            break
    
    if existing_idx is not None:
        # 更新现有记录
        sessions[existing_idx].update(updates)
    else:
        # 添加新记录
        new_session = {"session_id": session_id}
        new_session.update(updates)
        sessions.append(new_session)
    
    index_data["sessions"] = sessions
    
    # 设置当前会话
    if set_current:
        index_data["current_session_id"] = session_id
    
    return _save_sessions_index(project_root, index_data)


def remove_from_session_index(project_root: str, session_id: str) -> bool:
    """
    从会话索引中移除会话
    
    Args:
        project_root: 项目根目录路径
        session_id: 会话 ID
        
    Returns:
        bool: 是否移除成功
    """
    index_data = _load_sessions_index(project_root)
    sessions = index_data.get("sessions", [])
    
    # 过滤掉要删除的会话
    index_data["sessions"] = [
        s for s in sessions if s.get("session_id") != session_id
    ]
    
    # 如果删除的是当前会话，清空 current_session_id
    if index_data.get("current_session_id") == session_id:
        index_data["current_session_id"] = ""
    
    return _save_sessions_index(project_root, index_data)


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


def _get_sessions_index_path(project_root: str) -> Path:
    """获取会话索引文件路径"""
    return Path(project_root) / CONVERSATIONS_DIR / SESSIONS_INDEX_FILE


def _load_sessions_index(project_root: str) -> Dict[str, Any]:
    """
    加载会话索引文件
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        Dict: 索引数据，若不存在则返回空结构
    """
    index_path = _get_sessions_index_path(project_root)
    
    if not index_path.exists():
        return {
            "current_session_id": "",
            "sessions": []
        }
    
    data = _read_json_file(index_path)
    
    # 确保必要字段存在
    if "current_session_id" not in data:
        data["current_session_id"] = ""
    if "sessions" not in data:
        data["sessions"] = []
    
    return data


def _save_sessions_index(
    project_root: str,
    index_data: Dict[str, Any]
) -> bool:
    """
    保存会话索引文件
    
    Args:
        project_root: 项目根目录路径
        index_data: 索引数据
        
    Returns:
        bool: 是否保存成功
    """
    index_path = _get_sessions_index_path(project_root)
    
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_file(index_path, index_data)
        return True
    except Exception:
        return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 消息操作
    "save_messages",
    "load_messages",
    "append_message",
    "get_recent_messages",
    "get_message_count",
    "clear_messages",
    "get_conversation_path",
    # 会话管理
    "list_sessions",
    "delete_session",
    "session_exists",
    "rename_session",
    # 会话索引管理
    "get_current_session_id",
    "set_current_session_id",
    "get_session_metadata",
    "update_session_index",
    "remove_from_session_index",
    # 常量
    "CONVERSATIONS_DIR",
    "SESSIONS_INDEX_FILE",
]
