# Service Name Constants
"""
服务名常量定义

职责：
- 集中定义所有服务名称常量
- 避免字符串硬编码
- 作为 ServiceLocator 注册和获取服务的键

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

# 应用状态容器 - 中央状态管理
SVC_APP_STATE = "app_state"

# 错误处理器 - 统一错误处理
SVC_ERROR_HANDLER = "error_handler"

# Worker管理器 - 后台任务调度
SVC_WORKER_MANAGER = "worker_manager"

# 国际化管理器 - 多语言支持
SVC_I18N_MANAGER = "i18n_manager"

# ============================================================
# 基础设施层服务
# ============================================================

# 凭证管理器 - 敏感信息加密存储
SVC_CREDENTIAL_MANAGER = "credential_manager"

# 配置管理器 - 统一配置访问
SVC_CONFIG_MANAGER = "config_manager"

# 文件管理器 - 统一文件操作
SVC_FILE_MANAGER = "file_manager"

# ============================================================
# 应用层服务
# ============================================================

# 项目服务 - 工作文件夹管理
SVC_PROJECT_SERVICE = "project_service"

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
# 领域层服务
# ============================================================

# 上下文管理器 - 对话消息和 Token 管理
SVC_CONTEXT_MANAGER = "context_manager"

# Prompt 模板管理器 - 提示词模板
SVC_PROMPT_TEMPLATE_MANAGER = "prompt_template_manager"

# 外部服务管理器 - API 调用熔断和重试
SVC_EXTERNAL_SERVICE_MANAGER = "external_service_manager"

# 迭代跟踪器 - 状态同步
SVC_ITERATION_TRACKER = "iteration_tracker"

# 向量存储 - RAG 知识库
SVC_VECTOR_STORE = "vector_store"

# 代码索引器 - 工作区代码索引
SVC_CODE_INDEXER = "code_indexer"

# 仿真服务 - 电路仿真协调
SVC_SIMULATION_SERVICE = "simulation_service"

# 执行器注册表 - 仿真执行器管理
SVC_EXECUTOR_REGISTRY = "executor_registry"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 共享内核层
    "SVC_EVENT_BUS",
    "SVC_APP_STATE",
    "SVC_ERROR_HANDLER",
    "SVC_WORKER_MANAGER",
    "SVC_I18N_MANAGER",
    # 基础设施层
    "SVC_CREDENTIAL_MANAGER",
    "SVC_CONFIG_MANAGER",
    "SVC_FILE_MANAGER",
    "SVC_LLM_CLIENT",
    # 应用层
    "SVC_PROJECT_SERVICE",
    "SVC_DESIGN_WORKFLOW",
    "SVC_TOOL_EXECUTOR",
    # 领域层
    "SVC_CONTEXT_MANAGER",
    "SVC_PROMPT_TEMPLATE_MANAGER",
    "SVC_EXTERNAL_SERVICE_MANAGER",
    "SVC_ITERATION_TRACKER",
    "SVC_VECTOR_STORE",
    "SVC_CODE_INDEXER",
    "SVC_SIMULATION_SERVICE",
    "SVC_EXECUTOR_REGISTRY",
]
