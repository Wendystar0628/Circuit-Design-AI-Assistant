# Tool Factory - Agent 工具工厂
"""
Agent 工具工厂

职责：
- 集中创建并注册所有默认工具到 ToolRegistry
- 替代 LLMExecutor.execute_agent() 中的分散内联注册逻辑

架构位置：
- 被 LLMExecutor.execute_agent() 调用，取代原来的内联注册
- 对应 pi-mono createAllTools(cwd) / createCodingToolDefinitions(cwd) 模式
- 所有工具注册变更只需修改本文件

使用示例：
    from domain.llm.agent.tool_factory import create_default_tools

    registry = create_default_tools()
    # registry 已注册所有可用工具，可直接传给 AgentLoop
"""

import logging

from domain.llm.agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


# ============================================================
# 公开工厂函数
# ============================================================

def create_default_tools() -> ToolRegistry:
    """
    创建并注册所有默认工具到新 ToolRegistry 实例

    对应 pi-mono 的 createAllTools(cwd) 模式。
    集中管理工具注册逻辑，外部调用方只需调用此函数。
    注册的工具：
        文件操作：read_file, patch_file, rewrite_file
        搜索导航：grep_search, find_files, list_directory
        知识检索：rag_search

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
    from domain.llm.agent.tools.web_search import WebSearchTool

    registry = ToolRegistry()

    # ---- 文件操作工具（核心，始终注册）----
    registry.register(ReadFileTool())
    registry.register(PatchFileTool())
    registry.register(RewriteFileTool())

    # ---- 搜索 / 导航工具（始终注册）----
    registry.register(GrepSearchTool())
    registry.register(FindFilesTool())
    registry.register(ListDirectoryTool())

    registry.register(RAGSearchTool())
    registry.register(WebSearchTool())

    logger.debug(f"Tool factory created registry: {registry!r}")
    return registry


# ============================================================
# 模块导出
# ============================================================

__all__ = ["create_default_tools"]
