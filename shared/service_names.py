# Service Name Constants
"""
服务名常量定义

职责：
- 集中定义所有服务名称常量
- 避免字符串硬编码
- 作为 ServiceLocator 注册和获取服务的键

三层状态分离架构：
- SVC_UI_STATE: 纯 UI 状态（窗口布局、面板可见性、编辑器状态）
- SVC_SESSION_STATE: GraphState 的只读投影，供 UI 层读取业务状态
- SVC_GRAPH_STATE_PROJECTOR: 监听 GraphState 变更，自动投影到 SessionState

设计原则：
- 纯常量定义，不依赖任何其他模块
- 所有服务名使用 SVC_ 前缀
- 按功能模块分组组织

使用示例：
    from shared.service_names import SVC_EVENT_BUS
    event_bus = ServiceLocator.get(SVC_EVENT_BUS)
"""

# ============================================================
# 共享内核层服务
# ============================================================

# 事件总线 - 跨组件通信
SVC_EVENT_BUS = "event_bus"

# 错误处理器 - 统一错误处理
SVC_ERROR_HANDLER = "error_handler"

# Worker管理器 - 后台任务调度（旧名称，保留兼容）
SVC_WORKER_MANAGER = "worker_manager"

# 异步任务注册表 - 异步任务管理（新名称）
SVC_ASYNC_TASK_REGISTRY = "async_task_registry"

# CPU 任务执行器 - CPU 密集型任务执行
SVC_CPU_TASK_EXECUTOR = "cpu_task_executor"

# 国际化管理器 - 多语言支持
SVC_I18N_MANAGER = "i18n_manager"

# LLM 执行器 - LLM 调用执行引擎
SVC_LLM_EXECUTOR = "llm_executor"

# ============================================================
# 基础设施层服务
# ============================================================

# 凭证管理器 - 敏感信息存储
SVC_CREDENTIAL_MANAGER = "credential_manager"

# 配置管理器 - 统一配置访问
SVC_CONFIG_MANAGER = "config_manager"

# LLM 运行时配置管理器 - 当前模型与 API Key 的统一解析与保存入口
SVC_LLM_RUNTIME_CONFIG_MANAGER = "llm_runtime_config_manager"

# 文件管理器 - 统一文件操作（同步底层接口）
SVC_FILE_MANAGER = "file_manager"

# 异步文件操作 - 应用层文件操作接口（UI 层和 LangGraph 节点使用）
SVC_ASYNC_FILE_OPS = "async_file_ops"

# 文件搜索服务 - 精确文件搜索（正则、模糊、符号）
SVC_FILE_SEARCH_SERVICE = "file_search_service"

# 统一搜索服务 - 项目级搜索门面（协调精确搜索和语义搜索）
SVC_UNIFIED_SEARCH_SERVICE = "unified_search_service"

# 单文件搜索服务 - 单文件搜索（分层降级策略）
SVC_IN_FILE_SEARCH_SERVICE = "in_file_search_service"

# ============================================================
# 应用层服务 - 三层状态分离架构
# ============================================================

# UI 状态容器 - 纯 UI 状态（窗口布局、面板可见性、编辑器状态）
# Layer 1: Presentation 层
SVC_UI_STATE = "ui_state"

# 会话状态 - GraphState 的只读投影，供 UI 层读取业务状态
# Layer 2: Application 层
SVC_SESSION_STATE = "session_state"

# GraphState 投影器 - 监听 GraphState 变更，自动投影到 SessionState
# 连接 Layer 2 和 Layer 3
SVC_GRAPH_STATE_PROJECTOR = "graph_state_projector"

# ============================================================
# 应用层服务 - 其他
# ============================================================

# 项目服务 - 工作文件夹管理
SVC_PROJECT_SERVICE = "project_service"

# 文件监听服务 - 文件系统变化监听
SVC_FILE_WATCHER = "file_watcher"
SVC_PENDING_WORKSPACE_EDIT_SERVICE = "pending_workspace_edit_service"

# 指标目标值持久化服务 - 按电路源文件记录 .MEASURE 指标的用户设定目标
SVC_METRIC_TARGET_SERVICE = "metric_target_service"

# 信息卡片持久化服务 - 信息面板卡片的持久化存储
SVC_INFO_CARD_PERSISTENCE = "info_card_persistence"

# 设计工作流 - LangGraph 编排
SVC_DESIGN_WORKFLOW = "design_workflow"

# 工具执行器 - LLM 工具调用
SVC_TOOL_EXECUTOR = "tool_executor"

# ============================================================
# 基础设施层服务 - LLM 适配器
# ============================================================

# LLM 客户端 - 大模型 API 调用
SVC_LLM_CLIENT = "llm_client"

# ============================================================
# 基础设施层服务 - 追踪系统（阶段 1.5）
# ============================================================

# 追踪存储 - SQLite 持久化
SVC_TRACING_STORE = "tracing_store"

# 追踪日志器 - 内存缓冲 + 定时刷新
SVC_TRACING_LOGGER = "tracing_logger"

# ============================================================
# 领域层服务
# ============================================================

# 上下文管理器 - 对话消息和 Token 管理
SVC_CONTEXT_MANAGER = "context_manager"

# 上下文压缩服务 - 压缩预算、预览、执行协调
SVC_CONTEXT_COMPRESSION_SERVICE = "context_compression_service"

# 会话状态管理器 - 会话状态的唯一数据源
SVC_SESSION_STATE_MANAGER = "session_state_manager"

# 对话节点撤回服务 - 以用户消息为锚点恢复会话与工作区
SVC_CONVERSATION_ROLLBACK_SERVICE = "conversation_rollback_service"

# 外部服务管理器 - API 调用熔断和重试
SVC_EXTERNAL_SERVICE_MANAGER = "external_service_manager"

# RAG 管理器 - RAG 业务逻辑（索引、查询）
SVC_RAG_MANAGER = "rag_manager"

# 仿真服务 - 电路仿真协调
SVC_SIMULATION_SERVICE = "simulation_service"

# 仿真 Job 管理器 - 并发 job 提交与生命周期的唯一权威入口
SVC_SIMULATION_JOB_MANAGER = "simulation_job_manager"

# 仿真结果仓储 - result.json 的权威加载/枚举/按电路聚合读取入口
# （Step 16 agent read-tool 基座通过 ToolContext 消费它，ToolContext
# 由 LLMExecutor 从 ServiceLocator 取本 key 注入；agent 工具禁止再
# import 模块级 singleton。UI 侧 SimulationTab 当前仍直 import 同一
# 单例对象——那是独立的 UI 层 hygiene 议题，不在 Step 16 范围内。）
SVC_SIMULATION_RESULT_REPOSITORY = "simulation_result_repository"

# 执行器注册表 - 仿真执行器管理
SVC_EXECUTOR_REGISTRY = "executor_registry"

# 波形数据服务 - 大数据波形降采样和流式渲染
SVC_WAVEFORM_DATA_SERVICE = "waveform_data_service"

# 依赖健康服务 - 依赖完整性检查和解析
SVC_DEPENDENCY_HEALTH_SERVICE = "dependency_health_service"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 共享内核层
    "SVC_EVENT_BUS",
    "SVC_ERROR_HANDLER",
    "SVC_WORKER_MANAGER",
    "SVC_ASYNC_TASK_REGISTRY",
    "SVC_CPU_TASK_EXECUTOR",
    "SVC_I18N_MANAGER",
    "SVC_LLM_EXECUTOR",
    # 基础设施层
    "SVC_CREDENTIAL_MANAGER",
    "SVC_CONFIG_MANAGER",
    "SVC_LLM_RUNTIME_CONFIG_MANAGER",
    "SVC_FILE_MANAGER",
    "SVC_ASYNC_FILE_OPS",
    "SVC_FILE_SEARCH_SERVICE",
    "SVC_UNIFIED_SEARCH_SERVICE",
    "SVC_IN_FILE_SEARCH_SERVICE",
    "SVC_LLM_CLIENT",
    "SVC_TRACING_STORE",
    "SVC_TRACING_LOGGER",
    # 应用层 - 三层状态分离架构
    "SVC_UI_STATE",
    "SVC_SESSION_STATE",
    "SVC_GRAPH_STATE_PROJECTOR",
    # 应用层 - 其他
    "SVC_PROJECT_SERVICE",
    "SVC_FILE_WATCHER",
    "SVC_PENDING_WORKSPACE_EDIT_SERVICE",
    "SVC_METRIC_TARGET_SERVICE",
    "SVC_INFO_CARD_PERSISTENCE",
    "SVC_DESIGN_WORKFLOW",
    "SVC_TOOL_EXECUTOR",
    # 领域层
    "SVC_CONTEXT_MANAGER",
    "SVC_CONTEXT_COMPRESSION_SERVICE",
    "SVC_SESSION_STATE_MANAGER",
    "SVC_CONVERSATION_ROLLBACK_SERVICE",
    "SVC_EXTERNAL_SERVICE_MANAGER",
    "SVC_RAG_MANAGER",
    "SVC_SIMULATION_SERVICE",
    "SVC_SIMULATION_JOB_MANAGER",
    "SVC_SIMULATION_RESULT_REPOSITORY",
    "SVC_EXECUTOR_REGISTRY",
    "SVC_WAVEFORM_DATA_SERVICE",
    "SVC_DEPENDENCY_HEALTH_SERVICE",
]
