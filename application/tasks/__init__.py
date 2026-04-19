# Application Tasks
"""
应用层任务模块

设计说明：
本模块只保留**非仿真**类型的长期运行任务。仿真任务已经统一
由 :class:`domain.services.simulation_job_manager.SimulationJobManager`
接管——它是仓库内唯一的仿真提交 / 查询 / 取消入口，不再需要
在 application/tasks/ 下重复一套 QThread 异步壳。

当前内容：
- file_watch_task.py: 文件监听任务（watchdog 线程管理）

架构原则：
- 长期运行任务通过 ServiceLocator 注册为单例服务
- 信号通过 EventBus.publish_throttled() 发送，避免高频事件风暴
- 取消操作通过任务自身的 stop 方法执行
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
]
