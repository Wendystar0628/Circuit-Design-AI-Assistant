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
- rag_service: RAG 语义检索服务（阶段五实现）
- iteration_history_service: 迭代历史视图服务（从 SqliteSaver 查询）
- snapshot_service: 全量快照服务（项目文件备份与恢复，线性快照栈）
- recovery_log_service: WAL 恢复日志服务（崩溃恢复）

搜索系统架构：
- UnifiedSearchService: 统一搜索门面（domain/search/）
- FileSearchService: 精确搜索引擎（infrastructure/file_intelligence/search/）
- RAGService: 语义搜索引擎（domain/services/rag_service.py）
"""

from domain.services.design_service import (
    save_design_goals,
    load_design_goals,
    get_goals_summary,
    validate_design_goals,
)

from domain.services.simulation_service import (
    SimulationService,
    SIM_RESULTS_DIR,
    LoadResult,
)

from domain.services.context_service import (
    save_messages,
    load_messages,
    append_message,
    get_recent_messages,
    get_message_count,
    list_sessions,
    delete_session,
    clear_messages,
    get_conversation_path,
    get_current_session_id,
    set_current_session_id,
    get_session_metadata,
    update_session_index,
    remove_from_session_index,
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

from domain.services.snapshot_service import (
    SnapshotInfo,
    create_snapshot,
    restore_snapshot,
    list_snapshots,
    delete_snapshot,
    cleanup_old_snapshots,
    get_previous_snapshot,
    pop_snapshot,
    generate_snapshot_id,
    parse_iteration_from_snapshot_id,
    # 异步方法（应用层接口）
    create_snapshot_async,
    restore_snapshot_async,
    list_snapshots_async,
    delete_snapshot_async,
    cleanup_old_snapshots_async,
)

from domain.services.recovery_log_service import (
    RecoveryLog,
    write_log as write_recovery_log,
    read_log as read_recovery_log,
    delete_log as delete_recovery_log,
    has_pending_recovery,
    update_phase as update_recovery_phase,
    create_undo_log,
)


__all__ = [
    # Design Service
    "save_design_goals",
    "load_design_goals",
    "get_goals_summary",
    "validate_design_goals",
    # Simulation Service
    "SimulationService",
    "SIM_RESULTS_DIR",
    "LoadResult",
    # Context Service
    "save_messages",
    "load_messages",
    "append_message",
    "get_recent_messages",
    "get_message_count",
    "list_sessions",
    "delete_session",
    "clear_messages",
    "get_conversation_path",
    "get_current_session_id",
    "set_current_session_id",
    "get_session_metadata",
    "update_session_index",
    "remove_from_session_index",
    # RAG Service
    "retrieve",
    "get_index_status",
    # Iteration History Service
    "IterationRecord",
    "get_iteration_history",
    "get_iteration_detail",
    "get_latest_iteration",
    # Snapshot Service (同步方法 - 底层接口)
    "SnapshotInfo",
    "create_snapshot",
    "restore_snapshot",
    "list_snapshots",
    "delete_snapshot",
    "cleanup_old_snapshots",
    "get_previous_snapshot",
    "pop_snapshot",
    "generate_snapshot_id",
    "parse_iteration_from_snapshot_id",
    # Snapshot Service (异步方法 - 应用层接口)
    "create_snapshot_async",
    "restore_snapshot_async",
    "list_snapshots_async",
    "delete_snapshot_async",
    "cleanup_old_snapshots_async",
    # Recovery Log Service
    "RecoveryLog",
    "write_recovery_log",
    "read_recovery_log",
    "delete_recovery_log",
    "has_pending_recovery",
    "update_recovery_phase",
    "create_undo_log",
]
