# Base Worker - Abstract Worker Class
"""
Worker 基类 - 所有后台 Worker 的统一接口和信号规范

职责：
- 定义所有后台 Worker 的统一接口
- 提供标准信号定义（progress、chunk、result、error、finished）
- 实现取消机制
- 自动转发信号到 EventBus

设计原则：
- 主线程只做界面更新，不进行业务计算
- 同类任务互斥排队，异类任务可并行
- 所有可能阻塞的操作设置超时

线程安全要求：
- 信号必须使用 pyqtSignal 定义为类属性
- do_work() 中禁止直接调用 UI 组件方法
- 数据传递只能通过信号参数，禁止共享可变对象
- 若需访问共享状态，必须使用 threading.Lock 保护

接口依赖原则：
- UI 层只依赖 BaseWorker 定义的信号接口，不依赖具体 Worker 子类
- 具体 Worker 子类可自由扩展，但必须实现基类定义的所有信号
- 通过 WorkerManager 获取 Worker 实例，不直接实例化具体子类

使用示例：
    class MyWorker(BaseWorker):
        def __init__(self, task_params):
            super().__init__()
            self._task_params = task_params
        
        def do_work(self):
            # 执行具体任务
            for i in range(100):
                if self.is_cancelled():
                    return
                # 处理逻辑...
                self.progress.emit(i, f"Processing {i}%")
            
            self.result.emit({"status": "success"})
"""

from abc import abstractmethod
from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal


# ============================================================
# 注意：不使用 ABC 作为基类
# ============================================================
# QThread 使用 sip.wrappertype 元类，ABC 使用 ABCMeta 元类
# 同时继承两者会导致元类冲突：
# "metaclass conflict: the metaclass of a derived class must be a 
#  (non-strict) subclass of the metaclasses of all its bases"
# 
# 解决方案：不继承 ABC，仅使用 @abstractmethod 装饰器
# @abstractmethod 装饰器本身不依赖 ABC 元类，可以独立使用
# 虽然不会在实例化时强制检查，但 IDE 和类型检查器仍会提示
# ============================================================


class BaseWorker(QThread):
    """
    Worker 基类 - 所有后台 Worker 的抽象基类
    
    所有后台任务 Worker 都必须继承此类并实现 do_work() 方法。
    基类提供统一的信号接口、取消机制和 EventBus 集成。
    
    信号说明：
    - progress(int, str): 进度更新（百分比 0-100，描述文本）
    - chunk(str): 流式数据块（用于 LLM 流式输出）
    - result(object): 任务完成结果
    - error(str, object): 错误信息（错误描述，异常对象）
    - finished_work(): 任务结束（无论成功失败）
    
    注意：QThread 已有 finished 信号，这里使用 finished_work 避免冲突
    """

    # ============================================================
    # 信号定义（类属性，所有实例共享信号类型）
    # ============================================================

    # 进度更新：(百分比 0-100, 描述文本)
    progress = pyqtSignal(int, str)

    # 流式数据块：用于 LLM 流式输出
    chunk = pyqtSignal(str)

    # 任务完成结果：任意对象
    result = pyqtSignal(object)

    # 错误信息：(错误描述, 异常对象)
    error = pyqtSignal(str, object)

    # 任务结束：无论成功失败都会触发
    finished_work = pyqtSignal()

    # ============================================================
    # 初始化
    # ============================================================

    def __init__(self, worker_type: str = "base"):
        """
        初始化 Worker
        
        Args:
            worker_type: Worker 类型标识，用于 EventBus 事件区分
        """
        super().__init__()
        
        # Worker 类型标识
        self._worker_type = worker_type
        
        # 取消标志（线程安全，bool 赋值是原子操作）
        self._is_cancelled = False
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 连接信号到 EventBus 转发
        self._connect_signals_to_event_bus()

    # ============================================================
    # 属性访问
    # ============================================================

    @property
    def worker_type(self) -> str:
        """获取 Worker 类型标识"""
        return self._worker_type

    @property
    def event_bus(self):
        """延迟获取 EventBus"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def logger(self):
        """延迟获取 Logger"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger(f"worker.{self._worker_type}")
            except Exception:
                pass
        return self._logger


    # ============================================================
    # 取消机制
    # ============================================================

    def cancel(self) -> None:
        """
        请求取消任务
        
        设置取消标志，子类应在 do_work() 中定期检查 is_cancelled()。
        注意：这是协作式取消，不会强制终止线程。
        """
        self._is_cancelled = True
        if self.logger:
            self.logger.info(f"Worker '{self._worker_type}' cancel requested")

    def is_cancelled(self) -> bool:
        """
        检查是否已请求取消
        
        子类应在 do_work() 的安全点（如循环开始、IO 操作前）调用此方法，
        若返回 True 则应尽快清理并退出。
        
        Returns:
            bool: 是否已请求取消
        """
        return self._is_cancelled

    def reset_cancel(self) -> None:
        """
        重置取消标志
        
        在重新启动 Worker 前调用，确保取消状态被清除。
        """
        self._is_cancelled = False

    # ============================================================
    # QThread 运行入口
    # ============================================================

    def run(self) -> None:
        """
        QThread 运行入口（禁止子类覆盖）
        
        此方法在新线程中执行，负责：
        1. 重置取消标志
        2. 调用子类的 do_work() 方法
        3. 捕获异常并发送 error 信号
        4. 无论成功失败都发送 finished_work 信号
        """
        # 重置取消标志
        self._is_cancelled = False
        
        if self.logger:
            self.logger.debug(f"Worker '{self._worker_type}' started")
        
        try:
            # 调用子类实现的具体任务逻辑
            self.do_work()
            
        except Exception as e:
            # 捕获所有异常，发送 error 信号
            error_msg = f"Worker '{self._worker_type}' failed: {str(e)}"
            if self.logger:
                self.logger.error(error_msg, exc_info=True)
            
            # 发送错误信号
            self.error.emit(error_msg, e)
            
        finally:
            # 无论成功失败都发送 finished_work 信号
            if self.logger:
                self.logger.debug(f"Worker '{self._worker_type}' finished")
            
            self.finished_work.emit()

    # ============================================================
    # 抽象方法（子类必须实现）
    # ============================================================

    @abstractmethod
    def do_work(self) -> None:
        """
        执行具体任务逻辑（子类必须实现）
        
        实现要求：
        1. 定期调用 is_cancelled() 检查取消状态
        2. 通过 progress.emit() 报告进度
        3. 通过 chunk.emit() 发送流式数据（如适用）
        4. 通过 result.emit() 发送最终结果
        5. 异常会被 run() 捕获并转换为 error 信号
        
        线程安全要求：
        - 禁止直接调用 UI 组件方法
        - 数据传递只能通过信号参数
        - 若需访问共享状态，必须使用 threading.Lock 保护
        
        示例：
            def do_work(self):
                for i in range(100):
                    if self.is_cancelled():
                        return
                    # 处理逻辑...
                    self.progress.emit(i, f"Processing {i}%")
                
                self.result.emit({"status": "success"})
        """
        pass


    # ============================================================
    # EventBus 集成
    # ============================================================

    def _connect_signals_to_event_bus(self) -> None:
        """
        连接信号到 EventBus 转发
        
        将 Worker 信号自动转发到 EventBus，使其他组件可以订阅 Worker 事件。
        转发时自动切换到主线程（EventBus.publish 内部处理）。
        """
        # 进度信号 → EVENT_WORKER_PROGRESS
        self.progress.connect(self._on_progress)
        
        # 结果信号 → EVENT_WORKER_COMPLETE
        self.result.connect(self._on_result)
        
        # 错误信号 → EVENT_WORKER_ERROR
        self.error.connect(self._on_error)

    def _on_progress(self, percent: int, description: str) -> None:
        """进度信号转发到 EventBus"""
        if self.event_bus:
            from shared.event_types import EVENT_WORKER_PROGRESS
            self.event_bus.publish(
                EVENT_WORKER_PROGRESS,
                data={
                    "worker_type": self._worker_type,
                    "percent": percent,
                    "description": description,
                },
                source=f"worker.{self._worker_type}"
            )

    def _on_result(self, result_data: Any) -> None:
        """结果信号转发到 EventBus"""
        if self.event_bus:
            from shared.event_types import EVENT_WORKER_COMPLETE
            self.event_bus.publish(
                EVENT_WORKER_COMPLETE,
                data={
                    "worker_type": self._worker_type,
                    "result": result_data,
                },
                source=f"worker.{self._worker_type}"
            )

    def _on_error(self, error_msg: str, exception: Any) -> None:
        """错误信号转发到 EventBus"""
        if self.event_bus:
            from shared.event_types import EVENT_WORKER_ERROR
            self.event_bus.publish(
                EVENT_WORKER_ERROR,
                data={
                    "worker_type": self._worker_type,
                    "error_msg": error_msg,
                    "exception": exception,
                },
                source=f"worker.{self._worker_type}"
            )

    # ============================================================
    # 辅助方法
    # ============================================================

    def emit_progress(self, percent: int, description: str = "") -> None:
        """
        发送进度更新（便捷方法）
        
        Args:
            percent: 进度百分比（0-100）
            description: 进度描述文本
        """
        self.progress.emit(percent, description)

    def emit_chunk(self, chunk_data: str) -> None:
        """
        发送流式数据块（便捷方法）
        
        Args:
            chunk_data: 数据块内容
        """
        self.chunk.emit(chunk_data)

    def emit_result(self, result_data: Any) -> None:
        """
        发送任务结果（便捷方法）
        
        Args:
            result_data: 结果数据
        """
        self.result.emit(result_data)

    def emit_error(self, error_msg: str, exception: Optional[Exception] = None) -> None:
        """
        发送错误信息（便捷方法）
        
        Args:
            error_msg: 错误描述
            exception: 异常对象（可选）
        """
        self.error.emit(error_msg, exception)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "BaseWorker",
]
