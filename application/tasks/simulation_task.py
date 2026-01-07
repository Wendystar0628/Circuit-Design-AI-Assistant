# Simulation Task - 仿真任务异步执行
"""
仿真任务 - 封装仿真执行的异步逻辑

职责：
- 在后台线程执行仿真，避免阻塞 UI
- 通过信号通知仿真进度和完成状态
- 支持取消操作

设计原则：
- 使用 QThread 实现后台执行
- 通过 Qt 信号机制与 UI 层通信
- 与 SimulationService 解耦，仅负责异步调度

使用示例：
    from application.tasks.simulation_task import SimulationTask
    
    task = SimulationTask()
    task.simulation_started.connect(on_started)
    task.simulation_progress.connect(on_progress)
    task.simulation_completed.connect(on_completed)
    task.simulation_error.connect(on_error)
    
    task.run_auto_detect(project_root)
    # 或
    task.run_file(file_path, project_root)
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class SimulationWorker(QObject):
    """
    仿真工作线程
    
    在独立线程中执行仿真，通过信号通知结果。
    """
    
    # 信号定义
    started = pyqtSignal(str)  # file_path
    progress = pyqtSignal(float, str)  # progress (0-1), message
    completed = pyqtSignal(object)  # SimulationResult
    error = pyqtSignal(str, str)  # error_type, error_message
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._cancelled = False
        self._file_path: Optional[str] = None
        self._project_root: Optional[str] = None
        self._analysis_config: Optional[Dict[str, Any]] = None
        self._mode: str = "auto"  # "auto" or "file"
    
    def setup_auto_detect(
        self,
        project_root: str,
        analysis_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """设置自动检测模式参数"""
        self._mode = "auto"
        self._project_root = project_root
        self._analysis_config = analysis_config
        self._file_path = None
    
    def setup_file(
        self,
        file_path: str,
        project_root: str,
        analysis_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """设置指定文件模式参数"""
        self._mode = "file"
        self._file_path = file_path
        self._project_root = project_root
        self._analysis_config = analysis_config
    
    def cancel(self) -> None:
        """请求取消仿真"""
        self._cancelled = True
    
    def run(self) -> None:
        """执行仿真（在工作线程中调用）"""
        self._cancelled = False
        
        try:
            from domain.services.simulation_service import SimulationService
            
            service = SimulationService()
            
            if self._mode == "auto":
                self._run_auto_detect(service)
            else:
                self._run_file(service)
                
        except Exception as e:
            self._logger.exception(f"仿真执行异常: {e}")
            self.error.emit("EXECUTION_ERROR", str(e))
    
    def _run_auto_detect(self, service: "SimulationService") -> None:
        """执行自动检测模式"""
        if not self._project_root:
            self.error.emit("INVALID_PARAM", "项目根目录未设置")
            return
        
        # 发送进度：开始检测
        self.progress.emit(0.1, "正在检测主电路...")
        
        if self._cancelled:
            return
        
        # 执行自动检测仿真
        result = service.run_with_auto_detect(
            project_path=self._project_root,
            analysis_config=self._analysis_config,
            on_progress=self._on_progress,
        )
        
        if self._cancelled:
            return
        
        # 发送完成信号
        if result.success:
            self.completed.emit(result)
        else:
            error_msg = ""
            if result.error:
                error_msg = str(result.error.message) if hasattr(result.error, 'message') else str(result.error)
            self.error.emit("SIMULATION_FAILED", error_msg)
    
    def _run_file(self, service: "SimulationService") -> None:
        """执行指定文件模式"""
        if not self._file_path:
            self.error.emit("INVALID_PARAM", "仿真文件未指定")
            return
        
        if not self._project_root:
            self.error.emit("INVALID_PARAM", "项目根目录未设置")
            return
        
        # 发送开始信号
        self.started.emit(self._file_path)
        self.progress.emit(0.1, f"正在仿真: {Path(self._file_path).name}")
        
        if self._cancelled:
            return
        
        # 执行仿真
        result = service.run_simulation(
            file_path=self._file_path,
            analysis_config=self._analysis_config,
            project_root=self._project_root,
            on_progress=self._on_progress,
        )
        
        if self._cancelled:
            return
        
        # 发送完成信号
        if result.success:
            self.completed.emit(result)
        else:
            error_msg = ""
            if result.error:
                error_msg = str(result.error.message) if hasattr(result.error, 'message') else str(result.error)
            self.error.emit("SIMULATION_FAILED", error_msg)
    
    def _on_progress(self, progress: float, message: str) -> None:
        """进度回调"""
        if not self._cancelled:
            # 映射进度到 0.1-0.9 范围（0.1 是开始，1.0 是完成）
            mapped_progress = 0.1 + progress * 0.8
            self.progress.emit(mapped_progress, message)


class SimulationTask(QObject):
    """
    仿真任务管理器
    
    管理仿真工作线程的生命周期，提供简洁的 API。
    """
    
    # 对外信号
    simulation_started = pyqtSignal(str)  # file_path
    simulation_progress = pyqtSignal(float, str)  # progress (0-1), message
    simulation_completed = pyqtSignal(object)  # SimulationResult
    simulation_error = pyqtSignal(str, str)  # error_type, error_message
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._thread: Optional[QThread] = None
        self._worker: Optional[SimulationWorker] = None
    
    @property
    def is_running(self) -> bool:
        """检查是否有仿真正在运行"""
        return self._thread is not None and self._thread.isRunning()
    
    def run_auto_detect(
        self,
        project_root: str,
        analysis_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        自动检测主电路并执行仿真
        
        Args:
            project_root: 项目根目录
            analysis_config: 仿真配置（可选）
            
        Returns:
            bool: 是否成功启动任务
        """
        if self.is_running:
            self._logger.warning("已有仿真任务正在运行")
            return False
        
        self._setup_worker()
        self._worker.setup_auto_detect(project_root, analysis_config)
        self._start_thread()
        return True
    
    def run_file(
        self,
        file_path: str,
        project_root: str,
        analysis_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        执行指定文件的仿真
        
        Args:
            file_path: 电路文件路径
            project_root: 项目根目录
            analysis_config: 仿真配置（可选）
            
        Returns:
            bool: 是否成功启动任务
        """
        if self.is_running:
            self._logger.warning("已有仿真任务正在运行")
            return False
        
        self._setup_worker()
        self._worker.setup_file(file_path, project_root, analysis_config)
        self._start_thread()
        return True
    
    def cancel(self) -> bool:
        """
        取消当前仿真
        
        Returns:
            bool: 是否成功发送取消请求
        """
        if not self.is_running:
            return False
        
        if self._worker:
            self._worker.cancel()
        return True
    
    def _setup_worker(self) -> None:
        """设置工作线程"""
        # 清理旧线程
        self._cleanup()
        
        # 创建新线程和工作对象
        self._thread = QThread()
        self._worker = SimulationWorker()
        self._worker.moveToThread(self._thread)
        
        # 连接信号
        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self.simulation_started.emit)
        self._worker.progress.connect(self.simulation_progress.emit)
        self._worker.completed.connect(self._on_completed)
        self._worker.error.connect(self._on_error)
    
    def _start_thread(self) -> None:
        """启动工作线程"""
        if self._thread:
            self._thread.start()
    
    def _on_completed(self, result: object) -> None:
        """仿真完成处理"""
        self.simulation_completed.emit(result)
        self._cleanup()
    
    def _on_error(self, error_type: str, error_message: str) -> None:
        """仿真错误处理"""
        self.simulation_error.emit(error_type, error_message)
        self._cleanup()
    
    def _cleanup(self) -> None:
        """清理线程资源"""
        if self._thread:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(3000)  # 等待最多 3 秒
            self._thread.deleteLater()
            self._thread = None
        
        if self._worker:
            self._worker.deleteLater()
            self._worker = None


__all__ = [
    "SimulationTask",
    "SimulationWorker",
]
