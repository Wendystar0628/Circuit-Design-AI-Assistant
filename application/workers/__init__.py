# Workers
"""
后台线程模块

⚠️ 废弃警告 (Deprecated)：
本模块中的 Worker 类已废弃，保留仅用于向后兼容。
新代码应使用 AsyncTaskRegistry + 协程模式：

    # 推荐的新模式
    from shared.async_task_registry import AsyncTaskRegistry, TASK_LLM
    from domain.llm.llm_executor import LLMExecutor
    
    async def llm_task():
        executor = LLMExecutor()
        async for chunk in executor.generate_stream(messages, model):
            event_bus.publish_throttled(EVENT_LLM_CHUNK, {"chunk": chunk})
        return executor.get_result()
    
    registry = AsyncTaskRegistry()
    await registry.submit(TASK_LLM, task_id, llm_task())

迁移指南：
- LLMWorker → LLMExecutor.generate_stream() + AsyncTaskRegistry
- FileWatcherWorker → application/tasks/file_watch_task.py (待实现)
- 其他 Worker → 直接使用 AsyncTaskRegistry.submit() 提交协程

原设计说明（已废弃）：
- Workers 是应用层的异步执行器，负责在后台线程中执行耗时任务
- 调用领域层服务完成具体业务逻辑，属于应用层的"执行臂"
- 由 shared/worker_manager.py 统一调度和管理生命周期

目录结构：
- base_worker.py: Worker 基类，定义统一信号接口（已废弃）
- llm_worker.py: LLM 调用 Worker（已废弃，使用 LLMExecutor）
- file_watcher_worker.py: 文件监听 Worker（已废弃）
- simulation_worker.py: 仿真执行 Worker（阶段四实现）
- rag_worker.py: RAG 检索 Worker（阶段四实现）

线程安全要求：
- Worker 信号必须使用 pyqtSignal 定义，通过信号槽与 UI 通信
- do_work() 中禁止直接调用 UI 组件方法
- 数据传递只能通过信号参数，禁止共享可变对象
"""

import warnings

# 发出废弃警告
warnings.warn(
    "application.workers 模块已废弃，请使用 AsyncTaskRegistry + 协程模式。"
    "参见 shared/async_task_registry.py 和 domain/llm/llm_executor.py",
    DeprecationWarning,
    stacklevel=2
)

# 基类导出
from application.workers.base_worker import BaseWorker

# 阶段三 Worker 导出
from application.workers.llm_worker import LLMWorker, LLMRequest, LLMResult, WORKER_TYPE_LLM
from application.workers.file_watcher_worker import (
    FileWatcherWorker,
    WORKER_TYPE_FILE_WATCHER,
    WATCHED_EXTENSIONS,
    IGNORED_DIRS,
)

# 阶段四实现后导出
# from application.workers.simulation_worker import SimulationWorker
# from application.workers.rag_worker import RAGWorker

__all__ = [
    # 基类
    "BaseWorker",
    # LLM Worker
    "LLMWorker",
    "LLMRequest",
    "LLMResult",
    "WORKER_TYPE_LLM",
    # File Watcher Worker
    "FileWatcherWorker",
    "WORKER_TYPE_FILE_WATCHER",
    "WATCHED_EXTENSIONS",
    "IGNORED_DIRS",
    # 阶段四实现后导出
    # "SimulationWorker",
    # "RAGWorker",
]
