# Workers Module (Deprecated - Empty)
"""
⚠️ 本模块已废弃并清空

所有异步任务现在通过 AsyncTaskRegistry + 协程模式实现：
- LLM 任务：使用 LLMExecutor.generate_stream() + AsyncTaskRegistry
- 文件监听：使用 application/tasks/file_watch_task.py（待实现）
- 其他任务：直接使用 AsyncTaskRegistry.submit() 提交协程

新代码请参考：
- shared/async_task_registry.py - 异步任务注册表
- domain/llm/llm_executor.py - LLM 调用执行器
- application/tasks/__init__.py - 任务模块

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
"""

# 本模块不再导出任何内容
__all__ = []
