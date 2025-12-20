# Domain Services Layer
"""
领域服务层 - 无状态纯函数式服务

设计原则：
- 领域服务是纯函数式的"搬运工"
- 输入 → 处理 → 输出到文件 → 返回路径/摘要
- 不持有任何内存状态
- 所有业务数据存储在文件系统中

包含：
- design_service: 设计目标读写服务
- simulation_service: 仿真执行服务（阶段四实现）
- context_service: 对话历史读写服务（阶段三实现）
- rag_service: RAG 检索服务（阶段五实现）
- iteration_history_service: 迭代历史视图服务（从 SqliteSaver 查询）
"""

from domain.services.design_service import (
    save_design_goals,
    load_design_goals,
    get_goals_summary,
    validate_design_goals,
)

from domain.services.simulation_service import (
    run_simulation,
    load_sim_result,
    extract_metrics,
    get_sim_result_path,
)

from domain.services.context_service import (
    save_messages,
    load_messages,
    append_message,
    get_recent_messages,
)

from domain.services.rag_service import (
    retrieve,
    get_index_status,
)

from domain.services.iteration_history_service import (
    IterationRecord,
    get_iteration_history,
    get_iteration_detail,
    get_latest_iteration,
)


__all__ = [
    # Design Service
    "save_design_goals",
    "load_design_goals",
    "get_goals_summary",
    "validate_design_goals",
    # Simulation Service
    "run_simulation",
    "load_sim_result",
    "extract_metrics",
    "get_sim_result_path",
    # Context Service
    "save_messages",
    "load_messages",
    "append_message",
    "get_recent_messages",
    # RAG Service
    "retrieve",
    "get_index_status",
    # Iteration History Service
    "IterationRecord",
    "get_iteration_history",
    "get_iteration_detail",
    "get_latest_iteration",
]
