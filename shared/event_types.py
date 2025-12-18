# Event Type Constants
"""
事件类型常量定义

职责：
- 集中定义所有事件类型常量
- 避免字符串硬编码
- 作为 EventBus 发布和订阅事件的键

设计原则：
- 纯常量定义，不依赖任何其他模块
- 所有事件名使用 EVENT_ 前缀
- 按功能模块分组组织
- 命名规范：EVENT_{模块}_{动作}，全大写下划线分隔

使用示例：
    from shared.event_types import EVENT_INIT_COMPLETE
    event_bus.subscribe(EVENT_INIT_COMPLETE, on_init_complete)
    event_bus.publish(EVENT_INIT_COMPLETE, {"timestamp": time.time()})
"""

# ============================================================
# 初始化事件
# ============================================================

# 启动阶段完成通知
EVENT_INIT_PHASE_COMPLETE = "init_phase_complete"

# 所有初始化完成
EVENT_INIT_COMPLETE = "init_complete"

# ============================================================
# UI 交互事件
# ============================================================

# 用户选择文件
EVENT_UI_FILE_SELECTED = "ui_file_selected"

# 用户发送消息
EVENT_UI_SEND_MESSAGE = "ui_send_message"

# 用户请求仿真
EVENT_UI_REQUEST_SIMULATION = "ui_request_simulation"

# ============================================================
# 状态变更事件
# ============================================================

# 项目打开
# 携带数据：
#   - path: str - 项目路径
#   - name: str - 项目名称
#   - is_existing: bool - 是否为已有项目（存在 checkpoints.sqlite3）
#   - has_history: bool - 是否有历史对话和优化记录
#   - status: str - 项目状态（ready/degraded）
#   - degraded: bool - 是否为降级模式
EVENT_STATE_PROJECT_OPENED = "state_project_opened"

# 项目关闭
# 携带数据：
#   - path: str - 关闭的项目路径
EVENT_STATE_PROJECT_CLOSED = "state_project_closed"

# 配置变更
EVENT_STATE_CONFIG_CHANGED = "state_config_changed"

# 迭代状态更新
EVENT_STATE_ITERATION_UPDATED = "state_iteration_updated"


# ============================================================
# Worker 事件
# ============================================================

# Worker 启动
EVENT_WORKER_STARTED = "worker_started"

# Worker 进度更新
EVENT_WORKER_PROGRESS = "worker_progress"

# Worker 完成
EVENT_WORKER_COMPLETE = "worker_complete"

# Worker 错误
EVENT_WORKER_ERROR = "worker_error"

# ============================================================
# LLM 事件
# ============================================================

# LLM 流式输出块
EVENT_LLM_CHUNK = "llm_chunk"

# LLM 完成
EVENT_LLM_COMPLETE = "llm_complete"

# LLM 工具调用
EVENT_LLM_TOOL_CALL = "llm_tool_call"

# ============================================================
# 联网搜索事件
# ============================================================

# 联网搜索开始
# 携带数据：
#   - query: str - 搜索查询
#   - search_type: str - 搜索类型（"provider" | "general"）
#   - provider: str - 搜索提供商（"zhipu" | "google" | "bing"）
EVENT_WEB_SEARCH_STARTED = "web_search_started"

# 联网搜索完成
# 携带数据：
#   - query: str - 搜索查询
#   - results: list - 搜索结果列表
#   - result_count: int - 结果数量
#   - search_type: str - 搜索类型
#   - provider: str - 搜索提供商
EVENT_WEB_SEARCH_COMPLETE = "web_search_complete"

# 联网搜索错误
# 携带数据：
#   - query: str - 搜索查询
#   - error: str - 错误信息
#   - provider: str - 搜索提供商
EVENT_WEB_SEARCH_ERROR = "web_search_error"

# ============================================================
# 仿真事件
# ============================================================

# 仿真开始
EVENT_SIM_STARTED = "sim_started"

# 仿真完成
EVENT_SIM_COMPLETE = "sim_complete"

# 仿真错误
EVENT_SIM_ERROR = "sim_error"

# 主电路变更
EVENT_MAIN_CIRCUIT_CHANGED = "main_circuit_changed"

# 电路分析完成
EVENT_CIRCUIT_ANALYSIS_COMPLETE = "circuit_analysis_complete"

# 仿真需要用户选择主电路（检测到多个候选）
# 携带数据：
#   - candidates: list - 候选主电路文件路径列表
#   - reason: str - 触发原因（"multiple_main_circuits"）
EVENT_SIMULATION_NEED_SELECTION = "simulation_need_selection"

# 仿真未找到主电路
# 携带数据：
#   - reason: str - 触发原因（"no_main_circuit"）
EVENT_SIMULATION_NO_MAIN_CIRCUIT = "simulation_no_main_circuit"

# 仿真执行失败（错误已收集，准备下一轮修复）
# 携带数据：
#   - error_type: str - 错误类型
#   - error_message: str - 错误信息
#   - file: str - 错误文件（可选）
#   - line: int - 错误行号（可选）
EVENT_SIMULATION_ERROR_COLLECTED = "simulation_error_collected"

# 主电路检测完成（项目打开或文件变更后）
# 携带数据：
#   - candidates: list - 主电路候选文件路径列表
#   - count: int - 候选数量
EVENT_MAIN_CIRCUIT_DETECTED = "main_circuit_detected"

# 仿真执行器注册
# 携带数据：
#   - name: str - 执行器名称
#   - extensions: list - 支持的文件扩展名列表
EVENT_EXECUTOR_REGISTERED = "executor_registered"

# 仿真执行器注销
# 携带数据：
#   - name: str - 执行器名称
EVENT_EXECUTOR_UNREGISTERED = "executor_unregistered"

# ============================================================
# RAG 事件
# ============================================================

# RAG 索引开始
EVENT_RAG_INDEX_STARTED = "rag_index_started"

# RAG 索引进度
EVENT_RAG_INDEX_PROGRESS = "rag_index_progress"

# RAG 索引完成
EVENT_RAG_INDEX_COMPLETE = "rag_index_complete"

# RAG 检索完成
EVENT_RAG_SEARCH_COMPLETE = "rag_search_complete"

# ============================================================
# 上下文压缩事件
# ============================================================

# 请求压缩上下文
EVENT_CONTEXT_COMPRESS_REQUESTED = "context_compress_requested"

# 压缩预览就绪
EVENT_CONTEXT_COMPRESS_PREVIEW_READY = "context_compress_preview_ready"

# 压缩完成
EVENT_CONTEXT_COMPRESS_COMPLETE = "context_compress_complete"

# ============================================================
# 对话管理事件
# ============================================================

# 对话重置（新开对话）
# 携带数据：
#   - archived_session_id: str - 被归档的会话 ID（若有）
#   - new_session_id: str - 新会话 ID
EVENT_CONVERSATION_RESET = "conversation_reset"

# 对话归档
EVENT_CONVERSATION_ARCHIVED = "conversation_archived"

# 对话更新（消息列表变化）
EVENT_CONVERSATION_UPDATED = "conversation_updated"

# 会话加载完成
# 携带数据：
#   - session_id: str - 会话 ID
#   - session_name: str - 会话名称
#   - message_count: int - 消息数量
#   - is_new: bool - 是否为新建会话
EVENT_SESSION_LOADED = "session_loaded"

# 会话名称变更
# 携带数据：
#   - session_id: str - 会话 ID
#   - old_name: str - 旧名称
#   - new_name: str - 新名称
EVENT_SESSION_NAME_CHANGED = "session_name_changed"

# 会话状态变更（由 SessionStateManager 发布）
# 携带数据：
#   - session_name: str - 当前会话名称
#   - message_count: int - 消息数量
#   - action: str - 触发动作（"new", "switch", "save", "delete", "rename", "restore"）
#   - previous_session_name: str - 之前的会话名称（可选）
EVENT_SESSION_CHANGED = "session_changed"


# ============================================================
# 错误处理事件
# ============================================================

# 错误发生
EVENT_ERROR_OCCURRED = "error_occurred"

# 错误恢复
EVENT_ERROR_RECOVERED = "error_recovered"

# ============================================================
# 文件操作事件
# ============================================================

# 文件变更
EVENT_FILE_CHANGED = "file_changed"

# 文件锁定
EVENT_FILE_LOCKED = "file_locked"

# 文件解锁
EVENT_FILE_UNLOCKED = "file_unlocked"

# ============================================================
# 外部服务事件
# ============================================================

# 熔断器打开
EVENT_SERVICE_CIRCUIT_OPEN = "service_circuit_open"

# 熔断器关闭
EVENT_SERVICE_CIRCUIT_CLOSE = "service_circuit_close"

# ============================================================
# 国际化事件
# ============================================================

# 语言切换
EVENT_LANGUAGE_CHANGED = "language_changed"

# ============================================================
# 迭代确认事件
# ============================================================

# 等待用户确认
EVENT_ITERATION_AWAITING_CONFIRMATION = "iteration_awaiting_confirmation"

# 用户确认继续
EVENT_ITERATION_USER_CONFIRMED = "iteration_user_confirmed"

# 用户停止
EVENT_ITERATION_USER_STOPPED = "iteration_user_stopped"

# ============================================================
# 工作流锁定事件
# ============================================================

# 工作流锁定
EVENT_WORKFLOW_LOCKED = "workflow_locked"

# 工作流解锁
EVENT_WORKFLOW_UNLOCKED = "workflow_unlocked"


# ============================================================
# 关键事件列表（需要特殊保护）
# ============================================================

CRITICAL_EVENTS = [
    EVENT_ITERATION_AWAITING_CONFIRMATION,
    EVENT_WORKFLOW_LOCKED,
    EVENT_WORKFLOW_UNLOCKED,
    EVENT_ERROR_OCCURRED,
]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 初始化事件
    "EVENT_INIT_PHASE_COMPLETE",
    "EVENT_INIT_COMPLETE",
    # UI 交互事件
    "EVENT_UI_FILE_SELECTED",
    "EVENT_UI_SEND_MESSAGE",
    "EVENT_UI_REQUEST_SIMULATION",
    # 状态变更事件
    "EVENT_STATE_PROJECT_OPENED",
    "EVENT_STATE_PROJECT_CLOSED",
    "EVENT_STATE_CONFIG_CHANGED",
    "EVENT_STATE_ITERATION_UPDATED",
    # Worker 事件
    "EVENT_WORKER_STARTED",
    "EVENT_WORKER_PROGRESS",
    "EVENT_WORKER_COMPLETE",
    "EVENT_WORKER_ERROR",
    # LLM 事件
    "EVENT_LLM_CHUNK",
    "EVENT_LLM_COMPLETE",
    "EVENT_LLM_TOOL_CALL",
    # 联网搜索事件
    "EVENT_WEB_SEARCH_STARTED",
    "EVENT_WEB_SEARCH_COMPLETE",
    "EVENT_WEB_SEARCH_ERROR",
    # 仿真事件
    "EVENT_SIM_STARTED",
    "EVENT_SIM_COMPLETE",
    "EVENT_SIM_ERROR",
    "EVENT_MAIN_CIRCUIT_CHANGED",
    "EVENT_CIRCUIT_ANALYSIS_COMPLETE",
    "EVENT_SIMULATION_NEED_SELECTION",
    "EVENT_SIMULATION_NO_MAIN_CIRCUIT",
    "EVENT_SIMULATION_ERROR_COLLECTED",
    "EVENT_MAIN_CIRCUIT_DETECTED",
    "EVENT_EXECUTOR_REGISTERED",
    "EVENT_EXECUTOR_UNREGISTERED",
    # RAG 事件
    "EVENT_RAG_INDEX_STARTED",
    "EVENT_RAG_INDEX_PROGRESS",
    "EVENT_RAG_INDEX_COMPLETE",
    "EVENT_RAG_SEARCH_COMPLETE",
    # 上下文压缩事件
    "EVENT_CONTEXT_COMPRESS_REQUESTED",
    "EVENT_CONTEXT_COMPRESS_PREVIEW_READY",
    "EVENT_CONTEXT_COMPRESS_COMPLETE",
    # 对话管理事件
    "EVENT_CONVERSATION_RESET",
    "EVENT_CONVERSATION_ARCHIVED",
    "EVENT_CONVERSATION_UPDATED",
    "EVENT_SESSION_LOADED",
    "EVENT_SESSION_NAME_CHANGED",
    "EVENT_SESSION_CHANGED",
    # 错误处理事件
    "EVENT_ERROR_OCCURRED",
    "EVENT_ERROR_RECOVERED",
    # 文件操作事件
    "EVENT_FILE_CHANGED",
    "EVENT_FILE_LOCKED",
    "EVENT_FILE_UNLOCKED",
    # 外部服务事件
    "EVENT_SERVICE_CIRCUIT_OPEN",
    "EVENT_SERVICE_CIRCUIT_CLOSE",
    # 国际化事件
    "EVENT_LANGUAGE_CHANGED",
    # 迭代确认事件
    "EVENT_ITERATION_AWAITING_CONFIRMATION",
    "EVENT_ITERATION_USER_CONFIRMED",
    "EVENT_ITERATION_USER_STOPPED",
    # 工作流锁定事件
    "EVENT_WORKFLOW_LOCKED",
    "EVENT_WORKFLOW_UNLOCKED",
    # 关键事件列表
    "CRITICAL_EVENTS",
]
