# Tool Registry - 工具注册表
"""
工具注册表

职责：
- 集中管理所有已注册的 Agent 工具实例
- 提供按名称查找工具的能力
- 生成 OpenAI Function Calling 格式的工具 schema 列表，直接传给 LLM API

架构位置：
- 被 AgentLoop 调用以查找工具并执行
- 被 ZhipuRequestBuilder 调用以获取 tools 参数
- 依赖 domain/llm/agent/types.py 中的 BaseTool

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/index.ts
  - createAllTools(cwd) 模式：集中持有工具定义

使用示例：
    from domain.llm.agent.tool_registry import ToolRegistry
    from domain.llm.agent.types import ToolContext

    registry = ToolRegistry()
    registry.register(ReadFileTool())

    # 获取所有工具的 OpenAI schema（传给 LLM API）
    schemas = registry.get_all_openai_schemas()

    # 查找并执行工具
    tool = registry.get("read_file")
    if tool:
        context = ToolContext(project_root="/path/to/project")
        result = await tool.execute(call_id, params, context)
"""

import logging
from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool


# ============================================================
# 工具注册表
# ============================================================

class ToolRegistry:
    """
    工具注册表
    
    集中管理所有 Agent 工具实例，提供注册、查找、schema 生成能力。

    设计要点：
    - 非单例模式，允许不同 Agent 会话使用不同的注册表实例
    - 注册时检查名称唯一性，重复注册同名工具会覆盖并警告
    - get_all_openai_schemas() 的返回值可直接传给 ZhipuClient.chat(tools=...)
    """
    
    def __init__(self):
        """
        初始化工具注册表
        """
        self._tools: Dict[str, BaseTool] = {}
        self._logger = logging.getLogger(__name__)

    # ============================================================
    # 注册 / 注销
    # ============================================================

    def register(self, tool: BaseTool) -> None:
        """
        注册工具
        """
        name = tool.name

        if name in self._tools:
            self._logger.warning(
                f"Tool '{name}' already registered, overwriting with new instance"
            )

        self._tools[name] = tool

        self._logger.debug(f"Registered tool: {name}")

    # ============================================================
    # 查找
    # ============================================================

    def get(self, name: str) -> Optional[BaseTool]:
        """
        根据名称查找工具
        
        Args:
            name: 工具名称
            
        Returns:
            工具实例，未找到返回 None
        """
        return self._tools.get(name)

    def get_names(self) -> List[str]:
        """获取所有已注册工具的名称"""
        return list(self._tools.keys())

    # ============================================================
    # Schema 生成（供 LLM API 使用）
    # ============================================================

    def get_all_openai_schemas(self) -> List[Dict[str, Any]]:
        """
        获取所有已注册工具的 OpenAI Function Calling 格式 schema 列表
        
        返回值可直接传给 ZhipuClient.chat(tools=...) 参数。
        
        Returns:
            OpenAI tools 参数格式的字典列表
        """
        return [tool.get_openai_schema() for tool in self._tools.values()]

    def __repr__(self) -> str:
        tool_names = ", ".join(self._tools.keys())
        return f"<ToolRegistry(tools=[{tool_names}])>"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ToolRegistry",
]
