# Workers
"""
后台线程模块

设计说明：
- Workers 是应用层的异步执行器，负责在后台线程中执行耗时任务
- 调用领域层服务完成具体业务逻辑，属于应用层的"执行臂"
- 由 shared/worker_manager.py 统一调度和管理生命周期

目录结构：
- base_worker.py: Worker 基类，定义统一信号接口（阶段三实现）
- llm_worker.py: LLM 调用 Worker（阶段三实现）
- file_watcher_worker.py: 文件监听 Worker（阶段三实现）
- simulation_worker.py: 仿真执行 Worker（阶段四实现）
- rag_worker.py: RAG 检索 Worker（阶段四实现）

线程安全要求：
- Worker 信号必须使用 pyqtSignal 定义，通过信号槽与 UI 通信
- do_work() 中禁止直接调用 UI 组件方法
- 数据传递只能通过信号参数，禁止共享可变对象
"""

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
