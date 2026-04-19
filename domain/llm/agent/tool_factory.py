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
        知识检索：rag_search, web_search
        仿真闭环：run_simulation

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
    from domain.llm.agent.tools.run_simulation import RunSimulationTool
    from domain.llm.agent.tools.read_metrics import ReadMetricsTool
    from domain.llm.agent.tools.read_output_log import ReadOutputLogTool
    from domain.llm.agent.tools.read_signals import ReadSignalsTool

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

    # ---- 仿真闭环：对项目内任意电路发起一次仿真，返回紧凑摘要 ----
    # 与 UI 的 Run 按钮共享 SimulationJobManager 通道，但通过
    # origin=AGENT_TOOL 与 UI_EDITOR 严格区分；tool 内部完全不触碰
    # presentation/* 层，UI 刷新由 EventBus 订阅自然完成。
    registry.register(RunSimulationTool())

    # ---- Artifact 读取工具：共享 Step 16 的解析链基座 ----
    # 每个工具各自专注一类 artifact 的格式化（metrics 表、信号摘要
    # 等），寻址逻辑集中在 SimulationArtifactReaderBase——见
    # ``tools/simulation_artifact_reader_base.py``。
    #
    # ``read_signals`` 是 agent 面对仿真信号的**唯一**入口，覆盖
    # raw_data 全量转储 + 具名 chart 两类 CSV。``waveforms/waveform.csv``
    # 因为列由 UI 勾选过滤产生，刻意不暴露给 agent——详见
    # ``tools/read_signals.py`` 顶部的架构说明。
    registry.register(ReadMetricsTool())
    registry.register(ReadOutputLogTool())
    registry.register(ReadSignalsTool())

    logger.debug(f"Tool factory created registry: {registry!r}")
    return registry


# ============================================================
# 模块导出
# ============================================================

__all__ = ["create_default_tools"]
