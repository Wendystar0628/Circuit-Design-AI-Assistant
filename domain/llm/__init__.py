# LLM Interaction Domain
"""
LLM 交互域

设计说明：
- 本模块包含 LLM 对话交互的核心业务逻辑
- 与具体 LLM 提供商无关，通过抽象接口调用适配器
- 消息直接使用 LangChain 消息类型，通过 message_helpers 操作

目录结构（阶段三实现）：

消息辅助模块：
- message_helpers.py: LangChain 消息扩展字段读写辅助函数
- message_types.py: 辅助数据结构（TokenUsage、Attachment）

上下文管理模块组：
- context_manager.py: 门面类，协调各子模块
- message_store.py: 消息存储与检索
- token_monitor.py: Token 使用监控
- context_compressor.py: 上下文压缩逻辑
- cache_stats_tracker.py: 缓存统计追踪

对话辅助模块：
- conversation.py: 对话格式化辅助
- context_retriever.py: 智能上下文检索

Prompt 管理模块：
- prompt_template_manager.py: Prompt 模板统一管理
- prompt_builder.py: 提示词构建器

外部服务管理：
- external_service_manager.py: 外部服务统一管理（重试/熔断）
"""

# 消息辅助函数
from domain.llm.message_helpers import (
    # 角色常量
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
    VALID_ROLES,
    # 消息创建
    create_human_message,
    create_ai_message,
    create_system_message,
    create_tool_message,
    # 扩展字段读取
    get_reasoning_content,
    get_operations,
    get_usage,
    get_attachments,
    get_timestamp,
    is_partial_response,
    get_stop_reason,
    get_tool_calls_pending,
    get_web_search_results,
    # 扩展字段写入
    set_reasoning_content,
    set_operations,
    mark_as_partial,
    mark_as_complete,
    # 消息类型判断
    is_human_message,
    is_ai_message,
    is_system_message,
    is_tool_message,
    get_role,
    # 序列化
    message_to_dict,
    dict_to_message,
    messages_to_dicts,
    dicts_to_messages,
)

# 辅助数据结构
from domain.llm.message_types import (
    TokenUsage,
    Attachment,
)

# 对话格式化
from domain.llm.conversation import (
    format_message_for_display,
    format_reasoning_content,
    split_content_and_reasoning,
    format_partial_indicator,
    render_operations_summary,
    render_web_search_results,
    format_messages_for_export,
    StreamingContentBuffer,
)

# 上下文检索（从 context_retrieval 模块组导入）
from domain.llm.context_retrieval import (
    ContextRetriever,
    RetrievalResult,
    RetrievalContext,
)

# Token 计数
from domain.llm.token_counter import (
    count_tokens,
    count_message_tokens,
    get_model_context_limit,
    get_model_output_limit,
    get_available_context,
)

# 缓存统计
from domain.llm.cache_stats_tracker import (
    CacheStats,
    SessionCacheStats,
    CacheEfficiencyReport,
    CacheStatsTracker,
)

# Token 监控
from domain.llm.token_monitor import (
    TokenMonitor,
    DEFAULT_COMPRESS_THRESHOLD,
    TARGET_USAGE_AFTER_COMPRESS,
)

# 消息存储
from domain.llm.message_store import (
    MessageStore,
    IMPORTANCE_HIGH,
    IMPORTANCE_MEDIUM,
    IMPORTANCE_LOW,
)

# 会话状态管理器
from domain.llm.session_state_manager import (
    SessionStateManager,
    SessionInfo,
)

# 上下文压缩
from domain.llm.context_compressor import (
    ContextCompressor,
    CompressPreview,
)

# 上下文管理器（门面类）
from domain.llm.context_manager import ContextManager

# Prompt 模板常量
from domain.llm.prompt_constants import (
    # 任务级模板
    PROMPT_EXTRACT_DESIGN_GOALS,
    PROMPT_INITIAL_DESIGN,
    PROMPT_ANALYZE_SIMULATION,
    PROMPT_OPTIMIZE_PARAMETERS,
    PROMPT_FIX_ERROR,
    PROMPT_EXECUTE_INSTRUCTION,
    PROMPT_GENERAL_CONVERSATION,
    PROMPT_SUMMARIZE_CONVERSATION,
    PROMPT_INTENT_ANALYSIS,
    # 输出格式模板
    FORMAT_SPICE_OUTPUT,
    FORMAT_JSON_OUTPUT,
    FORMAT_ANALYSIS_OUTPUT,
    # 映射关系
    TEMPLATE_FORMAT_MAPPING,
    NODE_TEMPLATE_MAPPING,
    # 节点名称常量
    NODE_DESIGN_GOALS,
    NODE_INITIAL_DESIGN,
    NODE_ANALYSIS,
    NODE_INTENT_ANALYSIS,
    # Action 名称常量
    ACTION_OPTIMIZE_PARAMETERS,
    ACTION_FIX_ERROR,
    ACTION_EXECUTE_INSTRUCTION,
    ACTION_GENERAL_CONVERSATION,
    # 辅助函数
    get_template_for_node,
)

# Prompt 模板管理器
from domain.llm.prompt_template_manager import (
    PromptTemplateManager,
    Template,
    TemplateMetadata,
)

# Prompt 构建模块组
from domain.llm.prompt_building import (
    PromptBuilder,
    TokenBudget,
    PromptSection,
    BuildResult,
    DEFAULT_BUDGET_RATIOS,
    TokenBudgetAllocator,
    ContextFormatter,
    FileContentProcessor,
)

# 系统提示词注入器
from domain.llm.system_prompt_injector import (
    SystemPromptInjector,
    InjectionResult,
    LAYER_SEPARATOR,
    LAYER_MARKERS,
)

# 身份提示词管理器
from domain.llm.identity_prompt_manager import (
    IdentityPromptManager,
    IdentityPrompt,
)

# 外部服务管理器
from domain.llm.external_service_manager import (
    ExternalServiceManager,
    ServiceCallResult,
    CallStatistics,
    CircuitBreaker,
    CircuitState,
    ServiceStatus,
    SERVICE_LLM_ZHIPU,
    SERVICE_LLM_GEMINI,
    SERVICE_LLM_OPENAI,
    SERVICE_LLM_CLAUDE,
    SERVICE_LLM_QWEN,
    SERVICE_LLM_DEEPSEEK,
    SERVICE_SEARCH_ZHIPU,
    SERVICE_SEARCH_GOOGLE,
    SERVICE_SEARCH_BING,
    ALL_SERVICE_TYPES,
)

# LLM 执行器
from domain.llm.llm_executor import LLMExecutor

__all__ = [
    # 角色常量
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_TOOL",
    "VALID_ROLES",
    # 消息创建
    "create_human_message",
    "create_ai_message",
    "create_system_message",
    "create_tool_message",
    # 扩展字段读取
    "get_reasoning_content",
    "get_operations",
    "get_usage",
    "get_attachments",
    "get_timestamp",
    "is_partial_response",
    "get_stop_reason",
    "get_tool_calls_pending",
    "get_web_search_results",
    # 扩展字段写入
    "set_reasoning_content",
    "set_operations",
    "mark_as_partial",
    "mark_as_complete",
    # 消息类型判断
    "is_human_message",
    "is_ai_message",
    "is_system_message",
    "is_tool_message",
    "get_role",
    # 序列化
    "message_to_dict",
    "dict_to_message",
    "messages_to_dicts",
    "dicts_to_messages",
    # 辅助数据结构
    "TokenUsage",
    "Attachment",
    # 对话格式化
    "format_message_for_display",
    "format_reasoning_content",
    "split_content_and_reasoning",
    "format_partial_indicator",
    "render_operations_summary",
    "render_web_search_results",
    "format_messages_for_export",
    "StreamingContentBuffer",
    # 上下文检索
    "ContextRetriever",
    "RetrievalResult",
    "RetrievalContext",
    # Token 计数
    "count_tokens",
    "count_message_tokens",
    "get_model_context_limit",
    "get_model_output_limit",
    "get_available_context",
    # 缓存统计
    "CacheStats",
    "SessionCacheStats",
    "CacheEfficiencyReport",
    "CacheStatsTracker",
    # Token 监控
    "TokenMonitor",
    "DEFAULT_COMPRESS_THRESHOLD",
    "TARGET_USAGE_AFTER_COMPRESS",
    # 消息存储
    "MessageStore",
    "IMPORTANCE_HIGH",
    "IMPORTANCE_MEDIUM",
    "IMPORTANCE_LOW",
    # 会话状态管理器
    "SessionStateManager",
    "SessionInfo",
    # 上下文压缩
    "ContextCompressor",
    "CompressPreview",
    # 上下文管理器
    "ContextManager",
    # Prompt 模板常量 - 任务级
    "PROMPT_EXTRACT_DESIGN_GOALS",
    "PROMPT_INITIAL_DESIGN",
    "PROMPT_ANALYZE_SIMULATION",
    "PROMPT_OPTIMIZE_PARAMETERS",
    "PROMPT_FIX_ERROR",
    "PROMPT_EXECUTE_INSTRUCTION",
    "PROMPT_GENERAL_CONVERSATION",
    "PROMPT_SUMMARIZE_CONVERSATION",
    "PROMPT_INTENT_ANALYSIS",
    # Prompt 模板常量 - 输出格式
    "FORMAT_SPICE_OUTPUT",
    "FORMAT_JSON_OUTPUT",
    "FORMAT_ANALYSIS_OUTPUT",
    # Prompt 模板常量 - 映射关系
    "TEMPLATE_FORMAT_MAPPING",
    "NODE_TEMPLATE_MAPPING",
    # Prompt 模板常量 - 节点名称
    "NODE_DESIGN_GOALS",
    "NODE_INITIAL_DESIGN",
    "NODE_ANALYSIS",
    "NODE_INTENT_ANALYSIS",
    # Prompt 模板常量 - Action 名称
    "ACTION_OPTIMIZE_PARAMETERS",
    "ACTION_FIX_ERROR",
    "ACTION_EXECUTE_INSTRUCTION",
    "ACTION_GENERAL_CONVERSATION",
    # Prompt 模板常量 - 辅助函数
    "get_template_for_node",
    # Prompt 模板管理器
    "PromptTemplateManager",
    "Template",
    "TemplateMetadata",
    # Prompt 构建模块组
    "PromptBuilder",
    "TokenBudget",
    "PromptSection",
    "BuildResult",
    "DEFAULT_BUDGET_RATIOS",
    "TokenBudgetAllocator",
    "ContextFormatter",
    "FileContentProcessor",
    # 系统提示词注入器
    "SystemPromptInjector",
    "InjectionResult",
    "LAYER_SEPARATOR",
    "LAYER_MARKERS",
    # 身份提示词管理器
    "IdentityPromptManager",
    "IdentityPrompt",
    # 外部服务管理器
    "ExternalServiceManager",
    "ServiceCallResult",
    "CallStatistics",
    "CircuitBreaker",
    "CircuitState",
    "ServiceStatus",
    "SERVICE_LLM_ZHIPU",
    "SERVICE_LLM_GEMINI",
    "SERVICE_LLM_OPENAI",
    "SERVICE_LLM_CLAUDE",
    "SERVICE_LLM_QWEN",
    "SERVICE_LLM_DEEPSEEK",
    "SERVICE_SEARCH_ZHIPU",
    "SERVICE_SEARCH_GOOGLE",
    "SERVICE_SEARCH_BING",
    "ALL_SERVICE_TYPES",
    # LLM 执行器
    "LLMExecutor",
]
