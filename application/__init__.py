# Application Layer
"""
应用层 - 启动引导、工作流编排、LangGraph、Workers、工具执行

包含：
- bootstrap.py: 应用启动引导器（初始化编排）
- design_workflow.py: 核心编排器
- tool_executor.py: LLM工具调用执行
- project_service.py: 项目管理服务
- workers/: 后台线程（LLM、仿真、RAG、文件监听）
- graph/: LangGraph编排（状态、节点、边、构建器）
"""

from application.bootstrap import run

__all__ = ["run"]
