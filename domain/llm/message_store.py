# Message Store - Message Storage and Retrieval
"""
消息存储 - 消息的存储、检索和分类

职责：
- 添加消息到状态
- 获取消息历史
- 消息重要性分级
- 会话归档与恢复

设计原则：
- 状态不可变：消息操作返回更新后的 state 副本
- 线程安全：内部使用 RLock 保护共享状态
- 解耦设计：通过 MessageAdapter 与 GraphState 交互，不直接操作 state["messages"]

使用示例：
    from domain.llm.message_store import MessageStore
    
    store = MessageStore()
    new_state = store.add_message(state, "user", "Hello")
    messages = store.get_messages(state)
"""

import copy
import json
import threading
from datetime import datetime
from pathlib import Path
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

# 会话目录名（相对于 .circuit_ai/）
CONVERSATIONS_DIR = "conversations"

# 归档目录名（相对于 .circuit_ai/）- 用于旧版归档功能
ARCHIVE_DIR = "conversations/archive"

# 会话索引文件名
SESSIONS_INDEX_FILE = "sessions.json"

# 文件名安全字符替换（特殊字符 → 下划线）
UNSAFE_FILENAME_CHARS = '/\\:*?"<>|'

# 文件名最大长度
MAX_FILENAME_LENGTH = 100


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
    """
    
    def __init__(self):
        """初始化消息存储"""
        self._lock = threading.RLock()
        self._logger = None
        self._file_manager = None
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
    
    @property
    def file_manager(self):
        """延迟获取文件管理器"""
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager
    
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
                    f"添加消息: role={role}, content_len={len(content)}"
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
    # 会话归档
    # ============================================================
    
    def archive_current_session(
        self,
        state: Dict[str, Any],
        project_path: str
    ) -> Tuple[bool, str]:
        """
        归档当前对话到 conversations/archive/
        
        Args:
            state: 当前状态
            project_path: 项目路径
            
        Returns:
            (是否成功, 消息或会话ID)
        """
        with self._lock:
            messages = self.get_messages(state)
            
            if not messages:
                return False, "没有消息可归档"
            
            # 生成会话 ID
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 构建归档数据
            archive_data = {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "summary": self.get_summary(state),
                "messages": [msg.to_dict() for msg in messages],
            }
            
            # 确定归档路径
            archive_dir = Path(project_path) / ARCHIVE_DIR
            archive_file = archive_dir / f"{session_id}.json"
            
            try:
                # 创建目录
                archive_dir.mkdir(parents=True, exist_ok=True)
                
                # 写入文件
                archive_file.write_text(
                    json.dumps(archive_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                
                if self.logger:
                    self.logger.info(f"会话已归档: {session_id}")
                
                return True, session_id
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"归档失败: {e}")
                return False, str(e)
    
    def get_archived_sessions(
        self,
        project_path: str
    ) -> List[Dict[str, Any]]:
        """
        获取已归档的对话列表
        
        Args:
            project_path: 项目路径
            
        Returns:
            归档会话列表（包含 session_id, created_at, message_count, summary）
        """
        archive_dir = Path(project_path) / ARCHIVE_DIR
        
        if not archive_dir.exists():
            return []
        
        sessions = []
        
        for file_path in sorted(archive_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", file_path.stem),
                    "created_at": data.get("created_at", ""),
                    "message_count": data.get("message_count", 0),
                    "summary": data.get("summary", "")[:100],  # 截断摘要
                })
            except Exception:
                continue
        
        return sessions
    
    def restore_session(
        self,
        session_id: str,
        project_path: str,
        state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        从归档恢复对话
        
        通过 MessageAdapter 更新 GraphState。
        
        Args:
            session_id: 会话 ID
            project_path: 项目路径
            state: 当前状态
            
        Returns:
            (更新后的状态, 是否成功, 消息)
        """
        archive_file = Path(project_path) / ARCHIVE_DIR / f"{session_id}.json"
        
        if not archive_file.exists():
            return state, False, f"归档文件不存在: {session_id}"
        
        try:
            data = json.loads(archive_file.read_text(encoding="utf-8"))
            
            # 重建消息（内部格式）
            messages_data = data.get("messages", [])
            messages = [Message.from_dict(m) for m in messages_data]
            
            # 通过 MessageAdapter 更新状态
            new_state = self._message_adapter.update_state_messages(state, messages)
            new_state["conversation_summary"] = data.get("summary", "")
            
            if self.logger:
                self.logger.info(f"会话已恢复: {session_id}")
            
            return new_state, True, f"已恢复 {len(messages)} 条消息"
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"恢复会话失败: {e}")
            return state, False, str(e)
    
    # ============================================================
    # 导入导出
    # ============================================================
    
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
            format: 导出格式 ("json" | "markdown" | "text")
            
        Returns:
            (是否成功, 消息)
        """
        from domain.llm.conversation import format_messages_for_export
        
        messages = self.get_messages(state)
        
        if not messages:
            return False, "没有消息可导出"
        
        try:
            if format == "json":
                content = json.dumps(
                    [msg.to_dict() for msg in messages],
                    ensure_ascii=False,
                    indent=2
                )
            else:
                content = format_messages_for_export(messages, format)
            
            Path(path).write_text(content, encoding="utf-8")
            
            if self.logger:
                self.logger.info(f"会话已导出: {path}")
            
            return True, f"已导出 {len(messages)} 条消息"
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"导出失败: {e}")
            return False, str(e)
    
    def import_session(
        self,
        path: str,
        state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        导入历史会话
        
        通过 MessageAdapter 更新 GraphState。
        
        Args:
            path: 导入路径（JSON 格式）
            state: 当前状态
            
        Returns:
            (更新后的状态, 是否成功, 消息)
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            
            # 解析消息
            if isinstance(data, list):
                messages_data = data
            elif isinstance(data, dict) and "messages" in data:
                messages_data = data["messages"]
            else:
                return state, False, "无效的会话文件格式"
            
            # 重建消息（内部格式）
            messages = [Message.from_dict(m) for m in messages_data]
            
            # 通过 MessageAdapter 更新状态
            new_state = self._message_adapter.update_state_messages(state, messages)
            
            if self.logger:
                self.logger.info(f"会话已导入: {path}")
            
            return new_state, True, f"已导入 {len(messages)} 条消息"
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"导入失败: {e}")
            return state, False, str(e)


    # ============================================================
    # 文件名处理方法
    # ============================================================
    
    def _safe_filename(self, name: str) -> str:
        """
        将会话名称转换为安全的文件名
        
        处理规则：
        - 替换特殊字符 /\\:*?"<>| 为下划线
        - 限制长度不超过 100 字符
        - 超长时截断并添加哈希后缀
        
        Args:
            name: 会话名称
            
        Returns:
            str: 安全的文件名（不含扩展名）
        """
        import hashlib
        
        # 替换特殊字符
        safe_name = name
        for char in UNSAFE_FILENAME_CHARS:
            safe_name = safe_name.replace(char, '_')
        
        # 处理长度限制
        if len(safe_name) > MAX_FILENAME_LENGTH:
            # 截断并添加哈希后缀以保证唯一性
            hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
            safe_name = safe_name[:MAX_FILENAME_LENGTH - 9] + '_' + hash_suffix
        
        return safe_name
    
    def _get_session_file_path(
        self,
        project_path: str,
        session_name: str
    ) -> Path:
        """
        获取会话文件完整路径
        
        Args:
            project_path: 项目路径
            session_name: 会话名称
            
        Returns:
            Path: 会话文件路径
        """
        safe_name = self._safe_filename(session_name)
        return (
            Path(project_path) / ".circuit_ai" / CONVERSATIONS_DIR / f"{safe_name}.json"
        )
    
    def _get_sessions_index_path(self, project_path: str) -> Path:
        """
        获取会话索引文件路径
        
        Args:
            project_path: 项目路径
            
        Returns:
            Path: 索引文件路径
        """
        return (
            Path(project_path) / ".circuit_ai" / CONVERSATIONS_DIR / SESSIONS_INDEX_FILE
        )
    
    def _load_sessions_index(self, project_path: str) -> Dict[str, Any]:
        """
        加载会话索引文件
        
        Args:
            project_path: 项目路径
            
        Returns:
            Dict: 索引数据，若不存在则返回空结构
        """
        index_path = self._get_sessions_index_path(project_path)
        
        if not index_path.exists():
            return {
                "current_session_name": "",
                "sessions": []
            }
        
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载会话索引失败: {e}")
            return {
                "current_session_name": "",
                "sessions": []
            }
    
    def _save_sessions_index(
        self,
        project_path: str,
        index_data: Dict[str, Any]
    ) -> bool:
        """
        保存会话索引文件
        
        Args:
            project_path: 项目路径
            index_data: 索引数据
            
        Returns:
            bool: 是否成功
        """
        index_path = self._get_sessions_index_path(project_path)
        
        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(
                json.dumps(index_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"保存会话索引失败: {e}")
            return False
    
    def _update_sessions_index(
        self,
        project_path: str,
        session_info: Dict[str, Any],
        set_current: bool = True
    ) -> bool:
        """
        更新会话索引
        
        Args:
            project_path: 项目路径
            session_info: 会话信息（name, file_name, created_at, updated_at, message_count, preview）
            set_current: 是否设置为当前会话
            
        Returns:
            bool: 是否成功
        """
        index_data = self._load_sessions_index(project_path)
        
        session_name = session_info.get("name", "")
        
        # 查找是否已存在
        existing_idx = None
        for i, s in enumerate(index_data["sessions"]):
            if s.get("name") == session_name:
                existing_idx = i
                break
        
        if existing_idx is not None:
            # 更新现有记录
            index_data["sessions"][existing_idx].update(session_info)
        else:
            # 添加新记录
            index_data["sessions"].append(session_info)
        
        # 设置当前会话
        if set_current:
            index_data["current_session_name"] = session_name
        
        return self._save_sessions_index(project_path, index_data)
    
    # ============================================================
    # 会话管理方法
    # ============================================================
    
    def save_session(
        self,
        state: Dict[str, Any],
        project_path: str,
        session_name: str
    ) -> Tuple[bool, str]:
        """
        保存会话到文件
        
        使用会话名称作为文件名（经过安全处理）。
        
        Args:
            state: 当前状态
            project_path: 项目路径
            session_name: 会话名称
            
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            messages = self.get_messages(state)
            safe_name = self._safe_filename(session_name)
            
            # 获取首条用户消息作为预览
            preview = ""
            for msg in messages:
                if msg.is_user():
                    preview = msg.content[:50]
                    break
            
            # 构建会话数据
            session_data = {
                "name": session_name,
                "file_name": safe_name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "messages": [msg.to_dict() for msg in messages],
                "summary": self.get_summary(state),
                "ui_state": {
                    "scroll_position": 0,
                }
            }
            
            # 确定保存路径
            session_file = self._get_session_file_path(project_path, session_name)
            
            try:
                # 创建目录
                session_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 写入文件
                session_file.write_text(
                    json.dumps(session_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                
                # 更新索引
                self._update_sessions_index(project_path, {
                    "name": session_name,
                    "file_name": safe_name,
                    "created_at": session_data["created_at"],
                    "updated_at": session_data["updated_at"],
                    "message_count": len(messages),
                    "preview": preview,
                })
                
                if self.logger:
                    self.logger.info(f"会话已保存: {session_name}")
                
                return True, session_name
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"保存会话失败: {e}")
                return False, str(e)
    
    def load_session(
        self,
        project_path: str,
        session_name: str,
        state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool, str, Optional[Dict[str, Any]]]:
        """
        加载指定会话
        
        Args:
            project_path: 项目路径
            session_name: 会话名称
            state: 当前状态
            
        Returns:
            (更新后的状态, 是否成功, 消息, 会话元数据)
        """
        session_file = self._get_session_file_path(project_path, session_name)
        
        if not session_file.exists():
            return state, False, f"会话文件不存在: {session_name}", None
        
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            
            # 重建消息
            messages_data = data.get("messages", [])
            messages = [Message.from_dict(m) for m in messages_data]
            
            # 更新状态
            new_state = self._message_adapter.update_state_messages(state, messages)
            new_state["conversation_summary"] = data.get("summary", "")
            
            # 提取元数据
            metadata = {
                "name": data.get("name", session_name),
                "file_name": data.get("file_name", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": data.get("message_count", 0),
                "ui_state": data.get("ui_state", {}),
            }
            
            # 更新索引中的当前会话
            index_data = self._load_sessions_index(project_path)
            index_data["current_session_name"] = session_name
            self._save_sessions_index(project_path, index_data)
            
            if self.logger:
                self.logger.info(f"会话已加载: {session_name}")
            
            return new_state, True, f"已加载 {len(messages)} 条消息", metadata
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载会话失败: {e}")
            return state, False, str(e), None
    
    def load_current_session(
        self,
        project_path: str,
        state: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool, str, Optional[Dict[str, Any]]]:
        """
        加载当前会话
        
        从 sessions.json 获取 current_session_name，然后加载对应会话文件。
        
        Args:
            project_path: 项目路径
            state: 当前状态
            
        Returns:
            (更新后的状态, 是否成功, 消息, 会话元数据)
        """
        index_data = self._load_sessions_index(project_path)
        current_name = index_data.get("current_session_name", "")
        
        if not current_name:
            return state, False, "没有当前会话", None
        
        return self.load_session(project_path, current_name, state)
    
    def save_current_session(
        self,
        state: Dict[str, Any],
        project_path: str,
        session_name: str
    ) -> Tuple[bool, str]:
        """
        保存当前会话
        
        Args:
            state: 当前状态
            project_path: 项目路径
            session_name: 会话名称
            
        Returns:
            (是否成功, 消息)
        """
        return self.save_session(state, project_path, session_name)
    
    def create_new_session(
        self,
        state: Dict[str, Any],
        project_path: str,
        session_name: str,
        save_current: bool = True,
        current_session_name: str = ""
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        创建新会话
        
        Args:
            state: 当前状态
            project_path: 项目路径
            session_name: 新会话名称
            save_current: 是否保存当前会话
            current_session_name: 当前会话名称（用于保存）
            
        Returns:
            (更新后的状态, 是否成功, 消息)
        """
        with self._lock:
            # 保存当前会话（如果有消息且需要保存）
            if save_current and current_session_name:
                messages = self.get_messages(state)
                if messages:
                    success, msg = self.save_session(
                        state, project_path, current_session_name
                    )
                    if not success:
                        if self.logger:
                            self.logger.warning(f"保存当前会话失败: {msg}")
            
            # 重置消息列表
            new_state = self.reset_messages(state, keep_system=True)
            
            # 创建新会话文件
            success, msg = self.save_session(
                new_state, project_path, session_name
            )
            
            if success:
                if self.logger:
                    self.logger.info(f"新会话已创建: {session_name}")
                return new_state, True, f"新会话已创建: {session_name}"
            else:
                return new_state, False, f"创建新会话失败: {msg}"
    
    def delete_session(
        self,
        project_path: str,
        session_name: str
    ) -> Tuple[bool, str]:
        """
        删除会话
        
        Args:
            project_path: 项目路径
            session_name: 会话名称
            
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            session_file = self._get_session_file_path(project_path, session_name)
            
            try:
                # 删除文件
                if session_file.exists():
                    session_file.unlink()
                
                # 更新索引
                index_data = self._load_sessions_index(project_path)
                index_data["sessions"] = [
                    s for s in index_data["sessions"]
                    if s.get("name") != session_name
                ]
                
                # 如果删除的是当前会话，清空 current_session_name
                if index_data.get("current_session_name") == session_name:
                    index_data["current_session_name"] = ""
                
                self._save_sessions_index(project_path, index_data)
                
                if self.logger:
                    self.logger.info(f"会话已删除: {session_name}")
                
                return True, f"会话已删除: {session_name}"
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"删除会话失败: {e}")
                return False, str(e)
    
    def rename_session(
        self,
        project_path: str,
        old_name: str,
        new_name: str
    ) -> Tuple[bool, str]:
        """
        重命名会话
        
        Args:
            project_path: 项目路径
            old_name: 旧会话名称
            new_name: 新会话名称
            
        Returns:
            (是否成功, 消息)
        """
        with self._lock:
            old_file = self._get_session_file_path(project_path, old_name)
            new_file = self._get_session_file_path(project_path, new_name)
            
            if not old_file.exists():
                return False, f"会话不存在: {old_name}"
            
            if new_file.exists() and old_file != new_file:
                return False, f"会话名称已存在: {new_name}"
            
            try:
                # 读取旧文件
                data = json.loads(old_file.read_text(encoding="utf-8"))
                
                # 更新会话数据
                new_safe_name = self._safe_filename(new_name)
                data["name"] = new_name
                data["file_name"] = new_safe_name
                data["updated_at"] = datetime.now().isoformat()
                
                # 写入新文件
                new_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                
                # 删除旧文件（如果文件名不同）
                if old_file != new_file:
                    old_file.unlink()
                
                # 更新索引
                index_data = self._load_sessions_index(project_path)
                for s in index_data["sessions"]:
                    if s.get("name") == old_name:
                        s["name"] = new_name
                        s["file_name"] = new_safe_name
                        s["updated_at"] = data["updated_at"]
                        break
                
                # 更新当前会话名称
                if index_data.get("current_session_name") == old_name:
                    index_data["current_session_name"] = new_name
                
                self._save_sessions_index(project_path, index_data)
                
                if self.logger:
                    self.logger.info(f"会话已重命名: {old_name} -> {new_name}")
                
                return True, f"会话已重命名: {new_name}"
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"重命名会话失败: {e}")
                return False, str(e)
    
    def get_all_sessions(
        self,
        project_path: str,
        sync_with_files: bool = True
    ) -> List[Dict[str, Any]]:
        """
        获取所有会话列表
        
        同时检查索引文件和实际会话文件，确保同步一致。
        
        Args:
            project_path: 项目路径
            sync_with_files: 是否与实际文件同步（默认 True）
            
        Returns:
            会话列表
        """
        index_data = self._load_sessions_index(project_path)
        indexed_sessions = index_data.get("sessions", [])
        
        if not sync_with_files:
            return indexed_sessions
        
        # 扫描实际的会话文件
        conversations_dir = Path(project_path) / ".circuit_ai" / CONVERSATIONS_DIR
        if not conversations_dir.exists():
            return indexed_sessions
        
        # 构建索引中的会话名称集合
        indexed_names = {s.get("name", "") for s in indexed_sessions}
        
        # 扫描目录中的 JSON 文件（排除 sessions.json）
        updated = False
        for file_path in conversations_dir.glob("*.json"):
            if file_path.name == SESSIONS_INDEX_FILE:
                continue
            
            # 尝试读取文件获取会话信息
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                session_name = data.get("name", "")
                
                if session_name and session_name not in indexed_names:
                    # 文件存在但不在索引中，添加到索引
                    new_session_info = {
                        "name": session_name,
                        "file_name": data.get("file_name", file_path.stem),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "message_count": data.get("message_count", 0),
                        "preview": self._extract_preview(data.get("messages", [])),
                    }
                    indexed_sessions.append(new_session_info)
                    indexed_names.add(session_name)
                    updated = True
                    
                    if self.logger:
                        self.logger.info(f"Added missing session to index: {session_name}")
                        
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to read session file {file_path}: {e}")
                continue
        
        # 检查索引中的会话是否都有对应文件
        valid_sessions = []
        for session in indexed_sessions:
            session_name = session.get("name", "")
            if not session_name:
                continue
            
            session_file = self._get_session_file_path(project_path, session_name)
            if session_file.exists():
                valid_sessions.append(session)
            else:
                # 文件不存在，从索引中移除
                updated = True
                if self.logger:
                    self.logger.info(f"Removed orphan session from index: {session_name}")
        
        # 如果有更新，保存索引
        if updated:
            index_data["sessions"] = valid_sessions
            self._save_sessions_index(project_path, index_data)
        
        return valid_sessions
    
    def _extract_preview(self, messages: List[Dict[str, Any]]) -> str:
        """从消息列表中提取预览文本"""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                return content[:50] if content else ""
        return ""
    
    def get_current_session_name(self, project_path: str) -> str:
        """
        获取当前会话名称
        
        Args:
            project_path: 项目路径
            
        Returns:
            str: 当前会话名称
        """
        index_data = self._load_sessions_index(project_path)
        return index_data.get("current_session_name", "")
    
    def generate_session_name(self) -> str:
        """
        生成会话名称
        
        格式：Chat YYYY-MM-DD HH:mm（精确到分钟）
        
        Returns:
            str: 会话名称
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"Chat {now}"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "MessageStore",
    "IMPORTANCE_HIGH",
    "IMPORTANCE_MEDIUM",
    "IMPORTANCE_LOW",
    "CONVERSATIONS_DIR",
    "ARCHIVE_DIR",
    "SESSIONS_INDEX_FILE",
]
