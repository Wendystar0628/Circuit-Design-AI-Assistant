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

# 归档目录名
ARCHIVE_DIR = "conversations/archive"


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
# 模块导出
# ============================================================

__all__ = [
    "MessageStore",
    "IMPORTANCE_HIGH",
    "IMPORTANCE_MEDIUM",
    "IMPORTANCE_LOW",
    "ARCHIVE_DIR",
]
