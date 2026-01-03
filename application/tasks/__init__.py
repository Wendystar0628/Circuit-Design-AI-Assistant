# Application Tasks
"""
应用层任务模块

设计说明：
本模块包含应用层任务实现，分为两类：

1. 协程任务（通过 AsyncTaskRegistry 管理）：
   - LLM 生成任务
   - RAG 索引/检索任务
   - 仿真任务
   - 代码索引任务

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

使用示例：
    # 协程任务
    from shared.async_task_registry import AsyncTaskRegistry, TASK_LLM
    
    async def llm_task():
        executor = LLMExecutor()
        async for chunk in executor.generate_stream(messages, model):
            event_bus.publish_throttled(EVENT_LLM_CHUNK, {"chunk": chunk})
        return executor.get_result()
    
    registry = AsyncTaskRegistry()
    await registry.submit(TASK_LLM, task_id, llm_task())
    
    # 文件监听任务
    from application.tasks import FileWatchTask
    
    file_watcher = FileWatchTask()
    file_watcher.start_watching("/path/to/project")
"""

# 任务类型常量从 async_task_registry 导入
from shared.async_task_registry import (
    TASK_LLM,
    TASK_RAG_INDEX,
    TASK_RAG_SEARCH,
    TASK_FILE_WATCH,
    TASK_SIMULATION,
    TASK_SCHEMATIC,
    TASK_CODE_INDEX,
)

# 文件监听任务
from application.tasks.file_watch_task import (
    FileWatchTask,
    FileWatchReceiver,
    CircuitFileEventHandler,
    WATCHED_EXTENSIONS,
    IGNORED_DIRS,
    IGNORED_EXTENSIONS,
    DEBOUNCE_INTERVAL_MS,
)

__all__ = [
    # 任务类型常量
    "TASK_LLM",
    "TASK_RAG_INDEX",
    "TASK_RAG_SEARCH",
    "TASK_FILE_WATCH",
    "TASK_SIMULATION",
    "TASK_SCHEMATIC",
    "TASK_CODE_INDEX",
    # 文件监听任务
    "FileWatchTask",
    "FileWatchReceiver",
    "CircuitFileEventHandler",
    "WATCHED_EXTENSIONS",
    "IGNORED_DIRS",
    "IGNORED_EXTENSIONS",
    "DEBOUNCE_INTERVAL_MS",
]
