# Conversation ViewModel - UI Data Layer
"""
对话面板 ViewModel - UI 与数据层的中间层

职责：
- 作为 UI 与 ContextManager 之间的中间层
- 将内部消息格式转换为 UI 友好的 DisplayMessage 格式
- 管理流式输出状态
- 处理建议选项消息
- 提供上下文使用信息

设计目标：
- UI 组件只依赖 ViewModel 提供的数据和方法
- 消息格式或 ContextManager 接口变化时，只需修改 ViewModel
- 便于单元测试（可 mock ViewModel）

使用示例：
    from presentation.panels.conversation.conversation_view_model import (
        ConversationViewModel
    )
    
    view_model = ConversationViewModel()
    view_model.load_messages(state)
    messages = view_model.messages
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

# ============================================================
# 常量定义
# ============================================================

# 消息角色（扩展，包含建议选项）
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_SUGGESTION = "suggestion"  # 建议选项消息

# 建议选项状态
SUGGESTION_STATE_ACTIVE = "active"      # 活跃，等待用户选择
SUGGESTION_STATE_SELECTED = "selected"  # 已选择
SUGGESTION_STATE_EXPIRED = "expired"    # 已过期（用户通过输入框发送了消息）

# 压缩按钮状态
COMPRESS_STATE_NORMAL = "normal"        # 正常，无需压缩
COMPRESS_STATE_WARNING = "warning"      # 警告，建议压缩
COMPRESS_STATE_CRITICAL = "critical"    # 危险，必须压缩


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SuggestionItem:
    """建议选项项"""
    id: str                    # 选项唯一标识
    label: str                 # 显示文本
    value: str                 # 选项值（发送给后端）
    description: str = ""      # 详细描述（可选）
    is_recommended: bool = False  # 是否推荐选项


@dataclass
class DisplayMessage:
    """
    UI 友好的消息格式
    
    用于在对话面板中显示，包含已渲染的 HTML 内容。
    """
    id: str                                      # 消息唯一标识
    role: str                                    # 角色（user/assistant/system/suggestion）
    content_html: str                            # 已渲染的 HTML 内容
    reasoning_html: str = ""                     # 思考过程 HTML（可选）
    operations: List[str] = field(default_factory=list)  # 操作摘要列表
    attachments: List[Dict[str, Any]] = field(default_factory=list)  # 附件列表
    timestamp_display: str = ""                  # 格式化的时间戳字符串
    is_streaming: bool = False                   # 是否正在流式输出
    
    # 建议选项相关（仅 role=suggestion 时有效）
    suggestions: List[SuggestionItem] = field(default_factory=list)
    status_summary: str = ""                     # 状态摘要文本
    suggestion_state: str = ""                   # 建议选项状态
    selected_suggestion_id: str = ""             # 已选择的建议 ID
    
    def is_suggestion(self) -> bool:
        """是否为建议选项消息"""
        return self.role == ROLE_SUGGESTION


# ============================================================
# ViewModel 类
# ============================================================

class ConversationViewModel(QObject):
    """
    对话面板 ViewModel
    
    作为 UI 与数据层之间的中间层，隔离 conversation_panel 与 ContextManager。
    """
    
    # 信号定义
    messages_changed = pyqtSignal()              # 消息列表变化
    stream_updated = pyqtSignal(str, str)        # 流式内容更新 (content, reasoning)
    stream_finished = pyqtSignal()               # 流式输出完成
    usage_changed = pyqtSignal(float)            # 上下文占用变化 (ratio)
    can_send_changed = pyqtSignal(bool)          # 可发送状态变化
    suggestion_added = pyqtSignal(str)           # 建议选项消息添加 (message_id)
    compress_suggested = pyqtSignal()            # 建议压缩上下文
    new_conversation_suggested = pyqtSignal()    # 建议开启新对话
    session_name_updated = pyqtSignal(str)       # 会话名称更新 (name)
    
    def __init__(self, parent: Optional[QObject] = None):
        """初始化 ViewModel"""
        super().__init__(parent)
        
        # 内部状态
        self._messages: List[DisplayMessage] = []
        self._usage_ratio: float = 0.0
        self._is_loading: bool = False
        self._can_send: bool = True
        self._current_stream_content: str = ""
        self._current_reasoning_content: str = ""
        self._active_suggestion_message_id: Optional[str] = None
        
        # 会话名称相关
        self._current_session_id: Optional[str] = None
        self._current_session_name: str = ""
        
        # 延迟获取的服务
        self._context_manager = None
        self._event_bus = None
        self._logger = None
        self._markdown_converter = None
        self._config_manager = None
        
        # 事件订阅句柄
        self._subscriptions: List[Callable] = []

    # ============================================================
    # 属性
    # ============================================================
    
    @property
    def messages(self) -> List[DisplayMessage]:
        """获取格式化后的消息列表"""
        return self._messages
    
    @property
    def usage_ratio(self) -> float:
        """获取上下文占用比例（0-1）"""
        return self._usage_ratio
    
    @property
    def compress_button_state(self) -> str:
        """获取压缩按钮状态"""
        try:
            from infrastructure.config.settings import (
                COMPRESS_HINT_THRESHOLD,
                COMPRESS_AUTO_THRESHOLD,
            )
        except ImportError:
            COMPRESS_HINT_THRESHOLD = 0.60
            COMPRESS_AUTO_THRESHOLD = 0.80
        
        if self._usage_ratio >= COMPRESS_AUTO_THRESHOLD:
            return COMPRESS_STATE_CRITICAL
        elif self._usage_ratio >= COMPRESS_HINT_THRESHOLD:
            return COMPRESS_STATE_WARNING
        return COMPRESS_STATE_NORMAL
    
    @property
    def is_loading(self) -> bool:
        """是否正在加载"""
        return self._is_loading
    
    @property
    def current_stream_content(self) -> str:
        """当前流式输出内容"""
        return self._current_stream_content
    
    @property
    def current_reasoning_content(self) -> str:
        """当前思考过程内容"""
        return self._current_reasoning_content
    
    @property
    def active_suggestion_message_id(self) -> Optional[str]:
        """当前活跃的建议选项消息 ID"""
        return self._active_suggestion_message_id
    
    @property
    def can_send(self) -> bool:
        """是否可以发送消息"""
        return self._can_send and not self._is_loading
    
    @property
    def current_session_id(self) -> Optional[str]:
        """当前会话 ID"""
        return self._current_session_id
    
    @property
    def current_session_name(self) -> str:
        """当前会话名称"""
        return self._current_session_name
    
    # ============================================================
    # 延迟获取服务
    # ============================================================
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("conversation_view_model")
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
    
    @property
    def context_manager(self):
        """延迟获取上下文管理器"""
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager
    
    @property
    def config_manager(self):
        """延迟获取配置管理器"""
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager
    
    def _get_markdown_converter(self):
        """获取 Markdown 转换器"""
        if self._markdown_converter is None:
            try:
                import markdown
                self._markdown_converter = markdown.Markdown(
                    extensions=['fenced_code', 'tables', 'nl2br']
                )
            except ImportError:
                self._markdown_converter = None
        return self._markdown_converter

    # ============================================================
    # 初始化和清理
    # ============================================================
    
    def initialize(self) -> None:
        """初始化 ViewModel，订阅事件"""
        self._subscribe_events()
    
    def cleanup(self) -> None:
        """清理资源，取消事件订阅"""
        self._unsubscribe_events()
        self.clear()
    
    def _subscribe_events(self) -> None:
        """订阅事件"""
        if self.event_bus is None:
            return
        
        try:
            from shared.event_types import (
                EVENT_LLM_CHUNK,
                EVENT_LLM_COMPLETE,
                EVENT_ITERATION_AWAITING_CONFIRMATION,
                EVENT_WORKFLOW_LOCKED,
                EVENT_WORKFLOW_UNLOCKED,
                EVENT_CONTEXT_COMPRESS_COMPLETE,
            )
            
            self.event_bus.subscribe(EVENT_LLM_CHUNK, self._on_llm_chunk)
            self.event_bus.subscribe(EVENT_LLM_COMPLETE, self._on_llm_complete)
            self.event_bus.subscribe(
                EVENT_ITERATION_AWAITING_CONFIRMATION,
                self._on_iteration_awaiting
            )
            self.event_bus.subscribe(EVENT_WORKFLOW_LOCKED, self._on_workflow_locked)
            self.event_bus.subscribe(EVENT_WORKFLOW_UNLOCKED, self._on_workflow_unlocked)
            self.event_bus.subscribe(
                EVENT_CONTEXT_COMPRESS_COMPLETE,
                self._on_compress_complete
            )
            
        except ImportError:
            if self.logger:
                self.logger.warning("无法导入事件类型，事件订阅跳过")
    
    def _unsubscribe_events(self) -> None:
        """取消事件订阅"""
        if self.event_bus is None:
            return
        
        try:
            from shared.event_types import (
                EVENT_LLM_CHUNK,
                EVENT_LLM_COMPLETE,
                EVENT_ITERATION_AWAITING_CONFIRMATION,
                EVENT_WORKFLOW_LOCKED,
                EVENT_WORKFLOW_UNLOCKED,
                EVENT_CONTEXT_COMPRESS_COMPLETE,
            )
            
            self.event_bus.unsubscribe(EVENT_LLM_CHUNK, self._on_llm_chunk)
            self.event_bus.unsubscribe(EVENT_LLM_COMPLETE, self._on_llm_complete)
            self.event_bus.unsubscribe(
                EVENT_ITERATION_AWAITING_CONFIRMATION,
                self._on_iteration_awaiting
            )
            self.event_bus.unsubscribe(EVENT_WORKFLOW_LOCKED, self._on_workflow_locked)
            self.event_bus.unsubscribe(EVENT_WORKFLOW_UNLOCKED, self._on_workflow_unlocked)
            self.event_bus.unsubscribe(
                EVENT_CONTEXT_COMPRESS_COMPLETE,
                self._on_compress_complete
            )
            
        except ImportError:
            pass
    
    # ============================================================
    # 消息加载和转换
    # ============================================================
    
    def load_messages(self, state: Optional[Dict[str, Any]] = None) -> None:
        """
        从 ContextManager 加载消息并转换为显示格式
        
        Args:
            state: 可选的状态字典，若不提供则从 ContextManager 获取
        """
        if self.context_manager is None:
            if self.logger:
                self.logger.warning("ContextManager 不可用，无法加载消息")
            return
        
        try:
            # 获取内部消息
            if state is not None:
                from domain.llm.message_adapter import MessageAdapter
                adapter = MessageAdapter()
                internal_messages = adapter.extract_messages_from_state(state)
            else:
                # 使用有状态版本的方法
                internal_messages = self.context_manager.get_display_messages()
            
            # 转换为显示格式
            self._messages = [
                self.format_message(msg) for msg in internal_messages
                if not msg.is_system()  # 不显示系统消息
            ]
            
            # 更新使用率
            self._update_usage_ratio()
            
            # 发出信号
            self.messages_changed.emit()
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载消息失败: {e}")
    
    def format_message(self, internal_msg) -> DisplayMessage:
        """
        将内部消息转换为 DisplayMessage
        
        Args:
            internal_msg: 内部消息对象（Message 类型）
            
        Returns:
            DisplayMessage: UI 友好的消息格式
        """
        # 生成唯一 ID
        msg_id = internal_msg.metadata.get("id", str(uuid.uuid4()))
        
        # 转换 Markdown 为 HTML
        content_html = self._markdown_to_html(internal_msg.content)
        reasoning_html = ""
        if internal_msg.reasoning_content:
            reasoning_html = self._markdown_to_html(internal_msg.reasoning_content)
        
        # 格式化时间戳
        timestamp_display = self._format_timestamp(internal_msg.timestamp)
        
        # 转换附件
        attachments = [
            att.to_dict() if hasattr(att, 'to_dict') else att
            for att in internal_msg.attachments
        ]
        
        return DisplayMessage(
            id=msg_id,
            role=internal_msg.role,
            content_html=content_html,
            reasoning_html=reasoning_html,
            operations=internal_msg.operations.copy(),
            attachments=attachments,
            timestamp_display=timestamp_display,
            is_streaming=False,
        )

    # ============================================================
    # 流式输出处理
    # ============================================================
    
    def append_stream_chunk(
        self,
        chunk: str,
        chunk_type: str = "content"
    ) -> None:
        """
        追加流式输出块
        
        Args:
            chunk: 输出块内容
            chunk_type: 块类型（"content" 或 "reasoning"）
        """
        if chunk_type == "reasoning":
            self._current_reasoning_content += chunk
        else:
            self._current_stream_content += chunk
        
        # 发出更新信号
        self.stream_updated.emit(
            self._current_stream_content,
            self._current_reasoning_content
        )
    
    def finalize_stream(self) -> DisplayMessage:
        """
        完成流式输出，生成完整消息
        
        Returns:
            DisplayMessage: 完成的消息
        """
        # 转换为 HTML
        content_html = self._markdown_to_html(self._current_stream_content)
        reasoning_html = ""
        if self._current_reasoning_content:
            reasoning_html = self._markdown_to_html(self._current_reasoning_content)
        
        # 创建消息
        msg = DisplayMessage(
            id=str(uuid.uuid4()),
            role=ROLE_ASSISTANT,
            content_html=content_html,
            reasoning_html=reasoning_html,
            timestamp_display=self._format_timestamp(datetime.now().isoformat()),
            is_streaming=False,
        )
        
        # 添加到消息列表
        self._messages.append(msg)
        
        # 清空流式状态
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self._is_loading = False
        
        # 发出信号
        self.stream_finished.emit()
        self.messages_changed.emit()
        
        return msg
    
    def start_streaming(self) -> None:
        """开始流式输出"""
        self._is_loading = True
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self.can_send_changed.emit(False)
    
    # ============================================================
    # 建议选项消息处理
    # ============================================================
    
    def append_suggestion_message(
        self,
        suggestions: List[Dict[str, Any]],
        status_summary: str = ""
    ) -> str:
        """
        追加建议选项消息
        
        Args:
            suggestions: 建议选项列表
            status_summary: 状态摘要文本
            
        Returns:
            str: 消息 ID
        """
        # 转换建议选项
        suggestion_items = [
            SuggestionItem(
                id=s.get("id", str(uuid.uuid4())),
                label=s.get("label", ""),
                value=s.get("value", ""),
                description=s.get("description", ""),
                is_recommended=s.get("is_recommended", False),
            )
            for s in suggestions
        ]
        
        # 创建消息
        msg_id = str(uuid.uuid4())
        msg = DisplayMessage(
            id=msg_id,
            role=ROLE_SUGGESTION,
            content_html="",
            suggestions=suggestion_items,
            status_summary=status_summary,
            suggestion_state=SUGGESTION_STATE_ACTIVE,
            timestamp_display=self._format_timestamp(datetime.now().isoformat()),
        )
        
        # 标记之前的建议选项为过期
        self._expire_previous_suggestions()
        
        # 添加到消息列表
        self._messages.append(msg)
        self._active_suggestion_message_id = msg_id
        
        # 发出信号
        self.suggestion_added.emit(msg_id)
        self.messages_changed.emit()
        
        return msg_id
    
    def mark_suggestion_selected(self, suggestion_id: str) -> None:
        """
        标记建议选项已选择
        
        Args:
            suggestion_id: 选择的建议选项 ID
        """
        if self._active_suggestion_message_id is None:
            return
        
        for msg in self._messages:
            if msg.id == self._active_suggestion_message_id:
                msg.suggestion_state = SUGGESTION_STATE_SELECTED
                msg.selected_suggestion_id = suggestion_id
                break
        
        self._active_suggestion_message_id = None
        self.messages_changed.emit()
    
    def mark_suggestion_expired(self) -> None:
        """标记当前建议选项已过期"""
        self._expire_previous_suggestions()
        self._active_suggestion_message_id = None
        self.messages_changed.emit()
    
    def _expire_previous_suggestions(self) -> None:
        """将所有活跃的建议选项标记为过期"""
        for msg in self._messages:
            if msg.is_suggestion() and msg.suggestion_state == SUGGESTION_STATE_ACTIVE:
                msg.suggestion_state = SUGGESTION_STATE_EXPIRED

    # ============================================================
    # 消息发送和压缩
    # ============================================================
    
    def send_message(
        self,
        text: str,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        发送消息
        
        Args:
            text: 消息文本
            attachments: 附件列表
            
        Returns:
            bool: 是否成功发送
        """
        if not self.can_send:
            return False
        
        if not text.strip():
            return False
        
        # 标记之前的建议选项为过期
        if self._active_suggestion_message_id:
            self.mark_suggestion_expired()
        
        # 创建用户消息显示
        user_msg = DisplayMessage(
            id=str(uuid.uuid4()),
            role=ROLE_USER,
            content_html=self._markdown_to_html(text),
            attachments=attachments or [],
            timestamp_display=self._format_timestamp(datetime.now().isoformat()),
        )
        self._messages.append(user_msg)
        self.messages_changed.emit()
        
        # 开始加载状态
        self.start_streaming()
        
        # 委托给 ContextManager 发送（使用有状态便捷方法）
        if self.context_manager:
            try:
                from domain.llm.message_types import Attachment
                
                # 转换附件为 Attachment 对象列表
                att_list = None
                if attachments:
                    att_list = []
                    for att in attachments:
                        att_list.append(Attachment(
                            type=att.get("type", "file"),
                            path=att.get("path", ""),
                            name=att.get("name", ""),
                        ))
                
                # 使用有状态便捷方法添加用户消息
                self.context_manager.add_user_message(text, att_list)
                return True
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"发送消息失败: {e}")
                self._is_loading = False
                self.can_send_changed.emit(True)
                return False
        
        return False
    
    def add_assistant_message(
        self,
        content: str,
        reasoning_content: str = "",
    ) -> None:
        """
        添加助手消息到消息列表
        
        Args:
            content: 消息内容
            reasoning_content: 思考过程内容
        """
        # 转换为 HTML
        content_html = self._markdown_to_html(content)
        reasoning_html = ""
        if reasoning_content:
            reasoning_html = self._markdown_to_html(reasoning_content)
        
        # 创建消息
        msg = DisplayMessage(
            id=str(uuid.uuid4()),
            role=ROLE_ASSISTANT,
            content_html=content_html,
            reasoning_html=reasoning_html,
            timestamp_display=self._format_timestamp(datetime.now().isoformat()),
            is_streaming=False,
        )
        
        # 添加到消息列表
        self._messages.append(msg)
        
        # 更新状态
        self._is_loading = False
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        
        # 发出信号
        self.can_send_changed.emit(True)
    
    def request_compress(self) -> None:
        """请求压缩上下文"""
        if self.context_manager:
            try:
                self.context_manager.request_compress()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"请求压缩失败: {e}")
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def get_usage_info(self) -> Dict[str, Any]:
        """
        获取上下文使用信息
        
        Returns:
            Dict: 包含 ratio, used_tokens, total_tokens, state 等信息
        """
        return {
            "ratio": self._usage_ratio,
            "state": self.compress_button_state,
            "message_count": len(self._messages),
        }
    
    def clear(self) -> None:
        """清空显示数据"""
        self._messages.clear()
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self._is_loading = False
        self._active_suggestion_message_id = None
        self.messages_changed.emit()
    
    # ============================================================
    # 会话名称管理
    # ============================================================
    
    def generate_unique_session_name(self) -> str:
        """
        生成唯一的会话名称
        
        命名规则：
        - 基础格式："新对话 YYYY-MM-DD"
        - 若当天已有同名会话，追加序号："新对话 YYYY-MM-DD (2)"
        - 序号从 2 开始递增，直到找到唯一名称
        
        Returns:
            str: 唯一的会话名称
        """
        today = datetime.now().strftime("%Y-%m-%d")
        base_name = f"新对话 {today}"
        
        # 获取已存在的会话名称列表
        existing_names = self._get_existing_session_names()
        
        # 检查基础名称是否可用
        if base_name not in existing_names:
            return base_name
        
        # 追加序号直到找到唯一名称
        counter = 2
        while True:
            candidate_name = f"{base_name} ({counter})"
            if candidate_name not in existing_names:
                return candidate_name
            counter += 1
            # 安全限制，防止无限循环
            if counter > 1000:
                # 使用时间戳作为后备方案
                timestamp = datetime.now().strftime("%H%M%S")
                return f"{base_name} ({timestamp})"
    
    def _get_existing_session_names(self) -> set:
        """
        获取已存在的会话名称集合
        
        从配置和归档中收集所有已使用的会话名称。
        
        Returns:
            set: 已存在的会话名称集合
        """
        existing_names = set()
        
        # 从配置中获取当前会话名称
        if self.config_manager:
            current_name = self.config_manager.get("current_conversation_name")
            if current_name:
                existing_names.add(current_name)
        
        # 从归档中获取历史会话名称
        if self.context_manager:
            try:
                # 获取项目路径
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_APP_STATE
                from shared.app_state import STATE_PROJECT_PATH
                
                app_state = ServiceLocator.get_optional(SVC_APP_STATE)
                if app_state:
                    project_path = app_state.get(STATE_PROJECT_PATH)
                    if project_path:
                        archived = self.context_manager.get_archived_sessions(project_path)
                        for session in archived:
                            name = session.get("name") or session.get("session_id", "")
                            if name:
                                existing_names.add(name)
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"获取归档会话名称失败: {e}")
        
        return existing_names
    
    def set_session_name(self, name: str) -> None:
        """
        设置当前会话名称
        
        Args:
            name: 会话名称
        """
        self._current_session_name = name
        self.session_name_updated.emit(name)
        
        # 保存到配置
        if self.config_manager:
            self.config_manager.set("current_conversation_name", name)
    
    def get_session_name(self) -> str:
        """
        获取当前会话名称
        
        Returns:
            str: 会话名称
        """
        return self._current_session_name
    
    def set_session_id(self, session_id: str) -> None:
        """
        设置当前会话 ID
        
        Args:
            session_id: 会话 ID
        """
        self._current_session_id = session_id
        
        # 保存到配置
        if self.config_manager:
            self.config_manager.set("current_conversation_id", session_id)
    
    def reset_session(self) -> str:
        """
        重置会话（新开对话时调用）
        
        生成新的会话 ID 和唯一名称。
        
        Returns:
            str: 新的会话名称
        """
        # 生成新的会话 ID
        self._current_session_id = str(uuid.uuid4())
        
        # 生成唯一的会话名称
        self._current_session_name = self.generate_unique_session_name()
        
        # 保存到配置
        if self.config_manager:
            self.config_manager.set("current_conversation_id", self._current_session_id)
            self.config_manager.set("current_conversation_name", self._current_session_name)
        
        # 发出信号
        self.session_name_updated.emit(self._current_session_name)
        
        return self._current_session_name
    
    def _update_usage_ratio(self) -> None:
        """更新上下文占用比例"""
        if self.context_manager:
            try:
                # 使用有状态版本的方法
                self._usage_ratio = self.context_manager.get_usage_ratio_stateful()
                self.usage_changed.emit(self._usage_ratio)
            except Exception:
                pass
    
    def _markdown_to_html(self, text: str) -> str:
        """
        将 Markdown 转换为 HTML
        
        Args:
            text: Markdown 文本
            
        Returns:
            str: HTML 字符串
        """
        if not text:
            return ""
        
        converter = self._get_markdown_converter()
        if converter:
            try:
                converter.reset()
                return converter.convert(text)
            except Exception:
                pass
        
        # 回退：简单转义
        return text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    
    def _format_timestamp(self, iso_timestamp: str) -> str:
        """
        格式化时间戳为显示字符串
        
        Args:
            iso_timestamp: ISO 格式时间戳
            
        Returns:
            str: 格式化的时间字符串
        """
        if not iso_timestamp:
            return ""
        
        try:
            dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            now = datetime.now()
            
            # 今天的消息只显示时间
            if dt.date() == now.date():
                return dt.strftime("%H:%M")
            # 昨天的消息
            elif (now.date() - dt.date()).days == 1:
                return f"昨天 {dt.strftime('%H:%M')}"
            # 更早的消息显示日期
            else:
                return dt.strftime("%m-%d %H:%M")
                
        except Exception:
            return ""

    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_llm_chunk(self, event_data: Dict[str, Any]) -> None:
        """处理 LLM 流式输出块事件"""
        data = event_data.get("data", {})
        chunk = data.get("chunk", "")
        chunk_type = data.get("type", "content")
        
        if chunk:
            self.append_stream_chunk(chunk, chunk_type)
    
    def _on_llm_complete(self, event_data: Dict[str, Any]) -> None:
        """处理 LLM 输出完成事件"""
        data = event_data.get("data", {})
        
        # 如果有完整消息，使用它
        if "message" in data:
            msg_data = data["message"]
            content_html = self._markdown_to_html(msg_data.get("content", ""))
            reasoning_html = ""
            if msg_data.get("reasoning_content"):
                reasoning_html = self._markdown_to_html(msg_data["reasoning_content"])
            
            msg = DisplayMessage(
                id=str(uuid.uuid4()),
                role=ROLE_ASSISTANT,
                content_html=content_html,
                reasoning_html=reasoning_html,
                operations=msg_data.get("operations", []),
                timestamp_display=self._format_timestamp(datetime.now().isoformat()),
            )
            self._messages.append(msg)
        else:
            # 否则使用流式内容
            self.finalize_stream()
        
        # 更新状态
        self._is_loading = False
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self._update_usage_ratio()
        
        # 发出信号
        self.stream_finished.emit()
        self.messages_changed.emit()
        self.can_send_changed.emit(True)
    
    def _on_iteration_awaiting(self, event_data: Dict[str, Any]) -> None:
        """处理迭代等待确认事件"""
        data = event_data.get("data", {})
        suggestions = data.get("suggestions", [])
        status_summary = data.get("status_summary", "")
        
        if suggestions:
            self.append_suggestion_message(suggestions, status_summary)
    
    def _on_workflow_locked(self, event_data: Dict[str, Any]) -> None:
        """处理工作流锁定事件"""
        self._can_send = False
        self.can_send_changed.emit(False)
    
    def _on_workflow_unlocked(self, event_data: Dict[str, Any]) -> None:
        """处理工作流解锁事件"""
        self._can_send = True
        if not self._is_loading:
            self.can_send_changed.emit(True)
    
    def _on_compress_complete(self, event_data: Dict[str, Any]) -> None:
        """处理压缩完成事件"""
        data = event_data.get("data", {})
        status = data.get("status", "")
        
        if status == "completed":
            # 重新加载消息
            self.load_messages()
        elif status == "suggest_new_conversation":
            # 建议开启新对话
            self.new_conversation_suggested.emit()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 常量
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_SUGGESTION",
    "SUGGESTION_STATE_ACTIVE",
    "SUGGESTION_STATE_SELECTED",
    "SUGGESTION_STATE_EXPIRED",
    "COMPRESS_STATE_NORMAL",
    "COMPRESS_STATE_WARNING",
    "COMPRESS_STATE_CRITICAL",
    # 数据结构
    "SuggestionItem",
    "DisplayMessage",
    # 类
    "ConversationViewModel",
]
