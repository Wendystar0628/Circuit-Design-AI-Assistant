# Agent Module - Agent 工具调用核心模块
"""
Agent 工具调用模块

职责：
- 定义 Agent 工具调用的基础类型体系（BaseTool、ToolResult、ToolContext 等）
- 提供工具注册表（ToolRegistry）
- 实现 ReAct 循环控制器（AgentLoop）
- 构建 Agent 系统提示词（AgentPromptBuilder）

架构位置：
- domain/llm/agent/ 是 Agent 功能的模块根
- 依赖 infrastructure/llm_adapters/ 的 BaseLLMClient 和 StreamChunk
- 依赖 domain/llm/message_helpers.py 的消息创建辅助函数
- 被 domain/llm/llm_executor.py 调用以执行 Agent 模式

模块结构：
- types.py        : 基础类型定义（BaseTool、ToolResult、ToolContext、ToolCallInfo）
- tool_registry.py : 工具注册表
- agent_loop.py   : ReAct 循环控制器（后续实现）
- agent_prompt_builder.py : Agent 系统提示词构建器（后续实现）
- tools/          : 具体工具实现（read_file、patch_file 已实现）
- utils/          : 工具函数（path_utils、truncate、edit_diff、file_mutex 已实现）
"""

from domain.llm.agent.types import (
    # 工具执行结果
    ToolResult,
    # 工具 Schema 定义
    ToolSchema,
    # 工具执行上下文
    ToolContext,
    # 工具调用信息（从 LLM 响应解析）
    ToolCallInfo,
    # 工具执行状态
    ToolExecutionStatus,
    # 工具基类
    BaseTool,
    # 工厂函数
    create_error_result,
    create_success_result,
)

from domain.llm.agent.tool_registry import (
    ToolRegistry,
    GROUP_FILE_OPS,
    GROUP_SEARCH,
    GROUP_SIMULATION,
    GROUP_ALL,
)

from domain.llm.agent.tools import ReadFileTool, PatchFileTool


__all__ = [
    # 基础类型
    "ToolResult",
    "ToolSchema",
    "ToolContext",
    "ToolCallInfo",
    "ToolExecutionStatus",
    "BaseTool",
    "create_error_result",
    "create_success_result",
    # 注册表
    "ToolRegistry",
    "GROUP_FILE_OPS",
    "GROUP_SEARCH",
    "GROUP_SIMULATION",
    "GROUP_ALL",
    # 工具
    "ReadFileTool",
    "PatchFileTool",
]
