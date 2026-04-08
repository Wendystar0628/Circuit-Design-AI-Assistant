# Conversation ViewModel - UI Data Layer
"""
对话面板 ViewModel - UI 与数据层的中间层

职责：
- 作为 UI 与 ContextManager 之间的中间层
- 将内部消息格式转换为 UI 友好的 DisplayMessage 格式
- 管理 Agent step 运行时状态
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
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from domain.llm.llm_message_builder import LLMMessageBuilder
from domain.llm.message_types import Attachment

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
class AgentStepToolCall:
    """单个 Agent step 内的工具调用记录。"""
    tool_call_id: str
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    result_content: str = ""
    is_error: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentStep:
    """Agent 单次 react step 的可视化状态。"""
    step_index: int
    step_id: str = ""
    content: str = ""
    reasoning_content: str = ""
    tool_calls: List[AgentStepToolCall] = field(default_factory=list)
    web_search_query: str = ""
    web_search_results: List[Dict[str, Any]] = field(default_factory=list)
    web_search_message: str = ""
    web_search_state: str = "idle"
    is_complete: bool = False
    is_partial: bool = False
    stop_reason: str = ""


@dataclass
class DisplayMessage:
    """
    UI 友好的消息格式
    """
    id: str                                      # 消息唯一标识
    role: str                                    # 角色（user/assistant/system/suggestion）
    content: str = ""
    attachments: List[Attachment] = field(default_factory=list)  # 附件列表
    agent_steps: List[AgentStep] = field(default_factory=list)  # Agent 逐步反应轨迹
    
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
    runtime_steps_changed = pyqtSignal()         # 运行时 step 列表变化
    runtime_steps_finished = pyqtSignal()        # 运行时 step 会话完成
    usage_changed = pyqtSignal(float)            # 上下文占用变化 (ratio)
    can_send_changed = pyqtSignal(bool)          # 可发送状态变化
    compress_suggested = pyqtSignal()            # 建议压缩上下文
    new_conversation_suggested = pyqtSignal()    # 建议开启新对话
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
        self._active_agent_steps: List[AgentStep] = []
        self._active_suggestion_message_id: Optional[str] = None
        
        # 停止控制相关
        self._stop_controller = None
        self._current_task_id: Optional[str] = None  # 当前 LLM 任务 ID
        
        # 延迟获取的服务
        self._context_manager = None
        self._event_bus = None
        self._logger = None
        self._session_state_manager = None
        self._context_compression_service = None
        self._llm_runtime_config_manager = None
        self._llm_message_builder = LLMMessageBuilder()
        
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
    def can_send(self) -> bool:
        """是否可以发送消息"""
        return self._can_send and not self._is_loading

    @property
    def active_agent_steps(self) -> List[AgentStep]:
        """当前运行中的 Agent step 列表。"""
        return self._active_agent_steps
    
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
    def context_compression_service(self):
        if self._context_compression_service is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_COMPRESSION_SERVICE
                self._context_compression_service = ServiceLocator.get_optional(
                    SVC_CONTEXT_COMPRESSION_SERVICE
                )
            except Exception:
                pass
        return self._context_compression_service

    @property
    def llm_runtime_config_manager(self):
        if self._llm_runtime_config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER

                self._llm_runtime_config_manager = ServiceLocator.get_optional(
                    SVC_LLM_RUNTIME_CONFIG_MANAGER
                )
            except Exception:
                pass
        return self._llm_runtime_config_manager
    
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
        if self.event_bus is not None:
            try:
                from shared.event_types import (
                    EVENT_ITERATION_AWAITING_CONFIRMATION,
                    EVENT_CONTEXT_COMPRESS_COMPLETE,
                    EVENT_SESSION_CHANGED,
                    EVENT_MODEL_CHANGED,
                )
                
                self.event_bus.subscribe(
                    EVENT_ITERATION_AWAITING_CONFIRMATION,
                    self._on_iteration_awaiting
                )
                self.event_bus.subscribe(
                    EVENT_CONTEXT_COMPRESS_COMPLETE,
                    self._on_compress_complete
                )
                self.event_bus.subscribe(EVENT_SESSION_CHANGED, self._on_session_changed)
                self.event_bus.subscribe(EVENT_MODEL_CHANGED, self._on_model_changed)
                
            except ImportError:
                if self.logger:
                    self.logger.warning("无法导入事件类型，事件订阅跳过")

        try:
            if self.stop_controller:
                self.stop_controller.stop_requested.connect(self._on_stop_requested_signal)
                self.stop_controller.stop_completed.connect(self._on_stop_completed_signal)
        except Exception:
            pass
    
    def _unsubscribe_events(self) -> None:
        """取消事件订阅"""
        if self.event_bus is not None:
            try:
                from shared.event_types import (
                    EVENT_ITERATION_AWAITING_CONFIRMATION,
                    EVENT_CONTEXT_COMPRESS_COMPLETE,
                    EVENT_SESSION_CHANGED,
                    EVENT_MODEL_CHANGED,
                )
                
                self.event_bus.unsubscribe(
                    EVENT_ITERATION_AWAITING_CONFIRMATION,
                    self._on_iteration_awaiting
                )
                self.event_bus.unsubscribe(
                    EVENT_CONTEXT_COMPRESS_COMPLETE,
                    self._on_compress_complete
                )
                self.event_bus.unsubscribe(EVENT_SESSION_CHANGED, self._on_session_changed)
                self.event_bus.unsubscribe(EVENT_MODEL_CHANGED, self._on_model_changed)
                
            except ImportError:
                pass

        try:
            if self.stop_controller:
                self.stop_controller.stop_requested.disconnect(self._on_stop_requested_signal)
                self.stop_controller.stop_completed.disconnect(self._on_stop_completed_signal)
        except Exception:
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
            get_attachments,
            get_agent_steps,
            get_reasoning_content,
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

        # 获取附件
        attachments = get_attachments(lc_msg)

        # 获取部分响应标记（3.0.10 数据稳定性）
        is_partial = is_partial_response(lc_msg)
        stop_reason = get_stop_reason(lc_msg)
        role = get_role(lc_msg)
        agent_steps = self._deserialize_agent_steps(get_agent_steps(lc_msg))
        web_search_results = get_web_search_results(lc_msg)

        if role == ROLE_ASSISTANT and not agent_steps:
            agent_steps = [
                AgentStep(
                    step_index=1,
                    step_id=f"{msg_id}_step_1",
                    content=content,
                    reasoning_content=get_reasoning_content(lc_msg),
                    web_search_results=web_search_results,
                    web_search_state="complete" if web_search_results else "idle",
                    is_complete=True,
                    is_partial=is_partial,
                    stop_reason=stop_reason,
                )
            ]
        
        return DisplayMessage(
            id=msg_id,
            role=role,
            content=content,
            attachments=attachments,
            agent_steps=agent_steps,
        )

    # ============================================================
    # Agent 运行时步骤
    # ============================================================

    def _deserialize_agent_steps(
        self,
        raw_steps: List[Dict[str, Any]],
    ) -> List[AgentStep]:
        steps: List[AgentStep] = []
        for index, raw_step in enumerate(raw_steps or [], start=1):
            if not isinstance(raw_step, dict):
                continue

            tool_calls: List[AgentStepToolCall] = []
            for raw_tool in raw_step.get("tool_calls", []) or []:
                if not isinstance(raw_tool, dict):
                    continue
                tool_calls.append(
                    AgentStepToolCall(
                        tool_call_id=str(raw_tool.get("tool_call_id", "") or ""),
                        tool_name=str(raw_tool.get("tool_name", "") or ""),
                        arguments=dict(raw_tool.get("arguments", {}) or {}),
                        result_content=str(raw_tool.get("result_content", "") or ""),
                        is_error=bool(raw_tool.get("is_error", False)),
                        details=dict(raw_tool.get("details", {}) or {}),
                    )
                )

            step_index = raw_step.get("step_index", index)
            try:
                step_index = max(1, int(step_index))
            except Exception:
                step_index = index

            steps.append(
                AgentStep(
                    step_index=step_index,
                    step_id=str(raw_step.get("step_id", "") or f"step_{step_index}"),
                    content=str(raw_step.get("content", "") or ""),
                    reasoning_content=str(raw_step.get("reasoning_content", "") or ""),
                    tool_calls=tool_calls,
                    web_search_query=str(raw_step.get("web_search_query", "") or ""),
                    web_search_results=list(raw_step.get("web_search_results", []) or []),
                    web_search_message=str(raw_step.get("web_search_message", "") or ""),
                    web_search_state=str(raw_step.get("web_search_state", "idle") or "idle"),
                    is_complete=bool(raw_step.get("is_complete", False)),
                    is_partial=bool(raw_step.get("is_partial", False)),
                    stop_reason=str(raw_step.get("stop_reason", "") or ""),
                )
            )
        return sorted(steps, key=lambda step: step.step_index)

    def _serialize_agent_steps(
        self,
        steps: Optional[List[AgentStep]] = None,
    ) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        for step in steps or self._active_agent_steps:
            serialized.append(
                {
                    "step_index": step.step_index,
                    "step_id": step.step_id,
                    "content": step.content,
                    "reasoning_content": step.reasoning_content,
                    "tool_calls": [
                        {
                            "tool_call_id": tool_call.tool_call_id,
                            "tool_name": tool_call.tool_name,
                            "arguments": dict(tool_call.arguments),
                            "result_content": tool_call.result_content,
                            "is_error": tool_call.is_error,
                            "details": dict(tool_call.details),
                        }
                        for tool_call in step.tool_calls
                    ],
                    "web_search_query": step.web_search_query,
                    "web_search_results": list(step.web_search_results),
                    "web_search_message": step.web_search_message,
                    "web_search_state": step.web_search_state,
                    "is_complete": step.is_complete,
                    "is_partial": step.is_partial,
                    "stop_reason": step.stop_reason,
                }
            )
        return serialized

    def _emit_runtime_steps_changed(self) -> None:
        self.runtime_steps_changed.emit()

    def _clear_active_agent_steps(self, emit_signal: bool = True) -> None:
        self._active_agent_steps = []
        if emit_signal:
            self._emit_runtime_steps_changed()

    def _ensure_agent_step(self, step_index: int) -> AgentStep:
        if step_index <= 0:
            step_index = len(self._active_agent_steps) + 1

        for step in self._active_agent_steps:
            if step.step_index == step_index:
                return step

        for step in self._active_agent_steps:
            step.is_complete = True

        step = AgentStep(
            step_index=step_index,
            step_id=f"{self._current_task_id or 'runtime'}_step_{step_index}",
        )
        self._active_agent_steps.append(step)
        self._active_agent_steps.sort(key=lambda item: item.step_index)
        return step

    def _find_tool_call(
        self,
        step: AgentStep,
        tool_call_id: str,
    ) -> Optional[AgentStepToolCall]:
        for tool_call in step.tool_calls:
            if tool_call.tool_call_id == tool_call_id:
                return tool_call
        return None

    def _mark_active_steps_complete(
        self,
        *,
        is_partial: bool = False,
        stop_reason: str = "",
    ) -> None:
        for step in self._active_agent_steps:
            step.is_complete = True

        if self._active_agent_steps and (is_partial or stop_reason):
            final_step = self._active_agent_steps[-1]
            final_step.is_partial = is_partial
            final_step.stop_reason = stop_reason

    def _start_agent_run(self) -> None:
        """开始一次新的 Agent 运行。"""
        self._is_loading = True
        self._clear_active_agent_steps(emit_signal=False)
        
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
            suggestions=suggestion_items,
            status_summary=status_summary,
            suggestion_state=SUGGESTION_STATE_ACTIVE,
        )
        
        # 标记之前的建议选项为过期
        self._expire_previous_suggestions()
        
        # 添加到消息列表
        self._messages.append(msg)
        self._active_suggestion_message_id = msg_id
        
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

    def select_suggestion(self, suggestion_id: str) -> str:
        """选择建议项并返回其 value 文本。"""
        if self._active_suggestion_message_id is None:
            return ""

        selected_value = ""
        for msg in self._messages:
            if msg.id != self._active_suggestion_message_id:
                continue
            for suggestion in msg.suggestions:
                if suggestion.id == suggestion_id:
                    selected_value = suggestion.value
                    break
            break

        self.mark_suggestion_selected(suggestion_id)
        return selected_value
    
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
        attachments: Optional[List[Attachment]] = None
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
        
        text_value = text.strip()
        if not text_value and not attachments:
            return False
        
        # 标记之前的建议选项为过期
        if self._active_suggestion_message_id:
            self.mark_suggestion_expired()
        
        # 委托给 ContextManager 发送（使用有状态便捷方法）
        # 注意：不直接操作 _messages 列表，通过 load_messages() 统一同步
        if self.context_manager:
            try:
                att_list = attachments if attachments else None
                
                # 使用有状态便捷方法添加用户消息
                self.context_manager.add_user_message(text_value, att_list)
                
                # 标记会话为脏，确保消息会被保存
                if self.session_state_manager:
                    self.session_state_manager.mark_dirty()
                
                # 从 ContextManager 重新加载消息以保持同步
                self.load_messages()
                
                # 开始新的 Agent 运行
                self._start_agent_run()
                
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
        触发 LLM 调用（默认 Agent 模式）
        
        获取消息历史，调用 LLMExecutor.execute_agent() 进入 Agent 循环。
        Agent 模式下 LLM 自行决定是否调用工具：
        - 若不需要工具，行为与普通对话完全一致
        - 若需要工具，自动执行 ReAct 循环
        """
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_EXECUTOR, SVC_LLM_RUNTIME_CONFIG_MANAGER
            
            llm_executor = ServiceLocator.get_optional(SVC_LLM_EXECUTOR)
            llm_runtime_config_manager = ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER)
            
            if not llm_executor:
                if self.logger:
                    self.logger.error("LLMExecutor not available")
                self._handle_llm_error("LLM 服务未初始化，请先配置 API Key")
                return
            
            if not llm_runtime_config_manager:
                if self.logger:
                    self.logger.error("LLMRuntimeConfigManager not available")
                self._handle_llm_error("模型配置服务不可用")
                return
            
            # 获取模型配置
            active_config = llm_runtime_config_manager.resolve_active_config()
            model = active_config.model
            enable_thinking = active_config.enable_thinking
            if not model:
                self._handle_llm_error("当前未配置对话模型")
                return
            
            # 获取消息历史（用于 LLM 调用）
            messages = self._llm_message_builder.build_messages(
                self.context_manager.get_working_messages()
            )
            
            # 使用当前 Agent 运行的任务 ID
            task_id = self._current_task_id or f"llm_{uuid.uuid4().hex[:8]}"
            self._current_task_id = task_id
            
            # 连接 LLMExecutor 信号
            llm_executor.agent_turn_started.connect(self._on_agent_turn_started)
            llm_executor.stream_chunk.connect(self._on_llm_stream_chunk)
            llm_executor.generation_complete.connect(self._on_llm_generation_complete)
            llm_executor.generation_error.connect(self._on_llm_generation_error)
            llm_executor.tool_execution_started.connect(self._on_tool_execution_started)
            llm_executor.tool_execution_finished.connect(self._on_tool_execution_finished)
            
            # 默认使用 Agent 模式
            # @asyncSlot() 装饰器会自动将协程调度到 qasync 事件循环中执行
            llm_executor.execute_agent(
                task_id=task_id,
                messages=messages,
                model=model,
                thinking=enable_thinking,
            )
            
            if self.logger:
                self.logger.info(
                    f"Agent call triggered: task_id={task_id}, model={model}")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to trigger LLM call: {e}")
            self._handle_llm_error(f"调用 LLM 失败: {e}")
    
    def _on_llm_stream_chunk(
        self,
        task_id: str,
        step_index: int,
        chunk_type: str,
        chunk_data: Dict[str, Any]
    ) -> None:
        """
        处理 LLM step 增量输出
        
        Args:
            task_id: 任务 ID
            chunk_type: 块类型 ("reasoning" | "content")
            chunk_data: 块数据
        """
        if task_id != self._current_task_id:
            return

        text = chunk_data.get("text", "")
        if text:
            step = self._ensure_agent_step(step_index)
            if chunk_type == "reasoning":
                step.reasoning_content += text
            else:
                step.content += text
            self._emit_runtime_steps_changed()

    def _on_agent_turn_started(self, task_id: str, step_index: int) -> None:
        if task_id != self._current_task_id:
            return
        self._ensure_agent_step(step_index)
        self._emit_runtime_steps_changed()

    def _disconnect_llm_executor_signals(self) -> None:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_EXECUTOR

            llm_executor = ServiceLocator.get_optional(SVC_LLM_EXECUTOR)
            if llm_executor:
                llm_executor.agent_turn_started.disconnect(self._on_agent_turn_started)
                llm_executor.stream_chunk.disconnect(self._on_llm_stream_chunk)
                llm_executor.generation_complete.disconnect(self._on_llm_generation_complete)
                llm_executor.generation_error.disconnect(self._on_llm_generation_error)
                llm_executor.tool_execution_started.disconnect(self._on_tool_execution_started)
                llm_executor.tool_execution_finished.disconnect(self._on_tool_execution_finished)
        except Exception:
            pass
    
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
        if task_id != self._current_task_id:
            return

        # 断开信号连接（避免重复处理）
        self._disconnect_llm_executor_signals()
        
        # 提取结果
        content = result.get("content", "")
        reasoning_content = result.get("reasoning_content", "")
        usage = result.get("usage")
        is_partial = result.get("is_partial", False)
        self._mark_active_steps_complete(is_partial=is_partial)
        self._emit_runtime_steps_changed()

        has_tool_activity = any(step.tool_calls for step in self._active_agent_steps)
        has_web_search_activity = any(
            step.web_search_query or step.web_search_results
            for step in self._active_agent_steps
        )
        agent_steps = self._serialize_agent_steps()

        if not reasoning_content and self._active_agent_steps:
            reasoning_content = self._active_agent_steps[-1].reasoning_content

        if not content and (has_tool_activity or has_web_search_activity):
            if has_web_search_activity:
                content = "本轮已完成工具执行，但模型未返回最终总结文本。请结合下方联网结果与工具记录继续查看。"
            else:
                content = "本轮工具调用已结束，但模型未返回最终文本答复。请参考下方工具执行记录。"

        # 添加助手消息到 ContextManager
        if self.context_manager and content:
            self.context_manager.add_assistant_message(
                content,
                reasoning_content=reasoning_content,
                usage=usage,
                agent_steps=agent_steps,
            )
        
        # 更新状态
        self._is_loading = False
        self._current_task_id = None  # 清除任务 ID
        
        # 重置 StopController 状态为 IDLE
        if self.stop_controller:
            self.stop_controller.reset()
        
        # 从 ContextManager 重新加载消息
        self.load_messages()
        
        # 自动保存会话
        self._auto_save_session()

        if self.context_compression_service:
            self.context_compression_service.schedule_auto_compress(
                source="llm_generation_complete"
            )
        
        # 发出信号
        self.runtime_steps_finished.emit()
        self._clear_active_agent_steps(emit_signal=False)
        self.can_send_changed.emit(True)
        
        if self.logger:
            self.logger.info(
                f"LLM generation complete: task_id={task_id}, "
                f"content_len={len(content)}, is_partial={is_partial}")
    
    def _on_llm_generation_error(self, task_id: str, error_msg: str) -> None:
        """
        处理 LLM 生成错误
        
        Args:
            task_id: 任务 ID
            error_msg: 错误消息
        """
        if task_id != self._current_task_id:
            return

        # 断开信号连接
        self._disconnect_llm_executor_signals()
        
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
        self._current_task_id = None  # 清除任务 ID
        self._mark_active_steps_complete(is_partial=bool(self._active_agent_steps), stop_reason="error")
        if self._active_agent_steps:
            self._emit_runtime_steps_changed()
        
        # 重置 StopController
        if self.stop_controller:
            self.stop_controller.reset()
        
        # 发出信号
        self.runtime_steps_finished.emit()
        self._clear_active_agent_steps(emit_signal=False)
        self.can_send_changed.emit(True)
    
    # ============================================================
    # Agent 工具事件处理
    # ============================================================

    def _on_tool_execution_started(
        self,
        task_id: str,
        step_index: int,
        tool_call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> None:
        """
        处理执行器发出的工具开始执行信号
        """
        if task_id != self._current_task_id:
            return

        if not tool_call_id or not tool_name:
            return

        step = self._ensure_agent_step(step_index)
        if tool_name == "web_search":
            step.web_search_query = str(arguments.get("query", "") or "").strip()
            step.web_search_state = "running"
        else:
            tool_call = self._find_tool_call(step, tool_call_id)
            if tool_call is None:
                step.tool_calls.append(
                    AgentStepToolCall(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        arguments=dict(arguments or {}),
                    )
                )
        self._emit_runtime_steps_changed()

    def _on_tool_execution_finished(
        self,
        task_id: str,
        step_index: int,
        tool_call_id: str,
        tool_name: str,
        result_content: str,
        is_error: bool,
        details: Dict[str, Any],
    ) -> None:
        """
        处理执行器发出的工具执行结束信号
        """
        if task_id != self._current_task_id:
            return

        if not tool_call_id:
            return

        step = self._ensure_agent_step(step_index)
        if tool_name == "web_search":
            results = details.get("results") if isinstance(details, dict) else []
            if not isinstance(results, list):
                results = []
            step.web_search_results = [item for item in results if isinstance(item, dict)]
            step.web_search_message = result_content
            step.web_search_state = "error" if is_error else "complete"
        else:
            tool_call = self._find_tool_call(step, tool_call_id)
            if tool_call is None:
                tool_call = AgentStepToolCall(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                )
                step.tool_calls.append(tool_call)
            tool_call.tool_name = tool_name or tool_call.tool_name
            tool_call.is_error = is_error
            tool_call.result_content = result_content
            tool_call.details = dict(details or {})
        self._emit_runtime_steps_changed()
    
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
        input_limit = 0
        output_reserve = 0
        display_ratio = 0.0
        
        usage = self._calculate_usage_snapshot()
        if usage:
            current_tokens = usage.get("total_tokens", 0)
            max_tokens = usage.get("context_limit", 0)
            input_limit = usage.get("input_limit", 0)
            output_reserve = usage.get("output_reserve", 0)
            display_ratio = usage.get("usage_ratio", 0.0)
            self._usage_ratio = display_ratio
        
        return {
            "ratio": max(0.0, min(1.0, display_ratio)),
            "current_tokens": current_tokens,
            "max_tokens": max_tokens,
            "input_limit": input_limit,
            "output_reserve": output_reserve,
            "state": self.compress_button_state,
            "message_count": len(self._messages),
        }
    
    def clear(self) -> None:
        """清空显示数据"""
        self._messages.clear()
        self._clear_active_agent_steps(emit_signal=False)
        self._is_loading = False
        self._current_task_id = None
        self._active_suggestion_message_id = None
        self.messages_changed.emit()
    
    # ============================================================
    # 会话名称管理
    # ============================================================
    
    def request_new_session(self) -> Tuple[bool, str]:
        """
        请求新开对话（委托给 SessionStateManager）
        
        Returns:
            (是否成功, 新会话名称或错误消息)
        """
        if self.session_state_manager:
            try:
                self.session_state_manager.create_session()
                session_name = self.session_state_manager.get_current_session_name()
                return True, session_name
            except Exception as e:
                return False, str(e)
        return False, "SessionStateManager not available"
    
    def _update_usage_ratio(self) -> None:
        """更新上下文占用比例"""
        usage = self._calculate_usage_snapshot()
        self._usage_ratio = usage.get("usage_ratio", 0.0) if usage else 0.0
        self.usage_changed.emit(self._usage_ratio)

    def _resolve_usage_target(self) -> Tuple[str, Optional[str]]:
        model = "default"
        provider: Optional[str] = None

        try:
            runtime_manager = self.llm_runtime_config_manager
            if runtime_manager:
                active_config = runtime_manager.resolve_active_config()
                if active_config.model:
                    model = active_config.model
                if active_config.provider:
                    provider = active_config.provider
        except Exception:
            pass

        return model, provider

    def _calculate_usage_snapshot(self) -> Dict[str, Any]:
        if self.context_manager is None:
            return {}

        try:
            state = self.context_manager.get_current_state()
            model, provider = self._resolve_usage_target()
            return self.context_manager.calculate_usage(state, model=model, provider=provider)
        except Exception:
            return {}
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _auto_save_session(self) -> None:
        """
        自动保存当前会话
        
        在每轮对话完成后调用，委托给 SessionStateManager。
        """
        if self.session_state_manager and self.context_manager:
            try:
                success = self.session_state_manager.save_current_session()
                if success:
                    if self.logger:
                        session_name = self.session_state_manager.get_current_session_name()
                        self.logger.debug(f"Auto-saved session: {session_name}")
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
    
    def _on_compress_complete(self, event_data: Dict[str, Any]) -> None:
        """处理压缩完成事件"""
        data = event_data.get("data", {})
        status = data.get("status", "")
        
        if status in {"completed", "suggest_new_conversation"}:
            # 重新加载消息
            self.load_messages()
        if status == "suggest_new_conversation":
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
        
        # 重新加载消息（ContextManager 状态已由 SessionStateManager 同步）
        self.load_messages()
        
        # 更新使用率
        self._update_usage_ratio()

    def _on_model_changed(self, event_data: Dict[str, Any]) -> None:
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
                return success
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to request stop: {e}")
                return False
        
        if self.logger:
            self.logger.warning("StopController not available")
        return False

    def _on_stop_requested_signal(self, task_id: str, reason: str) -> None:
        """
        处理 StopController 的停止请求信号。
        """
        if task_id and task_id != self._current_task_id:
            return

        if self.logger:
            self.logger.debug(f"Stop requested: task_id={task_id}, reason={reason}")

        self.stop_requested.emit()

    def _on_stop_completed_signal(self, task_id: str, result_data: Dict[str, Any]) -> None:
        """
        处理 StopController 的停止完成信号
        
        处理部分响应，更新消息列表，恢复 UI 状态。
        
        关键步骤：
        1. 处理部分响应（保存或丢弃）
        2. 清空运行时 step 状态
        3. 发出信号通知 UI 恢复
        """
        reason = result_data.get("reason", "")
        is_partial = result_data.get("is_partial", True)
        partial_content = result_data.get("partial_content", "")

        if task_id and task_id != self._current_task_id:
            return
        
        if self.logger:
            self.logger.info(
                f"Stop completed: task_id={task_id}, reason={reason}, "
                f"is_partial={is_partial}, content_len={len(partial_content)}"
            )
 
        self._disconnect_llm_executor_signals()
        
        if is_partial and self._active_agent_steps:
            self._mark_active_steps_complete(is_partial=True, stop_reason=reason)
            self._emit_runtime_steps_changed()
            final_step = self._active_agent_steps[-1]
            if final_step.content:
                partial_content = final_step.content
 
        saved = False
        if partial_content or self._active_agent_steps:
            self._save_partial_response(partial_content, reason)
            self._auto_save_session()
            saved = True
        
        # 清空运行时 step 状态
        self._is_loading = False
        self._current_task_id = None  # 清除任务 ID
        
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
        
        # 发出运行时步骤完成信号
        self.runtime_steps_finished.emit()
        self._clear_active_agent_steps(emit_signal=False)
    
    def _save_partial_response(self, content: str, reason: str) -> None:
        """
        保存部分响应为消息
        
        Args:
            content: 部分响应内容
            reason: 停止原因
        """
        if not content and self._active_agent_steps:
            last_step = self._active_agent_steps[-1]
            if last_step.tool_calls or last_step.web_search_query:
                content = "本轮已中断，已保留当前步骤轨迹。请参考下方步骤中的搜索与工具记录继续处理。"

        serialized_steps = self._serialize_agent_steps()
        
        # 创建消息（设置 is_partial 和 stop_reason 供消息渲染层展示中断标记）
        msg = DisplayMessage(
            id=str(uuid.uuid4()),
            role=ROLE_ASSISTANT,
            content=content,
            agent_steps=self._deserialize_agent_steps(serialized_steps),
        )
        
        # 添加到消息列表
        self._messages.append(msg)
        
        # 同步到 ContextManager（标记为部分响应）
        if self.context_manager:
            try:
                self.context_manager.add_assistant_message(
                    content,
                    reasoning_content=latest_reasoning,
                    is_partial=True,
                    stop_reason=reason,
                    agent_steps=serialized_steps,
                )
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Failed to save partial response to context: {e}")
        
        # 发出消息变更信号
        self.messages_changed.emit()
        
        if self.logger:
            self.logger.info(f"Saved partial response: {len(content)} chars")


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
    "AgentStepToolCall",
    "AgentStep",
    "DisplayMessage",
    # 类
    "ConversationViewModel",
]
