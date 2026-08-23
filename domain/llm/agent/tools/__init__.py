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
- run_simulation : 对显式项目电路发起仿真并返回 exact result_path
- read_metrics   : 按 exact result_path 读取结构化 .MEASURE 值与单位
- read_output_log: 按 exact result_path 读取结构化诊断或原始仿真输出
- read_op_result : 按 exact result_path 读取结构化 .op 工作点数据
- read_signals   : 按 exact result_path 读取权威 SimulationResult.data 的
                   描述性统计与锚点；不读取 UI chart/PNG/显示选择派生物
"""

from domain.llm.agent.tools.read_file import ReadFileTool
from domain.llm.agent.tools.patch_file import PatchFileTool
from domain.llm.agent.tools.rewrite_file import RewriteFileTool
from domain.llm.agent.tools.grep_search import GrepSearchTool
from domain.llm.agent.tools.find_files import FindFilesTool
from domain.llm.agent.tools.list_directory import ListDirectoryTool
from domain.llm.agent.tools.rag_search import RAGSearchTool
from domain.llm.agent.tools.run_simulation import RunSimulationTool
from domain.llm.agent.tools.read_metrics import ReadMetricsTool
from domain.llm.agent.tools.read_output_log import ReadOutputLogTool
from domain.llm.agent.tools.read_op_result import ReadOpResultTool
from domain.llm.agent.tools.read_signals import ReadSignalsTool


__all__ = [
    "ReadFileTool",
    "PatchFileTool",
    "RewriteFileTool",
    "GrepSearchTool",
    "FindFilesTool",
    "ListDirectoryTool",
    "RAGSearchTool",
    "RunSimulationTool",
    "ReadMetricsTool",
    "ReadOutputLogTool",
    "ReadOpResultTool",
    "ReadSignalsTool",
]
