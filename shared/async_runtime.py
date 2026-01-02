# Circuit Design AI - Async Runtime
"""
异步运行时初始化模块

职责：
- 初始化 qasync 融合事件循环（Qt + asyncio）
- 提供全局 asyncio 循环访问
- 管理异步运行时的生命周期

设计背景：
- PyQt6 使用 QEventLoop 作为主事件循环
- asyncio 使用独立的事件循环
- 传统方案（QThread + asyncio）存在跨线程同步风险：死锁、信号丢失、竞态条件
- qasync 将两个循环融合为一，所有异步操作在主线程协作式执行

架构图：
┌─────────────────────────────────────────────────────────────┐
│           融合事件循环 (QEventLoop + asyncio via qasync)     │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ UI 组件         │  │ async 协程      │  │ 信号槽      │ │
│  │ (QWidget)       │  │ (LLM调用等)     │  │ (pyqtSignal)│ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
│           ↑                   ↑                   ↑        │
│           └───────────────────┴───────────────────┘        │
│                    协作式调度（无跨线程）                    │
└─────────────────────────────────────────────────────────────┘

初始化顺序：Phase 0（应用启动最早期），在 bootstrap.py 中调用

使用方式：
    from shared.async_runtime import init_async_runtime, get_event_loop, shutdown
    
    # 在 bootstrap.py 中
    app = QApplication(sys.argv)
    loop = init_async_runtime(app)
    
    # 运行应用
    with loop:
        loop.run_forever()
    
    # 关闭时
    shutdown()
"""

import asyncio
import sys
from typing import Optional

from PyQt6.QtWidgets import QApplication

# 模块级变量
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_is_initialized: bool = False


def init_async_runtime(app: QApplication) -> asyncio.AbstractEventLoop:
    """
    初始化 qasync 融合事件循环
    
    将 asyncio 事件循环挂载到 Qt 的事件循环上，实现两者融合。
    此函数必须在 QApplication 创建后、进入事件循环前调用。
    
    Args:
        app: QApplication 实例
        
    Returns:
        asyncio.AbstractEventLoop: 融合后的事件循环
        
    Raises:
        RuntimeError: 如果已经初始化过
        ImportError: 如果 qasync 未安装
        
    Example:
        app = QApplication(sys.argv)
        loop = init_async_runtime(app)
        
        # 创建主窗口等...
        
        with loop:
            loop.run_forever()
    """
    global _event_loop, _is_initialized
    
    if _is_initialized:
        raise RuntimeError("异步运行时已经初始化，不能重复初始化")
    
    try:
        from qasync import QEventLoop
    except ImportError as e:
        raise ImportError(
            "qasync 库未安装，请运行: pip install qasync>=0.27.1"
        ) from e
    
    # 创建 qasync 融合事件循环
    # QEventLoop 继承自 asyncio.AbstractEventLoop，同时集成 Qt 事件处理
    loop = QEventLoop(app)
    
    # 设置为全局默认事件循环
    asyncio.set_event_loop(loop)
    
    # 保存引用
    _event_loop = loop
    _is_initialized = True
    
    return loop


def get_event_loop() -> asyncio.AbstractEventLoop:
    """
    获取当前事件循环
    
    返回 qasync 融合事件循环。如果尚未初始化，返回 asyncio 默认循环。
    
    Returns:
        asyncio.AbstractEventLoop: 当前事件循环
        
    Note:
        推荐在 init_async_runtime() 调用后使用此函数。
        在初始化前调用会返回 asyncio 默认循环（可能不是融合循环）。
    """
    if _event_loop is not None:
        return _event_loop
    
    # 回退到 asyncio 默认循环
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


def is_initialized() -> bool:
    """
    检查异步运行时是否已初始化
    
    Returns:
        bool: True 表示已初始化
    """
    return _is_initialized


async def shutdown_async() -> None:
    """
    异步关闭运行时（内部使用）
    
    取消所有待处理的异步任务，清理异步生成器。
    """
    loop = get_event_loop()
    
    # 获取所有待处理的任务（排除当前任务）
    try:
        current_task = asyncio.current_task(loop)
    except RuntimeError:
        current_task = None
    
    pending_tasks = [
        task for task in asyncio.all_tasks(loop)
        if task is not current_task and not task.done()
    ]
    
    if pending_tasks:
        # 取消所有待处理任务
        for task in pending_tasks:
            task.cancel()
        
        # 等待任务完成（带超时）
        try:
            await asyncio.wait(pending_tasks, timeout=5.0)
        except Exception:
            pass  # 忽略取消异常
    
    # 关闭异步生成器
    try:
        await loop.shutdown_asyncgens()
    except Exception:
        pass


def shutdown() -> None:
    """
    安全关闭异步运行时
    
    执行以下清理操作：
    1. 取消所有待处理的异步任务
    2. 运行 loop.shutdown_asyncgens() 清理异步生成器
    3. 重置模块状态
    
    此函数应在应用退出时调用。
    
    Note:
        此函数是同步的，内部会运行必要的异步清理操作。
        如果事件循环已关闭，会静默跳过清理。
    """
    global _event_loop, _is_initialized
    
    if not _is_initialized or _event_loop is None:
        return
    
    try:
        # 检查循环是否还在运行
        if _event_loop.is_running():
            # 如果循环还在运行，调度关闭任务
            _event_loop.create_task(shutdown_async())
        elif not _event_loop.is_closed():
            # 循环未运行但未关闭，同步执行清理
            _event_loop.run_until_complete(shutdown_async())
    except Exception:
        pass  # 关闭时的异常不应阻止程序退出
    finally:
        # 重置状态
        _event_loop = None
        _is_initialized = False


def run_coroutine_threadsafe(
    coro,
    callback=None,
    error_callback=None
) -> asyncio.Future:
    """
    从非主线程安全地提交协程到事件循环
    
    此函数用于从 QThreadPool 中的 QRunnable 或其他线程
    向主线程的事件循环提交异步任务。
    
    Args:
        coro: 要执行的协程
        callback: 成功回调函数，接收协程返回值
        error_callback: 错误回调函数，接收异常对象
        
    Returns:
        asyncio.Future: 可用于等待结果或取消任务
        
    Example:
        # 在 QRunnable 中
        async def fetch_data():
            return await some_async_operation()
        
        future = run_coroutine_threadsafe(
            fetch_data(),
            callback=lambda result: print(f"Got: {result}"),
            error_callback=lambda e: print(f"Error: {e}")
        )
    """
    loop = get_event_loop()
    
    if loop is None or loop.is_closed():
        raise RuntimeError("事件循环未初始化或已关闭")
    
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    
    if callback or error_callback:
        def done_callback(fut):
            try:
                result = fut.result()
                if callback:
                    callback(result)
            except Exception as e:
                if error_callback:
                    error_callback(e)
        
        future.add_done_callback(done_callback)
    
    return future


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "init_async_runtime",
    "get_event_loop",
    "is_initialized",
    "shutdown",
    "run_coroutine_threadsafe",
]
