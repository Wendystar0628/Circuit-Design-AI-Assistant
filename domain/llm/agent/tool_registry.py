# Tool Registry - 工具注册表
"""
工具注册表

职责：
- 集中管理所有已注册的 Agent 工具实例
- 提供按名称查找工具的能力
- 生成 OpenAI Function Calling 格式的工具 schema 列表，直接传给 LLM API
- 支持工具分组（按类别获取子集）

架构位置：
- 被 AgentLoop 调用以查找工具并执行
- 被 ZhipuRequestBuilder 调用以获取 tools 参数
- 依赖 domain/llm/agent/types.py 中的 BaseTool 和 ToolContext

参考来源：
- pi-mono: packages/coding-agent/src/core/tools/index.ts
  - createAllTools(cwd) 模式：注册表接收 ToolContext，传递给工具

使用示例：
    from domain.llm.agent.tool_registry import ToolRegistry
    from domain.llm.agent.types import ToolContext

    context = ToolContext(project_root="/path/to/project")
    registry = ToolRegistry(context)
    registry.register(ReadFileTool())

    # 获取所有工具的 OpenAI schema（传给 LLM API）
    schemas = registry.get_all_openai_schemas()

    # 查找并执行工具
    tool = registry.get("read_file")
    if tool:
        result = await tool.execute(call_id, params, context)
"""

import logging
from typing import Any, Dict, List, Optional, Set

from domain.llm.agent.types import BaseTool, ToolContext, ToolSchema


# ============================================================
# 工具分组常量
# ============================================================

GROUP_FILE_OPS = "file_ops"       # 文件操作类：read_file, patch_file, rewrite_file
GROUP_SEARCH = "search"           # 搜索类：grep, find, ls
GROUP_ALL = "all"                 # 所有工具


# ============================================================
# 工具注册表
# ============================================================

class ToolRegistry:
    """
    工具注册表
    
    集中管理所有 Agent 工具实例，提供注册、查找、schema 生成能力。
    
    对应 pi-mono 的 createAllTools(cwd) 模式，
    注册表在初始化时接收 ToolContext 作为共享上下文。
    
    设计要点：
    - 非单例模式，允许不同 Agent 会话使用不同的注册表实例
    - 注册时检查名称唯一性，重复注册同名工具会覆盖并警告
    - get_all_openai_schemas() 的返回值可直接传给 ZhipuClient.chat(tools=...)
    """
    
    def __init__(self, context: Optional[ToolContext] = None):
        """
        初始化工具注册表
        
        Args:
            context: 工具执行上下文（可选，后续可通过 set_context 设置）
        """
        self._tools: Dict[str, BaseTool] = {}
        self._groups: Dict[str, Set[str]] = {}
        self._context = context
        self._logger = logging.getLogger(__name__)
    
    @property
    def context(self) -> Optional[ToolContext]:
        """获取当前工具上下文"""
        return self._context
    
    @context.setter
    def context(self, value: ToolContext) -> None:
        """设置工具上下文"""
        self._context = value
    
    # ============================================================
    # 注册 / 注销
    # ============================================================
    
    def register(self, tool: BaseTool, groups: Optional[List[str]] = None) -> None:
        """
        注册工具
        
        Args:
            tool: 工具实例（必须继承 BaseTool）
            groups: 工具所属分组列表（可选）
                    例如 ["file_ops"] 表示属于文件操作分组
        """
        name = tool.name
        
        if name in self._tools:
            self._logger.warning(
                f"Tool '{name}' already registered, overwriting with new instance"
            )
        
        self._tools[name] = tool
        
        # 注册到分组（复制一份，避免修改调用方传入的列表）
        actual_groups = list(groups) if groups else []
        # 所有工具自动加入 GROUP_ALL
        actual_groups.append(GROUP_ALL)
        
        for group in actual_groups:
            if group not in self._groups:
                self._groups[group] = set()
            self._groups[group].add(name)
        
        self._logger.debug(f"Registered tool: {name} (groups: {actual_groups})")
    
    def unregister(self, name: str) -> bool:
        """
        注销工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否成功注销（工具不存在时返回 False）
        """
        if name not in self._tools:
            return False
        
        del self._tools[name]
        
        # 从所有分组中移除
        for group_tools in self._groups.values():
            group_tools.discard(name)
        
        self._logger.debug(f"Unregistered tool: {name}")
        return True
    
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
    
    def has(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools
    
    def get_all(self) -> List[BaseTool]:
        """获取所有已注册的工具"""
        return list(self._tools.values())
    
    def get_names(self) -> List[str]:
        """获取所有已注册工具的名称"""
        return list(self._tools.keys())
    
    @property
    def count(self) -> int:
        """已注册工具数量"""
        return len(self._tools)
    
    # ============================================================
    # 分组查询
    # ============================================================
    
    def get_by_group(self, group: str) -> List[BaseTool]:
        """
        按分组获取工具列表
        
        Args:
            group: 分组名称（如 GROUP_FILE_OPS）
            
        Returns:
            该分组下的工具列表
        """
        tool_names = self._groups.get(group, set())
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_group_names(self) -> List[str]:
        """获取所有分组名称"""
        return list(self._groups.keys())
    
    # ============================================================
    # Schema 生成（供 LLM API 使用）
    # ============================================================
    
    def get_all_schemas(self) -> List[ToolSchema]:
        """
        获取所有已注册工具的 ToolSchema 列表
        
        Returns:
            ToolSchema 实例列表
        """
        return [tool.get_schema() for tool in self._tools.values()]
    
    def get_all_openai_schemas(self) -> List[Dict[str, Any]]:
        """
        获取所有已注册工具的 OpenAI Function Calling 格式 schema 列表
        
        返回值可直接传给 ZhipuClient.chat(tools=...) 参数。
        
        Returns:
            OpenAI tools 参数格式的字典列表
        """
        return [tool.get_openai_schema() for tool in self._tools.values()]
    
    def get_schemas_by_group(self, group: str) -> List[Dict[str, Any]]:
        """
        按分组获取 OpenAI Function Calling 格式 schema 列表
        
        Args:
            group: 分组名称
            
        Returns:
            该分组下的 OpenAI tools schema 列表
        """
        tools = self.get_by_group(group)
        return [tool.get_openai_schema() for tool in tools]
    
    # ============================================================
    # 批量注册辅助
    # ============================================================
    
    def register_all(
        self,
        tools: List[BaseTool],
        groups: Optional[List[str]] = None,
    ) -> None:
        """
        批量注册工具
        
        Args:
            tools: 工具实例列表
            groups: 共享的分组列表（可选）
        """
        for tool in tools:
            self.register(tool, groups=list(groups) if groups else None)
    
    # ============================================================
    # 调试 / 信息
    # ============================================================
    
    def summary(self) -> str:
        """
        生成注册表摘要（用于日志和调试）
        
        Returns:
            人类可读的摘要字符串
        """
        lines = [f"ToolRegistry: {self.count} tools registered"]
        for name, tool in self._tools.items():
            lines.append(f"  - {name}: {tool.description[:60]}...")
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        tool_names = ", ".join(self._tools.keys())
        return f"<ToolRegistry(tools=[{tool_names}])>"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ToolRegistry",
    "GROUP_FILE_OPS",
    "GROUP_SEARCH",
    "GROUP_ALL",
]
