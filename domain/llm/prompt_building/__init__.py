# Prompt Building Module
"""
Prompt 构建模块组

职责：
- 构建上下文信息（不含身份提示词）
- 管理 Token 预算分配
- 格式化各种上下文数据
- 处理文件内容（截断、摘要）

⚠️ 职责变更：
- 身份提示词的注入已迁移到 SystemPromptInjector
- PromptBuilder 仅负责任务模板和上下文格式化

模块结构：
- prompt_builder.py           - 门面类，协调各子模块（不含身份提示词）
- token_budget_allocator.py   - Token 预算分配
- context_formatter.py        - 各种上下文的格式化
- file_content_processor.py   - 文件内容处理（截断、摘要）

设计理念：
- 门面模式：PromptBuilder 作为统一入口
- 单一职责：每个子模块专注一个功能领域
- 与 context_retrieval/ 模块组设计风格保持一致
"""

from domain.llm.prompt_building.prompt_builder import (
    PromptBuilder,
    PromptSection,
    BuildResult,
)
from domain.llm.prompt_building.token_budget_allocator import (
    TokenBudgetAllocator,
    TokenBudget,
    DEFAULT_BUDGET_RATIOS,
)
from domain.llm.prompt_building.context_formatter import (
    ContextFormatter,
)
from domain.llm.prompt_building.file_content_processor import (
    FileContentProcessor,
    SMALL_FILE_THRESHOLD,
    MEDIUM_FILE_THRESHOLD,
)


__all__ = [
    # 门面类
    "PromptBuilder",
    "PromptSection",
    "BuildResult",
    # Token 预算
    "TokenBudgetAllocator",
    "TokenBudget",
    "DEFAULT_BUDGET_RATIOS",
    # 格式化
    "ContextFormatter",
    # 文件处理
    "FileContentProcessor",
    "SMALL_FILE_THRESHOLD",
    "MEDIUM_FILE_THRESHOLD",
]
