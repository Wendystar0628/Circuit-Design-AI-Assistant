# Agent Tools - Agent 具体工具实现包
"""
Agent 工具实现模块

提供具体的 Agent 工具：
- read_file      : 读取文件内容（支持行号范围、截断）
- patch_file     : 搜索替换式编辑
- rewrite_file   : 整体写入文件
- grep_search    : 按正则/字面模式搜索文件内容
- find_files     : 按 glob 模式查找文件
- list_directory : 列出目录内容
- rag_search     : 项目索引库检索
- web_search     : Web 检索
- run_simulation : 对项目内任意电路发起一次仿真并返回紧凑摘要
- read_metrics   : 读取一次仿真的 .MEASURE 指标表（Step 17）
- read_waveform  : 读取一次仿真波形的紧凑统计 + 锚点（Step 18）
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
from domain.llm.agent.tools.read_waveform import ReadWaveformTool


__all__ = [
    "ReadFileTool",
    "PatchFileTool",
    "RewriteFileTool",
    "GrepSearchTool",
    "FindFilesTool",
    "ListDirectoryTool",
    "RAGSearchTool",
    "WebSearchTool",
    "RunSimulationTool",
    "ReadMetricsTool",
    "ReadWaveformTool",
]
