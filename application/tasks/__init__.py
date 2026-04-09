# Application Tasks
"""
应用层任务模块

设计说明：
本模块包含应用层任务实现，分为两类：

1. 协程任务（通过 AsyncTaskRegistry 管理）：
   - RAG 索引/检索任务（Embedding + ChromaDB）
   - 仿真任务

2. 长期运行任务（独立线程管理）：
   - 文件监听任务（使用 watchdog 库）

架构原则：
- 协程任务通过 AsyncTaskRegistry.submit() 提交
- 长期运行任务通过 ServiceLocator 注册为单例服务
- 信号通过 EventBus.publish_throttled() 发送，避免高频事件风暴
- 取消操作通过 AsyncTaskRegistry.cancel() 或任务自身的 stop 方法执行

目录结构：
- file_watch_task.py: 文件监听任务（watchdog 线程管理）
- 其他任务按需添加
"""

# 任务类型常量从 async_task_registry 导入
from shared.async_task_registry import (
    TASK_RAG_INDEX,
    TASK_RAG_QUERY,
    TASK_FILE_WATCH,
    TASK_SIMULATION,
    TASK_SCHEMATIC,
)

# 文件监听任务
from application.tasks.file_watch_task import (
    FileWatchTask,
    FileWatchReceiver,
    CircuitFileEventHandler,
    IGNORED_DIRS,
    IGNORED_EXTENSIONS,
    DEBOUNCE_INTERVAL_MS,
)

# 仿真任务
from application.tasks.simulation_task import (
    SimulationTask,
    SimulationWorker,
)

__all__ = [
    # 任务类型常量
    "TASK_RAG_INDEX",
    "TASK_RAG_QUERY",
    "TASK_FILE_WATCH",
    "TASK_SIMULATION",
    "TASK_SCHEMATIC",
    # 文件监听任务
    "FileWatchTask",
    "FileWatchReceiver",
    "CircuitFileEventHandler",
    "IGNORED_DIRS",
    "IGNORED_EXTENSIONS",
    "DEBOUNCE_INTERVAL_MS",
    # 仿真任务
    "SimulationTask",
    "SimulationWorker",
]
