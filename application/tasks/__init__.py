# Application Tasks
"""
应用层任务模块

设计说明：
本模块包含基于 AsyncTaskRegistry 的任务实现。
所有 I/O 密集型任务通过协程提交到 AsyncTaskRegistry 执行。

架构原则：
- 任务逻辑直接写在领域服务或执行器中（如 LLMExecutor）
- 通过 AsyncTaskRegistry.submit() 提交协程
- 信号通过 EventBus.publish_throttled() 发送，避免高频事件风暴
- 取消操作通过 AsyncTaskRegistry.cancel() 执行

目录结构：
- file_watch_task.py: 文件监听任务（3.1.2 实现）
- 其他任务按需添加

使用示例：
    from shared.async_task_registry import AsyncTaskRegistry, TASK_LLM
    from domain.llm.llm_executor import LLMExecutor
    
    async def llm_task():
        executor = LLMExecutor()
        async for chunk in executor.generate_stream(messages, model):
            event_bus.publish_throttled(EVENT_LLM_CHUNK, {"chunk": chunk})
        return executor.get_result()
    
    registry = AsyncTaskRegistry()
    await registry.submit(TASK_LLM, task_id, llm_task())

与旧 Worker 模块的关系：
- application/workers/ 目录下的 Worker 类已标记为废弃
- 新代码应使用本模块的任务模式
- 旧 Worker 保留用于向后兼容，但不再维护
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

__all__ = [
    # 任务类型常量
    "TASK_LLM",
    "TASK_RAG_INDEX",
    "TASK_RAG_SEARCH",
    "TASK_FILE_WATCH",
    "TASK_SIMULATION",
    "TASK_SCHEMATIC",
    "TASK_CODE_INDEX",
]
