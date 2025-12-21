# Application Layer
"""
应用层 - 启动引导、工作流编排、LangGraph、Workers、工具执行

包含：
- bootstrap.py: 应用启动引导器（初始化编排）
- session_state.py: 会话状态容器（GraphState 的只读投影）
- graph_state_projector.py: GraphState 投影器（自动投影到 SessionState）
- design_workflow.py: 核心编排器
- tool_executor.py: LLM工具调用执行
- project_service.py: 项目管理服务
- snapshot_service.py: 全量快照服务
- workers/: 后台线程（LLM、仿真、RAG、文件监听）
- graph/: LangGraph编排（状态、节点、边、构建器）

三层状态分离架构：
- Layer 1: UIState (Presentation) - 纯 UI 状态
- Layer 2: SessionState (Application) - GraphState 的只读投影
- Layer 3: GraphState (Domain) - LangGraph 工作流的唯一真理来源
"""

from application.bootstrap import run
from application.session_state import (
    SessionState,
    SessionStateChangeHandler,
    SESSION_PROJECT_ROOT,
    SESSION_ID,
    SESSION_WORK_MODE,
    SESSION_WORKFLOW_LOCKED,
    SESSION_CURRENT_NODE,
    SESSION_ITERATION_COUNT,
    SESSION_CHECKPOINT_COUNT,
    SESSION_ACTIVE_CIRCUIT_FILE,
)
from application.graph_state_projector import (
    GraphStateProjector,
    is_workflow_locked,
    UNLOCKED_NODES,
)
from application.project_service import (
    ProjectService,
    ProjectStatus,
    ProjectInfo,
)
from application.snapshot_service import (
    SnapshotService,
    SnapshotInfo,
)
from application.graph import (
    GraphState,
    WorkMode,
    create_initial_state,
)

__all__ = [
    "run",
    # 会话状态
    "SessionState",
    "SessionStateChangeHandler",
    "SESSION_PROJECT_ROOT",
    "SESSION_ID",
    "SESSION_WORK_MODE",
    "SESSION_WORKFLOW_LOCKED",
    "SESSION_CURRENT_NODE",
    "SESSION_ITERATION_COUNT",
    "SESSION_CHECKPOINT_COUNT",
    "SESSION_ACTIVE_CIRCUIT_FILE",
    # GraphState 投影器
    "GraphStateProjector",
    "is_workflow_locked",
    "UNLOCKED_NODES",
    # 项目服务
    "ProjectService",
    "ProjectStatus",
    "ProjectInfo",
    # 快照服务
    "SnapshotService",
    "SnapshotInfo",
    # GraphState
    "GraphState",
    "WorkMode",
    "create_initial_state",
]
