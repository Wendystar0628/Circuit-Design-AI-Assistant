# Service Name Constants
"""
服务名常量定义

职责：
- 集中定义所有服务名称常量
- 避免字符串硬编码
- 作为 ServiceLocator 注册和获取服务的键

运行时说明：
- 仅 bootstrap 实际注册的 key 才代表可用服务
- SVC_SESSION_STATE 是项目/RAG 状态的轻量 UI 读模型
- SVC_SESSION_STATE_PROJECTOR 连接项目/RAG 生命周期与该读模型

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

# 文件搜索服务 - 精确文件搜索（正则、模糊、符号）
SVC_FILE_SEARCH_SERVICE = "file_search_service"

# ============================================================
# 应用层状态服务
# ============================================================

# 项目/RAG 的轻量 UI 读模型。
SVC_SESSION_STATE = "session_state"

# ProjectService/RAG → SessionState 投影器。
SVC_SESSION_STATE_PROJECTOR = "session_state_projector"

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

# ============================================================
# 基础设施层服务 - LLM 适配器
# ============================================================

# LLM 客户端 - 大模型 API 调用
SVC_LLM_CLIENT = "llm_client"

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

# RAG 管理器 - RAG 业务逻辑（索引、查询）
SVC_RAG_MANAGER = "rag_manager"

# 仿真 Job 管理器 - 并发 job 提交与生命周期的唯一权威入口
SVC_SIMULATION_JOB_MANAGER = "simulation_job_manager"

# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 共享内核层
    "SVC_EVENT_BUS",
    "SVC_ERROR_HANDLER",
    "SVC_I18N_MANAGER",
    "SVC_LLM_EXECUTOR",
    # 基础设施层
    "SVC_CREDENTIAL_MANAGER",
    "SVC_CONFIG_MANAGER",
    "SVC_LLM_RUNTIME_CONFIG_MANAGER",
    "SVC_FILE_MANAGER",
    "SVC_FILE_SEARCH_SERVICE",
    "SVC_LLM_CLIENT",
    # 应用层状态投影
    "SVC_SESSION_STATE",
    "SVC_SESSION_STATE_PROJECTOR",
    # 应用层 - 其他
    "SVC_PROJECT_SERVICE",
    "SVC_FILE_WATCHER",
    "SVC_PENDING_WORKSPACE_EDIT_SERVICE",
    "SVC_METRIC_TARGET_SERVICE",
    # 领域层
    "SVC_CONTEXT_MANAGER",
    "SVC_CONTEXT_COMPRESSION_SERVICE",
    "SVC_SESSION_STATE_MANAGER",
    "SVC_CONVERSATION_ROLLBACK_SERVICE",
    "SVC_RAG_MANAGER",
    "SVC_SIMULATION_JOB_MANAGER",
]
