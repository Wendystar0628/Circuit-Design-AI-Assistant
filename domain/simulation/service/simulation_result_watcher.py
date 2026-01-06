# Simulation Result Watcher - Monitor simulation result file changes
"""
仿真结果文件监控器

职责：
- 监控仿真结果目录的文件变化
- 过滤出 .circuit_ai/sim_results/ 目录下的 .json 文件
- 发布 EVENT_SIM_RESULT_FILE_CREATED 事件

设计原则：
- 订阅 EVENT_FILE_CHANGED 事件，过滤仿真结果文件
- 仅处理 created 类型的文件事件
- 防抖处理：同一文件在 500ms 内的多次事件合并为一次
- 与 FileWatchTask 配合，作为仿真结果加载的补充路径

生命周期：
- 在 EVENT_STATE_PROJECT_OPENED 时启动
- 在 EVENT_STATE_PROJECT_CLOSED 时停止

被调用方：
- SessionManager 或 MainWindow 负责生命周期管理

使用示例：
    from domain.simulation.service.simulation_result_watcher import (
        simulation_result_watcher
    )
    
    # 启动监控
    simulation_result_watcher.start("/path/to/project")
    
    # 停止监控
    simulation_result_watcher.stop()
"""

import logging
import time
from pathlib import Path
from typing import Dict, Optional, Set

from shared.event_types import (
    EVENT_FILE_CHANGED,
    EVENT_SIM_RESULT_FILE_CREATED,
    EVENT_STATE_PROJECT_OPENED,
    EVENT_STATE_PROJECT_CLOSED,
)

try:
    from shared.constants.paths import SIM_RESULTS_DIR
except ImportError:
    SIM_RESULTS_DIR = ".circuit_ai/sim_results"


# ============================================================
# 常量定义
# ============================================================

# 防抖间隔（秒）
DEBOUNCE_INTERVAL_SECONDS = 0.5

# 仿真结果文件扩展名
SIM_RESULT_EXTENSION = ".json"


# ============================================================
# SimulationResultWatcher - 仿真结果文件监控器
# ============================================================

class SimulationResultWatcher:
    """
    仿真结果文件监控器
    
    监控仿真结果目录的文件变化，过滤并发布结果文件创建事件。
    作为事件驱动加载的补充路径，覆盖事件丢失或跨进程场景。
    """
    
    def __init__(self):
        """初始化监控器"""
        self._logger = logging.getLogger(__name__)
        
        # 当前监控的项目根目录
        self._project_root: Optional[str] = None
        
        # 是否正在监控
        self._is_watching: bool = False
        
        # 防抖缓冲区：{file_path: last_event_time}
        self._debounce_buffer: Dict[str, float] = {}
        
        # 已处理的文件集合（避免重复发布）
        self._processed_files: Set[str] = set()
        
        # EventBus 引用（延迟获取）
        self._event_bus = None
        
        # 事件订阅 ID
        self._subscription_ids: list = []
    
    # ============================================================
    # 属性
    # ============================================================
    
    @property
    def is_watching(self) -> bool:
        """是否正在监控"""
        return self._is_watching
    
    @property
    def project_root(self) -> Optional[str]:
        """当前监控的项目根目录"""
        return self._project_root
    
    # ============================================================
    # 生命周期方法
    # ============================================================
    
    def start(self, project_root: str) -> bool:
        """
        开始监控指定项目
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            bool: 是否成功启动
        """
        if self._is_watching:
            self.stop()
        
        try:
            # 验证路径
            root_path = Path(project_root)
            if not root_path.exists():
                self._logger.error(f"Project root does not exist: {project_root}")
                return False
            
            self._project_root = str(root_path.resolve())
            
            # 订阅文件变更事件
            event_bus = self._get_event_bus()
            if event_bus:
                event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
                self._subscription_ids.append(
                    (EVENT_FILE_CHANGED, self._on_file_changed)
                )
            
            self._is_watching = True
            self._debounce_buffer.clear()
            self._processed_files.clear()
            
            self._logger.info(
                f"SimulationResultWatcher started for: {self._project_root}"
            )
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to start SimulationResultWatcher: {e}")
            self._project_root = None
            self._is_watching = False
            return False
    
    def stop(self) -> None:
        """停止监控"""
        if not self._is_watching:
            return
        
        try:
            # 取消事件订阅
            event_bus = self._get_event_bus()
            if event_bus:
                for event_type, handler in self._subscription_ids:
                    try:
                        event_bus.unsubscribe(event_type, handler)
                    except Exception:
                        pass
            
            self._subscription_ids.clear()
            
            self._logger.info(
                f"SimulationResultWatcher stopped for: {self._project_root}"
            )
            
        except Exception as e:
            self._logger.warning(f"Error stopping SimulationResultWatcher: {e}")
        
        finally:
            self._project_root = None
            self._is_watching = False
            self._debounce_buffer.clear()
            self._processed_files.clear()
    
    def initialize(self) -> None:
        """
        初始化监控器，订阅项目打开/关闭事件
        
        在应用启动时调用，自动响应项目生命周期
        """
        event_bus = self._get_event_bus()
        if event_bus:
            event_bus.subscribe(
                EVENT_STATE_PROJECT_OPENED, 
                self._on_project_opened
            )
            event_bus.subscribe(
                EVENT_STATE_PROJECT_CLOSED, 
                self._on_project_closed
            )
            self._logger.info("SimulationResultWatcher initialized")
    
    def dispose(self) -> None:
        """
        释放资源
        
        在应用关闭时调用
        """
        self.stop()
        
        event_bus = self._get_event_bus()
        if event_bus:
            try:
                event_bus.unsubscribe(
                    EVENT_STATE_PROJECT_OPENED, 
                    self._on_project_opened
                )
                event_bus.unsubscribe(
                    EVENT_STATE_PROJECT_CLOSED, 
                    self._on_project_closed
                )
            except Exception:
                pass
    
    # ============================================================
    # 事件处理
    # ============================================================
    
    def _on_project_opened(self, event_data: dict) -> None:
        """处理项目打开事件"""
        project_path = event_data.get("path")
        if project_path:
            self.start(project_path)
    
    def _on_project_closed(self, event_data: dict) -> None:
        """处理项目关闭事件"""
        self.stop()
    
    def _on_file_changed(self, event_data: dict) -> None:
        """
        处理文件变更事件
        
        Args:
            event_data: 事件数据，包含 path, event_type, is_directory
        """
        if not self._is_watching or not self._project_root:
            return
        
        file_path = event_data.get("path", "")
        event_type = event_data.get("event_type", "")
        is_directory = event_data.get("is_directory", False)
        
        # 忽略目录事件
        if is_directory:
            return
        
        # 仅处理创建和修改事件
        if event_type not in ("created", "modified"):
            return
        
        # 检查是否为仿真结果文件
        if not self._is_sim_result_file(file_path):
            return
        
        # 防抖处理
        current_time = time.time()
        last_time = self._debounce_buffer.get(file_path, 0)
        
        if current_time - last_time < DEBOUNCE_INTERVAL_SECONDS:
            # 在防抖间隔内，更新时间但不处理
            self._debounce_buffer[file_path] = current_time
            return
        
        self._debounce_buffer[file_path] = current_time
        
        # 计算相对路径
        try:
            abs_path = Path(file_path).resolve()
            root_path = Path(self._project_root).resolve()
            relative_path = str(abs_path.relative_to(root_path))
        except ValueError:
            # 文件不在项目目录内
            return
        
        # 检查是否已处理过（避免重复发布）
        if relative_path in self._processed_files:
            # 对于 modified 事件，允许重新处理
            if event_type != "modified":
                return
        
        self._processed_files.add(relative_path)
        
        # 发布事件
        self._publish_result_created_event(relative_path)
    
    def _is_sim_result_file(self, file_path: str) -> bool:
        """
        判断是否为仿真结果文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为仿真结果文件
        """
        try:
            path = Path(file_path)
            
            # 检查扩展名
            if path.suffix.lower() != SIM_RESULT_EXTENSION:
                return False
            
            # 检查是否在仿真结果目录下
            # 支持绝对路径和相对路径
            path_str = str(path)
            
            # 检查路径中是否包含仿真结果目录
            if SIM_RESULTS_DIR in path_str:
                return True
            
            # 检查相对于项目根目录的路径
            if self._project_root:
                try:
                    root_path = Path(self._project_root).resolve()
                    abs_path = path.resolve()
                    relative = abs_path.relative_to(root_path)
                    if str(relative).startswith(SIM_RESULTS_DIR.replace("/", "\\")):
                        return True
                    if str(relative).startswith(SIM_RESULTS_DIR):
                        return True
                except ValueError:
                    pass
            
            return False
            
        except Exception:
            return False
    
    def _publish_result_created_event(self, relative_path: str) -> None:
        """
        发布仿真结果文件创建事件
        
        Args:
            relative_path: 结果文件相对路径
        """
        event_bus = self._get_event_bus()
        if not event_bus:
            return
        
        event_data = {
            "file_path": relative_path,
            "project_root": self._project_root,
        }
        
        try:
            event_bus.publish(
                EVENT_SIM_RESULT_FILE_CREATED,
                event_data,
                source="simulation_result_watcher"
            )
            self._logger.info(
                f"Published EVENT_SIM_RESULT_FILE_CREATED: {relative_path}"
            )
        except Exception as e:
            self._logger.warning(f"Failed to publish event: {e}")
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _get_event_bus(self):
        """获取 EventBus 实例"""
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus
    
    def clear_processed_files(self) -> None:
        """清空已处理文件集合（用于测试或强制刷新）"""
        self._processed_files.clear()
        self._debounce_buffer.clear()


# ============================================================
# 模块级单例
# ============================================================

simulation_result_watcher = SimulationResultWatcher()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationResultWatcher",
    "simulation_result_watcher",
    "DEBOUNCE_INTERVAL_SECONDS",
    "SIM_RESULT_EXTENSION",
]
