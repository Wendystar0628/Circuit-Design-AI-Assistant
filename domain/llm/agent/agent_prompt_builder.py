# Agent Prompt Builder - Agent 系统提示词构建器
"""
Agent 系统提示词构建器

职责：
- 构建 Agent 模式下的完整系统提示词
- 从 ToolRegistry 动态获取工具列表和使用指南
- 注入项目上下文（工作目录、当前日期、当前文件）

参考来源：
- pi-mono: packages/coding-agent/src/core/system-prompt.ts

架构位置：
- 被 LLMExecutor.execute_agent() 调用
- 依赖 ToolRegistry 获取工具信息
- 完全自包含
"""

from datetime import date
from typing import Optional

from domain.llm.agent.tool_registry import ToolRegistry


# ============================================================
# 提示词构建
# ============================================================

def build_agent_system_prompt(
    registry: ToolRegistry,
    project_root: str,
    current_file: Optional[str] = None,
) -> str:
    """
    构建 Agent 模式的完整系统提示词

    对照 pi-mono system-prompt.ts buildSystemPrompt() 第 127-165 行。
    完全自包含。

    结构（与 pi-mono 一致）：
    1. 可用工具列表（从 ToolRegistry 动态生成）
    2. 使用指南（从工具的 promptGuidelines 汇总 + 通用指南）
    3. 项目上下文（工作目录、日期、当前文件）

    RAG 检索结果统一由 ContextRetriever 步骤 5.5 注入，
    不再在此处单独处理。

    LLM 的角色身份由 API 的 tools 参数隐式传达，
    不需要在 system prompt 里额外声明“你是xxx助手”。

    Args:
        registry: 已注册工具的注册表
        project_root: 项目根目录绝对路径
        current_file: 当前编辑器打开的文件路径（可选）

    Returns:
        完整的系统提示词字符串
    """
    sections = []

    # ---- 1. 可用工具列表 ----
    tools_section = _build_tools_section(registry)
    if tools_section:
        sections.append(tools_section)

    # ---- 2. 使用指南 ----
    guidelines_section = _build_guidelines_section(registry)
    if guidelines_section:
        sections.append(guidelines_section)

    # ---- 3. 项目上下文 ----
    sections.append(_build_context_section(project_root, current_file))

    return "\n\n".join(sections)


# ============================================================
# 内部构建函数
# ============================================================

def _build_tools_section(registry: ToolRegistry) -> str:
    """
    构建可用工具列表（对照 system-prompt.ts 第 85-88 行）

    格式：
        Available tools:
        - read_file: 读取文件内容，支持行号范围
        - patch_file: 搜索替换式精确编辑
        - rewrite_file: 创建或完整覆盖文件
    """
    tools = registry.get_all()
    if not tools:
        return ""

    lines = ["Available tools:"]
    for tool in tools:
        snippet = tool.prompt_snippet or tool.description[:80]
        lines.append(f"- {tool.name}: {snippet}")

    return "\n".join(lines)


def _build_guidelines_section(registry: ToolRegistry) -> str:
    """
    构建使用指南（对照 system-prompt.ts 第 90-125 行）

    从每个工具的 promptGuidelines 汇总，加上通用指南，去重。
    """
    seen = set()
    guidelines = []

    def _add(g: str) -> None:
        normalized = g.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            guidelines.append(normalized)

    # 从工具收集
    for tool in registry.get_all():
        if tool.prompt_guidelines:
            for g in tool.prompt_guidelines:
                _add(g)

    # 通用指南（对照开发方案中的"使用指南"列表）
    _add(
        "Use rewrite_file for new files or small files; "
        "use patch_file for surgical edits to large existing files."
    )
    _add(
        "Make one change at a time, then use read_file to verify the result."
    )
    _add(
        "SPICE files (.cir/.sp/.spice) use specific syntax; "
        "preserve comments and formatting."
    )
    _add("Show file paths clearly when working with files.")
    _add("Be concise in your responses.")

    if not guidelines:
        return ""

    lines = ["Guidelines:"]
    for g in guidelines:
        lines.append(f"- {g}")

    return "\n".join(lines)


def _build_context_section(
    project_root: str,
    current_file: Optional[str] = None,
) -> str:
    """
    构建项目上下文（对照 system-prompt.ts 第 163-165 行）
    """
    lines = [
        f"Current date: {date.today().isoformat()}",
        f"Working directory: {project_root.replace(chr(92), '/')}",
    ]
    if current_file:
        lines.append(f"Current file: {current_file}")

    return "\n".join(lines)



# ============================================================
# 模块导出
# ============================================================

__all__ = ["build_agent_system_prompt"]
