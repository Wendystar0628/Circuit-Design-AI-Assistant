# Circuit Design AI - Main Package
"""
电路AI设计助理 - 基于LLM的电路设计自动化工具

Architecture:
- presentation/    表示层 (UI面板、对话框)
- application/     应用层 (工作流编排、Workers)
- domain/          领域层 (设计、LLM、仿真、知识检索)
- infrastructure/  基础设施层 (配置、持久化、适配器)
- shared/          共享内核层 (ServiceLocator、EventBus)

三层状态分离架构：
- Layer 1: UIState (presentation/ui_state.py) - 纯 UI 状态
- Layer 2: SessionState (application/session_state.py) - GraphState 的只读投影
- Layer 3: GraphState (application/graph/state.py) - LangGraph 工作流的唯一真理来源
"""

__version__ = "0.1.0"
__author__ = "Circuit Design AI Team"
