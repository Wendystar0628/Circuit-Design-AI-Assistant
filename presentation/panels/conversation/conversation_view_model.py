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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    content: str = ""                            # 原始内容（用于 LaTeX 检测）
    reasoning_html: str = ""                     # 思考过程 HTML（可选）
    operations: List[str] = field(default_factory=list)  # 操作摘要列表
    attachments: List[Dict[str, Any]] = field(default_factory=list)  # 附件列表
    timestamp_display: str = ""                  # 格式化的时间戳字符串
    is_streaming: bool = False                   # 是否正在流式输出
    is_partial: bool = False                     # 是否为部分响应（已中断）
    stop_reason: str = ""                        # 停止原因（仅 is_partial=True 时有效）
    web_search_results: List[Dict[str, Any]] = field(default_factory=list)  # 联网搜索结果
    
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
    stop_requested = pyqtSignal()                # 停止请求已发出
    stop_completed = pyqtSignal(dict)            # 停止完成 (result)
    
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
        
        # 停止控制相关
        self._stop_controller = None
        self._current_task_id: Optional[str] = None  # 当前 LLM 任务 ID
        
        # 延迟获取的服务
        self._context_manager = None
        self._event_bus = None
        self._logger = None
        self._markdown_converter = None
        self._config_manager = None
        self._session_state_manager = None
        
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
        """当前会话名称（从 SessionStateManager 获取）"""
        if self.session_state_manager:
            return self.session_state_manager.get_current_session_name()
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
    
    @property
    def session_state_manager(self):
        """延迟获取会话状态管理器"""
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER
                self._session_state_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            except Exception:
                pass
        return self._session_state_manager
    
    @property
    def stop_controller(self):
        """延迟获取停止控制器"""
        if self._stop_controller is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_STOP_CONTROLLER
                self._stop_controller = ServiceLocator.get_optional(SVC_STOP_CONTROLLER)
            except Exception:
                pass
        return self._stop_controller
    
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
                EVENT_SESSION_CHANGED,
                EVENT_STOP_REQUESTED,
                EVENT_STOP_COMPLETED,
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
            self.event_bus.subscribe(EVENT_SESSION_CHANGED, self._on_session_changed)
            self.event_bus.subscribe(EVENT_STOP_REQUESTED, self._on_stop_requested_event)
            self.event_bus.subscribe(EVENT_STOP_COMPLETED, self._on_stop_completed_event)
            
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
                EVENT_SESSION_CHANGED,
                EVENT_STOP_REQUESTED,
                EVENT_STOP_COMPLETED,
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
            self.event_bus.unsubscribe(EVENT_SESSION_CHANGED, self._on_session_changed)
            self.event_bus.unsubscribe(EVENT_STOP_REQUESTED, self._on_stop_requested_event)
            self.event_bus.unsubscribe(EVENT_STOP_COMPLETED, self._on_stop_completed_event)
            
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
            # 获取消息（直接使用 LangChain 消息类型）
            if state is not None:
                messages = state.get("messages", [])
            else:
                # 使用有状态版本的方法
                messages = self.context_manager.get_display_messages()
            
            # 转换为显示格式
            from domain.llm.message_helpers import is_system_message
            self._messages = [
                self.format_message(msg) for msg in messages
                if not is_system_message(msg)  # 不显示系统消息
            ]
            
            # 更新使用率
            self._update_usage_ratio()
            
            # 发出信号
            self.messages_changed.emit()
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"加载消息失败: {e}")
    
    def format_message(self, lc_msg) -> DisplayMessage:
        """
        将 LangChain 消息转换为 DisplayMessage
        
        Args:
            lc_msg: LangChain 消息对象
            
        Returns:
            DisplayMessage: UI 友好的消息格式
        """
        from domain.llm.message_helpers import (
            get_role,
            get_reasoning_content,
            get_operations,
            get_attachments,
            get_timestamp,
            is_partial_response,
            get_stop_reason,
            get_web_search_results,
        )
        
        # 获取消息内容
        content = lc_msg.content if isinstance(lc_msg.content, str) else ""
        
        # 生成唯一 ID
        kwargs = getattr(lc_msg, "additional_kwargs", {}) or {}
        metadata = kwargs.get("metadata", {})
        msg_id = metadata.get("id", str(uuid.uuid4()))
        
        # 转换 Markdown 为 HTML
        content_html = self._markdown_to_html(content)
        reasoning_html = ""
        reasoning = get_reasoning_content(lc_msg)
        if reasoning:
            reasoning_html = self._markdown_to_html(reasoning)
        
        # 格式化时间戳
        timestamp_display = self._format_timestamp(get_timestamp(lc_msg))
        
        # 获取附件
        attachments = get_attachments(lc_msg)
        
        # 获取联网搜索结果
        web_search_results = get_web_search_results(lc_msg)
        
        # 获取部分响应标记（3.0.10 数据稳定性）
        is_partial = is_partial_response(lc_msg)
        stop_reason = get_stop_reason(lc_msg)
        
        return DisplayMessage(
            id=msg_id,
            role=get_role(lc_msg),
            content_html=content_html,
            content=content,  # 保留原始内容用于 LaTeX 检测
            reasoning_html=reasoning_html,
            operations=list(get_operations(lc_msg)),
            attachments=attachments,
            timestamp_display=timestamp_display,
            is_streaming=False,
            is_partial=is_partial,
            stop_reason=stop_reason,
            web_search_results=web_search_results,
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
        """
        开始流式输出
        
        设置加载状态，清空流式缓冲区，生成任务 ID 并注册到 StopController。
        任务 ID 会保存到 _current_task_id，供 _trigger_llm_call() 使用。
        """
        self._is_loading = True
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        
        # 生成任务 ID 并保存
        self._current_task_id = f"llm_{uuid.uuid4().hex[:8]}"
        
        # 注册任务到 StopController，允许用户停止
        if self.stop_controller:
            self.stop_controller.register_task(self._current_task_id)
        
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
        发送消息并触发 LLM 调用
        
        消息会被添加到当前打开的会话（由 SessionStateManager 管理），
        而不是关闭软件时持久化的会话。
        
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
        
        # 委托给 ContextManager 发送（使用有状态便捷方法）
        # 注意：不直接操作 _messages 列表，通过 load_messages() 统一同步
        if self.context_manager:
            try:
                # 附件已经是字典格式，直接传递
                att_list = attachments if attachments else None
                
                # 使用有状态便捷方法添加用户消息
                self.context_manager.add_user_message(text, att_list)
                
                # 标记会话为脏，确保消息会被保存
                if self.session_state_manager:
                    self.session_state_manager.mark_dirty()
                
                # 从 ContextManager 重新加载消息以保持同步
                self.load_messages()
                
                # 开始加载状态（流式输出）
                self.start_streaming()
                
                # 触发 LLM 调用
                self._trigger_llm_call()
                
                return True
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"发送消息失败: {e}")
                self._is_loading = False
                self.can_send_changed.emit(True)
                return False
        
        return False
    
    def _trigger_llm_call(self) -> None:
        """
        触发 LLM 调用
        
        获取消息历史，调用 LLMExecutor 进行流式生成。
        LLMExecutor.generate() 使用 @asyncSlot() 装饰器，会自动在 qasync 事件循环中执行。
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_EXECUTOR, SVC_CONFIG_MANAGER
            
            llm_executor = ServiceLocator.get_optional(SVC_LLM_EXECUTOR)
            config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            
            if not llm_executor:
                if self.logger:
                    self.logger.error("LLMExecutor not available")
                self._handle_llm_error("LLM 服务未初始化，请先配置 API Key")
                return
            
            if not config_manager:
                if self.logger:
                    self.logger.error("ConfigManager not available")
                self._handle_llm_error("配置服务不可用")
                return
            
            # 获取模型配置
            model = config_manager.get("llm_model", "glm-4.7")
            enable_thinking = config_manager.get("enable_thinking", True)
            
            # 获取消息历史（用于 LLM 调用）
            messages = self.context_manager.get_messages_for_llm()
            
            # 注入系统提示词
            messages = self._inject_system_prompt(messages)
            
            # 使用 start_streaming() 中生成的任务 ID
            task_id = self._current_task_id or f"llm_{uuid.uuid4().hex[:8]}"
            
            # 连接 LLMExecutor 信号
            llm_executor.stream_chunk.connect(self._on_llm_stream_chunk)
            llm_executor.generation_complete.connect(self._on_llm_generation_complete)
            llm_executor.generation_error.connect(self._on_llm_generation_error)
            
            # 直接调用 generate() 方法
            # @asyncSlot() 装饰器会自动将协程调度到 qasync 事件循环中执行
            llm_executor.generate(
                task_id=task_id,
                messages=messages,
                model=model,
                streaming=True,
                thinking=enable_thinking,
            )
            
            if self.logger:
                self.logger.info(f"LLM call triggered: task_id={task_id}, model={model}")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to trigger LLM call: {e}")
            self._handle_llm_error(f"调用 LLM 失败: {e}")
    
    def _inject_system_prompt(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        注入系统提示词
        
        Args:
            messages: 原始消息列表
            
        Returns:
            注入系统提示词后的消息列表
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_SYSTEM_PROMPT_INJECTOR
            
            injector = ServiceLocator.get_optional(SVC_SYSTEM_PROMPT_INJECTOR)
            if injector:
                system_prompt = injector.get_system_prompt()
                if system_prompt:
                    # 检查是否已有系统消息
                    if messages and messages[0].get("role") == "system":
                        # 替换现有系统消息
                        messages[0]["content"] = system_prompt
                    else:
                        # 插入系统消息到开头
                        messages.insert(0, {
                            "role": "system",
                            "content": system_prompt
                        })
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to inject system prompt: {e}")
        
        return messages
    
    def _on_llm_stream_chunk(
        self,
        task_id: str,
        chunk_type: str,
        chunk_data: Dict[str, Any]
    ) -> None:
        """
        处理 LLM 流式输出块
        
        Args:
            task_id: 任务 ID
            chunk_type: 块类型 ("reasoning" | "content")
            chunk_data: 块数据
        """
        text = chunk_data.get("text", "")
        if text:
            self.append_stream_chunk(text, chunk_type)
    
    def _on_llm_generation_complete(
        self,
        task_id: str,
        result: Dict[str, Any]
    ) -> None:
        """
        处理 LLM 生成完成
        
        Args:
            task_id: 任务 ID
            result: 生成结果
        """
        # 断开信号连接（避免重复处理）
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_EXECUTOR
            
            llm_executor = ServiceLocator.get_optional(SVC_LLM_EXECUTOR)
            if llm_executor:
                llm_executor.stream_chunk.disconnect(self._on_llm_stream_chunk)
                llm_executor.generation_complete.disconnect(self._on_llm_generation_complete)
                llm_executor.generation_error.disconnect(self._on_llm_generation_error)
        except Exception:
            pass
        
        # 提取结果
        content = result.get("content", "")
        reasoning_content = result.get("reasoning_content", "")
        usage = result.get("usage")
        is_partial = result.get("is_partial", False)
        
        # 添加助手消息到 ContextManager
        if self.context_manager and content:
            self.context_manager.add_assistant_message(
                content=content,
                reasoning_content=reasoning_content,
                usage=usage,
            )
        
        # 更新状态
        self._is_loading = False
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self._current_task_id = None  # 清除任务 ID
        
        # 重置 StopController 状态为 IDLE
        if self.stop_controller:
            self.stop_controller.reset()
        
        # 从 ContextManager 重新加载消息
        self.load_messages()
        
        # 自动保存会话
        self._auto_save_session()
        
        # 发出信号
        self.stream_finished.emit()
        self.can_send_changed.emit(True)
        
        if self.logger:
            self.logger.info(
                f"LLM generation complete: task_id={task_id}, "
                f"content_len={len(content)}, is_partial={is_partial}"
            )
    
    def _on_llm_generation_error(self, task_id: str, error_msg: str) -> None:
        """
        处理 LLM 生成错误
        
        Args:
            task_id: 任务 ID
            error_msg: 错误消息
        """
        # 断开信号连接
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_EXECUTOR
            
            llm_executor = ServiceLocator.get_optional(SVC_LLM_EXECUTOR)
            if llm_executor:
                llm_executor.stream_chunk.disconnect(self._on_llm_stream_chunk)
                llm_executor.generation_complete.disconnect(self._on_llm_generation_complete)
                llm_executor.generation_error.disconnect(self._on_llm_generation_error)
        except Exception:
            pass
        
        self._handle_llm_error(error_msg)
    
    def _handle_llm_error(self, error_msg: str) -> None:
        """
        处理 LLM 错误
        
        Args:
            error_msg: 错误消息
        """
        if self.logger:
            self.logger.error(f"LLM error: {error_msg}")
        
        # 更新状态
        self._is_loading = False
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self._current_task_id = None  # 清除任务 ID
        
        # 重置 StopController
        if self.stop_controller:
            self.stop_controller.reset()
        
        # 发出信号
        self.stream_finished.emit()
        self.can_send_changed.emit(True)
        
        # 发布错误事件
        if self.event_bus:
            try:
                from shared.event_types import EVENT_LLM_ERROR
                self.event_bus.publish(EVENT_LLM_ERROR, {
                    "error": error_msg,
                    "source": "conversation_view_model",
                })
            except ImportError:
                pass
    
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
            Dict: 包含 ratio, current_tokens, max_tokens, state 等信息
        """
        current_tokens = 0
        max_tokens = 0
        
        if self.context_manager:
            try:
                state = self.context_manager._get_internal_state()
                usage = self.context_manager.calculate_usage(state)
                current_tokens = usage.get("total_tokens", 0)
                # max_tokens 是可用于输入的空间（context_limit - output_reserve）
                context_limit = usage.get("context_limit", 0)
                output_reserve = usage.get("output_reserve", 0)
                max_tokens = context_limit - output_reserve
            except Exception:
                pass
        
        return {
            "ratio": self._usage_ratio,
            "current_tokens": current_tokens,
            "max_tokens": max_tokens,
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
        - 基础格式："Chat YYYY-MM-DD HH:mm"（精确到分钟）
        - 若已有同名会话，追加序号："Chat YYYY-MM-DD HH:mm (2)"
        - 序号从 2 开始递增，直到找到唯一名称
        - 精确到分钟可避免同一天内多次新建对话时名称冲突
        
        Returns:
            str: 唯一的会话名称
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        base_name = f"Chat {now}"
        
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
        
        从 SessionStateManager 收集所有已使用的会话名称。
        
        Returns:
            set: 已存在的会话名称集合
        """
        existing_names = set()
        
        # 从配置中获取当前会话名称
        if self.config_manager:
            current_name = self.config_manager.get("current_conversation_name")
            if current_name:
                existing_names.add(current_name)
        
        # 从 SessionStateManager 获取所有会话名称
        if self.session_state_manager:
            try:
                # 获取项目路径
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                
                session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
                if session_state:
                    project_path = session_state.project_root
                    if project_path:
                        sessions = self.session_state_manager.get_all_sessions(project_path)
                        for session in sessions:
                            if session.name:
                                existing_names.add(session.name)
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"获取会话名称失败: {e}")
        
        return existing_names
    
    def set_session_name(self, name: str) -> None:
        """
        设置当前会话名称（内部使用，用于同步状态）
        
        Args:
            name: 会话名称
        """
        self._current_session_name = name
        self.session_name_updated.emit(name)
    
    def get_session_name(self) -> str:
        """
        获取当前会话名称（从 SessionStateManager 获取）
        
        Returns:
            str: 会话名称
        """
        if self.session_state_manager:
            return self.session_state_manager.get_current_session_name()
        return self._current_session_name
    
    def set_session_id(self, session_id: str) -> None:
        """
        设置当前会话 ID（保留用于兼容）
        
        Args:
            session_id: 会话 ID
        """
        self._current_session_id = session_id
    
    def reset_session(self) -> str:
        """
        重置会话（新开对话时调用）
        
        委托给 SessionStateManager.create_session()
        
        Returns:
            str: 新的会话 ID
        """
        if self.session_state_manager:
            try:
                # 获取项目路径
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                
                session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
                if session_state and session_state.project_root:
                    session_id = self.session_state_manager.create_session(
                        session_state.project_root
                    )
                    self._current_session_id = session_id
                    self._current_session_name = self.session_state_manager.get_current_session_name()
                    self.session_name_updated.emit(self._current_session_name)
                    return self._current_session_name
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to create new session: {e}")
        
        # 回退：生成唯一的会话名称
        self._current_session_name = self.generate_unique_session_name()
        self.session_name_updated.emit(self._current_session_name)
        return self._current_session_name
    
    def request_new_session(self) -> Tuple[bool, str]:
        """
        请求新开对话（委托给 SessionStateManager）
        
        Returns:
            (是否成功, 新会话名称或错误消息)
        """
        if self.session_state_manager:
            try:
                # 获取项目路径
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                
                session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
                if session_state and session_state.project_root:
                    session_id = self.session_state_manager.create_session(
                        session_state.project_root
                    )
                    session_name = self.session_state_manager.get_current_session_name()
                    return True, session_name
                return False, "No project path available"
            except Exception as e:
                return False, str(e)
        return False, "SessionStateManager not available"
    
    def request_save_session(self) -> Tuple[bool, str]:
        """
        请求保存当前会话（委托给 SessionStateManager）
        
        Returns:
            (是否成功, 消息)
        """
        if self.session_state_manager:
            try:
                # 获取项目路径和当前状态
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                
                session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
                if session_state and session_state.project_root:
                    # 获取当前 GraphState
                    if self.context_manager:
                        state = self.context_manager._get_internal_state()
                        success = self.session_state_manager.save_current_session(
                            state, session_state.project_root
                        )
                        if success:
                            return True, "Session saved successfully"
                        return False, "Failed to save session"
                    return False, "ContextManager not available"
                return False, "No project path available"
            except Exception as e:
                return False, str(e)
        return False, "SessionStateManager not available"
    
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
        将 Markdown 转换为 HTML（使用 MarkdownRenderer 支持 LaTeX）
        
        Args:
            text: Markdown 文本
            
        Returns:
            str: HTML 字符串
        """
        if not text:
            return ""
        
        # 优先使用 MarkdownRenderer（支持 LaTeX 公式保护）
        try:
            from infrastructure.utils.markdown_renderer import render_markdown
            return render_markdown(text)
        except ImportError:
            pass
        
        # 回退：使用普通 markdown 库
        converter = self._get_markdown_converter()
        if converter:
            try:
                converter.reset()
                return converter.convert(text)
            except Exception:
                pass
        
        # 最终回退：简单转义
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
        # 更新状态
        self._is_loading = False
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        
        # 重置 StopController 状态为 IDLE，允许新任务注册
        if self.stop_controller:
            self.stop_controller.reset()
        
        # 从 ContextManager 重新加载消息以保持同步
        # 注意：不直接操作 _messages 列表，避免消息重复
        self.load_messages()
        
        # 每轮对话完成后自动保存会话
        self._auto_save_session()
        
        # 发出信号
        self.stream_finished.emit()
        self.can_send_changed.emit(True)
    
    def _auto_save_session(self) -> None:
        """
        自动保存当前会话
        
        在每轮对话完成后调用，委托给 SessionStateManager。
        """
        if self.session_state_manager and self.context_manager:
            try:
                # 获取项目路径
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                
                session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
                if session_state and session_state.project_root:
                    # 获取当前 GraphState
                    state = self.context_manager._get_internal_state()
                    success = self.session_state_manager.save_current_session(
                        state, session_state.project_root
                    )
                    if success:
                        if self.logger:
                            self.logger.debug(f"Auto-saved session: {self.current_session_name}")
                    else:
                        if self.logger:
                            self.logger.warning("Auto-save failed")
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Auto-save error: {e}")
    
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
    
    def _on_session_changed(self, event_data: Dict[str, Any]) -> None:
        """
        处理会话变更事件（由 SessionStateManager 发布）
        
        响应会话切换、新建、恢复等操作，刷新 UI 显示。
        
        注意：SessionStateManager 在发布此事件前已同步状态到 ContextManager，
        因此 load_messages() 能正确获取新会话的消息。
        """
        data = event_data.get("data", {})
        session_name = data.get("session_name", "")
        action = data.get("action", "")
        session_id = data.get("session_id", "")
        
        if self.logger:
            self.logger.debug(f"Session changed: action={action}, id={session_id}, name={session_name}")
        
        # 更新内部状态
        self._current_session_id = session_id
        self._current_session_name = session_name
        
        # 发出会话名称更新信号
        self.session_name_updated.emit(session_name)
        
        # 重新加载消息（ContextManager 状态已由 SessionStateManager 同步）
        self.load_messages()
        
        # 更新使用率
        self._update_usage_ratio()
    
    # ============================================================
    # 停止控制
    # ============================================================
    
    def request_stop(self) -> bool:
        """
        请求停止当前生成
        
        通过 StopController 发起停止请求。
        
        Returns:
            bool: 是否成功发起停止请求
        """
        if not self._is_loading:
            if self.logger:
                self.logger.debug("No active generation to stop")
            return False
        
        if self.stop_controller:
            try:
                from shared.stop_controller import StopReason
                success = self.stop_controller.request_stop(StopReason.USER_REQUESTED)
                if success:
                    if self.logger:
                        self.logger.info("Stop requested by user")
                    self.stop_requested.emit()
                return success
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to request stop: {e}")
                return False
        
        if self.logger:
            self.logger.warning("StopController not available")
        return False
    
    def _on_stop_requested_event(self, event_data: Dict[str, Any]) -> None:
        """
        处理停止请求事件（由 StopController 发布）
        
        更新 UI 状态，显示"正在停止"。
        """
        data = event_data.get("data", event_data)
        task_id = data.get("task_id", "")
        reason = data.get("reason", "")
        
        if self.logger:
            self.logger.debug(f"Stop requested event: task_id={task_id}, reason={reason}")
        
        # 发出信号通知 UI 更新按钮状态
        self.stop_requested.emit()
    
    def _on_stop_completed_event(self, event_data: Dict[str, Any]) -> None:
        """
        处理停止完成事件（由 StopController 发布）
        
        处理部分响应，更新消息列表，恢复 UI 状态。
        
        关键步骤：
        1. 处理部分响应（保存或丢弃）
        2. 清空流式状态
        3. 调用 StopController.reset() 重置状态为 IDLE
        4. 发出信号通知 UI 恢复
        """
        data = event_data.get("data", event_data)
        task_id = data.get("task_id", "")
        reason = data.get("reason", "")
        is_partial = data.get("is_partial", True)
        partial_content = data.get("partial_content", "")
        
        if self.logger:
            self.logger.info(
                f"Stop completed: task_id={task_id}, reason={reason}, "
                f"is_partial={is_partial}, content_len={len(partial_content)}"
            )
        
        # 处理部分响应
        if is_partial and self._current_stream_content:
            # 使用已累积的流式内容
            partial_content = self._current_stream_content
        
        # 根据内容长度决定是否保存
        MIN_PARTIAL_LENGTH = 50
        saved = False
        if partial_content and len(partial_content) >= MIN_PARTIAL_LENGTH:
            # 保存部分响应，标记为已中断
            self._save_partial_response(partial_content, reason)
            saved = True
        else:
            if self.logger:
                self.logger.debug(
                    f"Partial content too short ({len(partial_content)} chars), discarding"
                )
        
        # 清空流式状态
        self._current_stream_content = ""
        self._current_reasoning_content = ""
        self._is_loading = False
        self._current_task_id = None  # 清除任务 ID
        
        # 重置 StopController 状态为 IDLE，允许新任务注册
        if self.stop_controller:
            self.stop_controller.reset()
            if self.logger:
                self.logger.debug("StopController reset to IDLE")
        
        # 发出信号
        result = {
            "task_id": task_id,
            "reason": reason,
            "is_partial": is_partial,
            "saved": saved,
        }
        self.stop_completed.emit(result)
        
        # 发出可发送状态变化信号，恢复发送按钮
        self.can_send_changed.emit(True)
        
        # 发出流式输出完成信号
        self.stream_finished.emit()
    
    def _save_partial_response(self, content: str, reason: str) -> None:
        """
        保存部分响应为消息
        
        Args:
            content: 部分响应内容
            reason: 停止原因
        """
        # 转换为 HTML（不再在内容中添加中断标记，由 MessageBubble 渲染）
        content_html = self._markdown_to_html(content)
        reasoning_html = ""
        if self._current_reasoning_content:
            reasoning_html = self._markdown_to_html(self._current_reasoning_content)
        
        # 创建消息（设置 is_partial 和 stop_reason 供 MessageBubble 渲染中断标记）
        msg = DisplayMessage(
            id=str(uuid.uuid4()),
            role=ROLE_ASSISTANT,
            content_html=content_html,
            content=content,
            reasoning_html=reasoning_html,
            timestamp_display=self._format_timestamp(datetime.now().isoformat()),
            is_streaming=False,
            is_partial=True,
            stop_reason=reason,
        )
        
        # 添加到消息列表
        self._messages.append(msg)
        
        # 同步到 ContextManager（标记为部分响应）
        if self.context_manager:
            try:
                self.context_manager.add_assistant_message(
                    content,
                    reasoning_content=self._current_reasoning_content,
                    is_partial=True,
                    stop_reason=reason,
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to save partial response to context: {e}")
        
        # 发出消息变更信号
        self.messages_changed.emit()
        
        if self.logger:
            self.logger.info(f"Saved partial response: {len(content)} chars")
    
    def _get_stop_reason_text(self, reason: str) -> str:
        """
        获取停止原因的显示文本
        
        Args:
            reason: 停止原因代码
            
        Returns:
            str: 显示文本
        """
        reason_texts = {
            "user_requested": "用户停止",
            "timeout": "超时",
            "error": "错误",
            "session_switch": "会话切换",
            "app_shutdown": "应用关闭",
        }
        return reason_texts.get(reason, "已停止")


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
