# Tool Factory - Agent 工具工厂
"""
Agent 工具工厂

职责：
- 集中创建并注册所有默认工具到 ToolRegistry
- 处理条件性注册（RAGSearchTool 仅在 RAG 服务可用时注册）
- 替代 LLMExecutor.execute_agent() 中的分散内联注册逻辑

架构位置：
- 被 LLMExecutor.execute_agent() 调用，取代原来的内联注册
- 对应 pi-mono createAllTools(cwd) / createCodingToolDefinitions(cwd) 模式
- 所有工具注册变更只需修改本文件

工具分组说明：
    GROUP_FILE_OPS  → read_file, patch_file, rewrite_file
    GROUP_SEARCH    → grep_search, find_files, list_directory, rag_search(条件)
    GROUP_ALL       → 所有工具（自动加入）

使用示例：
    from domain.llm.agent.tool_factory import create_default_tools
    from domain.llm.agent.types import ToolContext

    context = ToolContext(project_root="/path/to/project")
    registry = create_default_tools(context)
    # registry 已注册所有可用工具，可直接传给 AgentLoop
"""

import logging

from domain.llm.agent.types import ToolContext
from domain.llm.agent.tool_registry import (
    ToolRegistry,
    GROUP_FILE_OPS,
    GROUP_SEARCH,
)

logger = logging.getLogger(__name__)


# ============================================================
# 公开工厂函数
# ============================================================

def create_default_tools(context: ToolContext) -> ToolRegistry:
    """
    创建并注册所有默认工具到新 ToolRegistry 实例

    对应 pi-mono 的 createAllTools(cwd) 模式。
    集中管理工具注册逻辑，外部调用方只需调用此函数。

    注册的工具：
        文件操作：read_file, patch_file, rewrite_file
        搜索导航：grep_search, find_files, list_directory
        知识检索：rag_search（仅当 RAG 服务可用时）

    Args:
        context: 工具执行上下文（包含 project_root 等）

    Returns:
        已完成注册的 ToolRegistry 实例
    """
    from domain.llm.agent.tools.read_file import ReadFileTool
    from domain.llm.agent.tools.patch_file import PatchFileTool
    from domain.llm.agent.tools.rewrite_file import RewriteFileTool
    from domain.llm.agent.tools.grep_search import GrepSearchTool
    from domain.llm.agent.tools.find_files import FindFilesTool
    from domain.llm.agent.tools.list_directory import ListDirectoryTool
    from domain.llm.agent.tools.rag_search import RAGSearchTool

    registry = ToolRegistry(context)

    # ---- 文件操作工具（核心，始终注册）----
    registry.register(ReadFileTool(), [GROUP_FILE_OPS])
    registry.register(PatchFileTool(), [GROUP_FILE_OPS])
    registry.register(RewriteFileTool(), [GROUP_FILE_OPS])

    # ---- 搜索 / 导航工具（始终注册）----
    registry.register(GrepSearchTool(), [GROUP_SEARCH])
    registry.register(FindFilesTool(), [GROUP_SEARCH])
    registry.register(ListDirectoryTool(), [GROUP_SEARCH])

    registry.register(RAGSearchTool(), [GROUP_SEARCH])

    logger.debug(f"Tool factory created registry: {registry!r}")
    return registry


# ============================================================
# 模块导出
# ============================================================

__all__ = ["create_default_tools"]
