# Shared Kernel Layer
"""
共享内核层 - 被所有层依赖的跨层基础设施

包含：
- service_names: 服务名常量定义
- service_locator: 服务定位器（依赖注入容器）
- event_types: 事件类型常量定义
- event_bus: 事件总线（发布-订阅通信）
- error_types: 错误类型常量定义
- error_handler: 统一错误处理器
- worker_types: Worker 类型常量定义
- worker_manager: Worker 生命周期管理器
- app_state: 应用状态容器
- i18n_manager: 国际化管理器

依赖方向（严格遵守，避免循环依赖）：
- service_names.py, event_types.py, error_types.py, worker_types.py: 纯常量定义，不依赖任何其他模块
- service_locator.py: 仅依赖 service_names.py
- event_bus.py: 依赖 event_types.py，不依赖 error_handler.py
- error_handler.py: 依赖 event_bus.py、error_types.py，内部错误处理不能再调用自身
- worker_manager.py: 依赖 event_bus.py、worker_types.py
- app_state.py: 依赖 event_bus.py、event_types.py
- 其他模块可依赖以上所有，但不能被以上模块反向依赖
"""

# 服务名常量
from shared.service_names import (
    SVC_EVENT_BUS,
    SVC_APP_STATE,
    SVC_ERROR_HANDLER,
    SVC_WORKER_MANAGER,
    SVC_I18N_MANAGER,
    SVC_CONFIG_MANAGER,
    SVC_FILE_MANAGER,
    SVC_PROJECT_SERVICE,
    SVC_DESIGN_WORKFLOW,
    SVC_TOOL_EXECUTOR,
    SVC_CONTEXT_MANAGER,
    SVC_PROMPT_TEMPLATE_MANAGER,
    SVC_EXTERNAL_SERVICE_MANAGER,
    SVC_ITERATION_TRACKER,
    SVC_VECTOR_STORE,
    SVC_CODE_INDEXER,
)

# 服务定位器
from shared.service_locator import (
    ServiceLocator,
    ServiceNotFoundError,
)

# 事件类型常量
from shared.event_types import (
    # 初始化事件
    EVENT_INIT_PHASE_COMPLETE,
    EVENT_INIT_COMPLETE,
    # UI 交互事件
    EVENT_UI_FILE_SELECTED,
    EVENT_UI_SEND_MESSAGE,
    EVENT_UI_REQUEST_SIMULATION,
    # 状态变更事件
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
    EVENT_STATE_CONFIG_CHANGED,
    EVENT_STATE_ITERATION_UPDATED,
    # Worker 事件
    EVENT_WORKER_STARTED,
    EVENT_WORKER_PROGRESS,
    EVENT_WORKER_COMPLETE,
    EVENT_WORKER_ERROR,
    # LLM 事件
    EVENT_LLM_CHUNK,
    EVENT_LLM_COMPLETE,
    EVENT_LLM_TOOL_CALL,
    # 仿真事件
    EVENT_SIM_STARTED,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    # RAG 事件
    EVENT_RAG_INDEX_STARTED,
    EVENT_RAG_INDEX_PROGRESS,
    EVENT_RAG_INDEX_COMPLETE,
    EVENT_RAG_SEARCH_COMPLETE,
    # 上下文压缩事件
    EVENT_CONTEXT_COMPRESS_REQUESTED,
    EVENT_CONTEXT_COMPRESS_PREVIEW_READY,
    EVENT_CONTEXT_COMPRESS_COMPLETE,
    # 错误处理事件
    EVENT_ERROR_OCCURRED,
    EVENT_ERROR_RECOVERED,
    # 文件操作事件
    EVENT_FILE_CHANGED,
    EVENT_FILE_LOCKED,
    EVENT_FILE_UNLOCKED,
    # 外部服务事件
    EVENT_SERVICE_CIRCUIT_OPEN,
    EVENT_SERVICE_CIRCUIT_CLOSE,
    # 国际化事件
    EVENT_LANGUAGE_CHANGED,
    # 迭代确认事件
    EVENT_ITERATION_AWAITING_CONFIRMATION,
    EVENT_ITERATION_USER_CONFIRMED,
    EVENT_ITERATION_USER_STOPPED,
    EVENT_ITERATION_AUTO_CONTINUED,
    # 工作流锁定事件
    EVENT_WORKFLOW_LOCKED,
    EVENT_WORKFLOW_UNLOCKED,
    # 关键事件列表
    CRITICAL_EVENTS,
)

# 事件总线
from shared.event_bus import (
    EventBus,
    EventHandler,
)

# 错误类型常量
from shared.error_types import (
    ErrorCategory,
    ErrorType,
    RecoveryStrategy,
    ERROR_CATEGORY_MAP,
    RECOVERY_STRATEGIES,
)

# 错误处理器
from shared.error_handler import ErrorHandler

# Worker 类型常量
from shared.worker_types import (
    WORKER_LLM,
    WORKER_SIMULATION,
    WORKER_RAG,
    WORKER_FILE_WATCHER,
    WorkerStatus,
    TaskPriority,
)

# Worker 管理器
from shared.worker_manager import (
    WorkerManager,
    Task,
    WorkerInfo,
)

# 应用状态容器
from shared.app_state import (
    AppState,
    StateChangeHandler,
    STATE_PROJECT_PATH,
    STATE_PROJECT_INITIALIZED,
    STATE_CURRENT_FILE,
    STATE_SELECTED_ITERATION,
    STATE_WORKFLOW_RUNNING,
    STATE_CURRENT_NODE,
    STATE_ITERATION_COUNT,
    STATE_WORKFLOW_LOCKED,
    STATE_LLM_CONFIGURED,
    STATE_RAG_ENABLED,
    STATE_INIT_PHASE,
    STATE_INIT_COMPLETE,
)

# 国际化管理器
from shared.i18n_manager import (
    I18nManager,
    LANG_EN_US,
    LANG_ZH_CN,
    SUPPORTED_LANGUAGES,
    LANGUAGE_NAMES,
)

__all__ = [
    # 服务名常量
    "SVC_EVENT_BUS",
    "SVC_APP_STATE",
    "SVC_ERROR_HANDLER",
    "SVC_WORKER_MANAGER",
    "SVC_I18N_MANAGER",
    "SVC_CONFIG_MANAGER",
    "SVC_FILE_MANAGER",
    "SVC_PROJECT_SERVICE",
    "SVC_DESIGN_WORKFLOW",
    "SVC_TOOL_EXECUTOR",
    "SVC_CONTEXT_MANAGER",
    "SVC_PROMPT_TEMPLATE_MANAGER",
    "SVC_EXTERNAL_SERVICE_MANAGER",
    "SVC_ITERATION_TRACKER",
    "SVC_VECTOR_STORE",
    "SVC_CODE_INDEXER",
    # 服务定位器
    "ServiceLocator",
    "ServiceNotFoundError",
    # 事件类型常量
    "EVENT_INIT_PHASE_COMPLETE",
    "EVENT_INIT_COMPLETE",
    "EVENT_UI_FILE_SELECTED",
    "EVENT_UI_SEND_MESSAGE",
    "EVENT_UI_REQUEST_SIMULATION",
    "EVENT_STATE_PROJECT_OPENED",
    "EVENT_STATE_PROJECT_CLOSED",
    "EVENT_STATE_CONFIG_CHANGED",
    "EVENT_STATE_ITERATION_UPDATED",
    "EVENT_WORKER_STARTED",
    "EVENT_WORKER_PROGRESS",
    "EVENT_WORKER_COMPLETE",
    "EVENT_WORKER_ERROR",
    "EVENT_LLM_CHUNK",
    "EVENT_LLM_COMPLETE",
    "EVENT_LLM_TOOL_CALL",
    "EVENT_SIM_STARTED",
    "EVENT_SIM_COMPLETE",
    "EVENT_SIM_ERROR",
    "EVENT_RAG_INDEX_STARTED",
    "EVENT_RAG_INDEX_PROGRESS",
    "EVENT_RAG_INDEX_COMPLETE",
    "EVENT_RAG_SEARCH_COMPLETE",
    "EVENT_CONTEXT_COMPRESS_REQUESTED",
    "EVENT_CONTEXT_COMPRESS_PREVIEW_READY",
    "EVENT_CONTEXT_COMPRESS_COMPLETE",
    "EVENT_ERROR_OCCURRED",
    "EVENT_ERROR_RECOVERED",
    "EVENT_FILE_CHANGED",
    "EVENT_FILE_LOCKED",
    "EVENT_FILE_UNLOCKED",
    "EVENT_SERVICE_CIRCUIT_OPEN",
    "EVENT_SERVICE_CIRCUIT_CLOSE",
    "EVENT_LANGUAGE_CHANGED",
    "EVENT_ITERATION_AWAITING_CONFIRMATION",
    "EVENT_ITERATION_USER_CONFIRMED",
    "EVENT_ITERATION_USER_STOPPED",
    "EVENT_ITERATION_AUTO_CONTINUED",
    "EVENT_WORKFLOW_LOCKED",
    "EVENT_WORKFLOW_UNLOCKED",
    "CRITICAL_EVENTS",
    # 事件总线
    "EventBus",
    "EventHandler",
    # 错误类型常量
    "ErrorCategory",
    "ErrorType",
    "RecoveryStrategy",
    "ERROR_CATEGORY_MAP",
    "RECOVERY_STRATEGIES",
    # 错误处理器
    "ErrorHandler",
    # Worker 类型常量
    "WORKER_LLM",
    "WORKER_SIMULATION",
    "WORKER_RAG",
    "WORKER_FILE_WATCHER",
    "WorkerStatus",
    "TaskPriority",
    # Worker 管理器
    "WorkerManager",
    "Task",
    "WorkerInfo",
    # 应用状态容器
    "AppState",
    "StateChangeHandler",
    "STATE_PROJECT_PATH",
    "STATE_PROJECT_INITIALIZED",
    "STATE_CURRENT_FILE",
    "STATE_SELECTED_ITERATION",
    "STATE_WORKFLOW_RUNNING",
    "STATE_CURRENT_NODE",
    "STATE_ITERATION_COUNT",
    "STATE_WORKFLOW_LOCKED",
    "STATE_LLM_CONFIGURED",
    "STATE_RAG_ENABLED",
    "STATE_INIT_PHASE",
    "STATE_INIT_COMPLETE",
    # 国际化管理器
    "I18nManager",
    "LANG_EN_US",
    "LANG_ZH_CN",
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_NAMES",
]
