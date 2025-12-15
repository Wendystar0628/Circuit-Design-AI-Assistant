# LLM Interaction Domain
"""
LLM 交互域

设计说明：
- 本模块包含 LLM 对话交互的核心业务逻辑
- 与具体 LLM 提供商无关，通过抽象接口调用适配器

目录结构（阶段三实现）：

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

# 消息类型
from domain.llm.message_types import (
    Message,
    TokenUsage,
    Attachment,
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    create_user_message,
    create_assistant_message,
    create_system_message,
    to_langchain_message,
    from_langchain_message,
    messages_to_langchain,
    messages_from_langchain,
)

# 消息适配器（解耦层）
from domain.llm.message_adapter import MessageAdapter

# 对话格式化
from domain.llm.conversation import (
    format_message_for_display,
    format_reasoning_content,
    split_content_and_reasoning,
    render_operations_summary,
    format_messages_for_export,
    StreamingContentBuffer,
)

# 上下文检索
from domain.llm.context_retriever import (
    ContextRetriever,
    RetrievalResult,
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
    CacheStatsTracker,
)

# Token 监控
from domain.llm.token_monitor import (
    TokenMonitor,
    DEFAULT_COMPRESS_THRESHOLD,
)

# 消息存储
from domain.llm.message_store import (
    MessageStore,
    IMPORTANCE_HIGH,
    IMPORTANCE_MEDIUM,
    IMPORTANCE_LOW,
)

# 上下文压缩
from domain.llm.context_compressor import (
    ContextCompressor,
    CompressPreview,
)

# 上下文管理器（门面类）
from domain.llm.context_manager import ContextManager

# 阶段三后续实现后导出
# from domain.llm.prompt_builder import PromptBuilder
# from domain.llm.external_service_manager import ExternalServiceManager

__all__ = [
    # 消息类型
    "Message",
    "TokenUsage",
    "Attachment",
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "create_user_message",
    "create_assistant_message",
    "create_system_message",
    "to_langchain_message",
    "from_langchain_message",
    "messages_to_langchain",
    "messages_from_langchain",
    # 消息适配器
    "MessageAdapter",
    # 对话格式化
    "format_message_for_display",
    "format_reasoning_content",
    "split_content_and_reasoning",
    "render_operations_summary",
    "format_messages_for_export",
    "StreamingContentBuffer",
    # 上下文检索
    "ContextRetriever",
    "RetrievalResult",
    # Token 计数
    "count_tokens",
    "count_message_tokens",
    "get_model_context_limit",
    "get_model_output_limit",
    "get_available_context",
    # 缓存统计
    "CacheStats",
    "SessionCacheStats",
    "CacheStatsTracker",
    # Token 监控
    "TokenMonitor",
    "DEFAULT_COMPRESS_THRESHOLD",
    # 消息存储
    "MessageStore",
    "IMPORTANCE_HIGH",
    "IMPORTANCE_MEDIUM",
    "IMPORTANCE_LOW",
    # 上下文压缩
    "ContextCompressor",
    "CompressPreview",
    # 上下文管理器
    "ContextManager",
    # 阶段三后续实现后导出
    # "PromptBuilder",
    # "ExternalServiceManager",
]
