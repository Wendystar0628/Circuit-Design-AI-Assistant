# ExecutorRegistry - Simulation Executor Registry
"""
仿真执行器注册表

职责：
- 管理所有仿真执行器的注册、查询和调度
- 根据文件扩展名自动选择合适的执行器
- 支持执行器的动态注册和注销
- 提供线程安全的访问控制

设计原则：
- 单例模式：确保全局唯一的注册表实例
- 开闭原则：新增仿真方式只需实现 SimulationExecutor 接口并注册
- 策略模式：执行器作为可插拔的策略组件

使用示例：
    # 注册执行器
    registry = ExecutorRegistry()
    registry.register(SpiceExecutor())
    registry.register(PythonExecutor())
    
    # 根据文件扩展名自动选择执行器
    executor = registry.get_executor_for_file("amplifier.cir")
    if executor:
        result = executor.execute("amplifier.cir", config)
    
    # 按名称获取执行器
    spice_executor = registry.get_executor("spice")
"""

import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

from domain.simulation.executor.simulation_executor import SimulationExecutor


# ============================================================
# ExecutorRegistry - 执行器注册表
# ============================================================

class ExecutorRegistry:
    """
    仿真执行器注册表
    
    管理所有仿真执行器的注册、查询和调度。
    使用单例模式确保全局唯一实例，使用锁保证线程安全。
    
    特性：
    - 线程安全：使用 threading.Lock 保护内部状态
    - 动态注册：支持运行时注册和注销执行器
    - 自动选择：根据文件扩展名自动选择合适的执行器
    - 优先级：多个执行器支持同一扩展名时，按注册顺序优先
    """
    
    def __init__(self):
        """
        初始化执行器注册表
        
        创建空的执行器字典和扩展名映射表，初始化线程锁
        """
        # 执行器字典：{name: executor}
        self._executors: Dict[str, SimulationExecutor] = {}
        
        # 扩展名映射表：{extension: [executor_names]}
        # 使用列表支持多个执行器处理同一扩展名（按注册顺序）
        self._extension_map: Dict[str, List[str]] = {}
        
        # 线程锁，保护内部状态
        self._lock = threading.Lock()
        
        # 日志记录器
        self._logger = logging.getLogger(__name__)
        
        self._logger.debug("ExecutorRegistry 初始化完成")
    
    # ============================================================
    # 执行器注册与注销
    # ============================================================
    
    def register(self, executor: SimulationExecutor) -> None:
        """
        注册仿真执行器
        
        将执行器添加到注册表，并更新扩展名映射表。
        如果执行器名称已存在，将覆盖旧的执行器。
        
        Args:
            executor: 要注册的执行器实例
            
        Raises:
            ValueError: 如果 executor 为 None
            
        示例：
            >>> registry = ExecutorRegistry()
            >>> registry.register(SpiceExecutor())
            >>> registry.register(PythonExecutor())
        """
        if executor is None:
            raise ValueError("executor 不能为 None")
        
        with self._lock:
            name = executor.get_name()
            
            # 如果执行器已存在，先注销旧的
            if name in self._executors:
                self._logger.warning(f"执行器 '{name}' 已存在，将被覆盖")
                self._unregister_internal(name)
            
            # 注册执行器
            self._executors[name] = executor
            
            # 更新扩展名映射表
            for ext in executor.get_supported_extensions():
                ext_lower = ext.lower()
                if ext_lower not in self._extension_map:
                    self._extension_map[ext_lower] = []
                
                # 添加到映射表（如果尚未存在）
                if name not in self._extension_map[ext_lower]:
                    self._extension_map[ext_lower].append(name)
            
            self._logger.info(
                f"执行器 '{name}' 注册成功，支持扩展名: "
                f"{', '.join(executor.get_supported_extensions())}"
            )
    
    def unregister(self, name: str) -> bool:
        """
        注销指定名称的执行器
        
        从注册表中移除执行器，并清理扩展名映射表。
        
        Args:
            name: 执行器名称
            
        Returns:
            bool: 是否成功注销（True 表示成功，False 表示执行器不存在）
            
        示例：
            >>> registry.unregister("spice")
            True
            >>> registry.unregister("nonexistent")
            False
        """
        with self._lock:
            return self._unregister_internal(name)
    
    def _unregister_internal(self, name: str) -> bool:
        """
        内部注销方法（不加锁，由调用方保证线程安全）
        
        Args:
            name: 执行器名称
            
        Returns:
            bool: 是否成功注销
        """
        if name not in self._executors:
            self._logger.warning(f"执行器 '{name}' 不存在，无法注销")
            return False
        
        # 获取执行器
        executor = self._executors[name]
        
        # 从扩展名映射表中移除
        for ext in executor.get_supported_extensions():
            ext_lower = ext.lower()
            if ext_lower in self._extension_map:
                if name in self._extension_map[ext_lower]:
                    self._extension_map[ext_lower].remove(name)
                
                # 如果该扩展名没有执行器了，删除映射项
                if not self._extension_map[ext_lower]:
                    del self._extension_map[ext_lower]
        
        # 从执行器字典中移除
        del self._executors[name]
        
        self._logger.info(f"执行器 '{name}' 注销成功")
        return True
    
    # ============================================================
    # 执行器查询
    # ============================================================
    
    def get_executor(self, name: str) -> Optional[SimulationExecutor]:
        """
        按名称获取执行器
        
        Args:
            name: 执行器名称
            
        Returns:
            Optional[SimulationExecutor]: 执行器实例，如果不存在则返回 None
            
        示例：
            >>> executor = registry.get_executor("spice")
            >>> if executor:
            ...     result = executor.execute("circuit.cir", {})
        """
        with self._lock:
            executor = self._executors.get(name)
            
            if executor is None:
                self._logger.debug(f"执行器 '{name}' 不存在")
            
            return executor
    
    def get_executor_for_file(self, file_path: str) -> Optional[SimulationExecutor]:
        """
        根据文件扩展名自动选择执行器
        
        从文件路径中提取扩展名，查找支持该扩展名的执行器。
        如果多个执行器支持同一扩展名，返回第一个注册的执行器。
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[SimulationExecutor]: 合适的执行器实例，如果没有找到则返回 None
            
        示例：
            >>> executor = registry.get_executor_for_file("amplifier.cir")
            >>> if executor:
            ...     print(f"使用执行器: {executor.get_name()}")
            使用执行器: spice
        """
        # 提取文件扩展名
        file_ext = Path(file_path).suffix.lower()
        
        if not file_ext:
            self._logger.debug(f"文件 '{file_path}' 没有扩展名")
            return None
        
        with self._lock:
            # 查找支持该扩展名的执行器
            executor_names = self._extension_map.get(file_ext, [])
            
            if not executor_names:
                self._logger.debug(
                    f"没有执行器支持扩展名 '{file_ext}'，"
                    f"支持的扩展名: {', '.join(self._extension_map.keys())}"
                )
                return None
            
            # 返回第一个注册的执行器（按注册顺序优先）
            executor_name = executor_names[0]
            executor = self._executors.get(executor_name)
            
            if executor:
                self._logger.debug(
                    f"为文件 '{file_path}' 选择执行器 '{executor_name}'"
                )
            
            return executor
    
    def get_all_executors(self) -> List[SimulationExecutor]:
        """
        获取所有已注册的执行器
        
        Returns:
            List[SimulationExecutor]: 执行器列表（副本，避免外部修改）
            
        示例：
            >>> executors = registry.get_all_executors()
            >>> for executor in executors:
            ...     print(f"- {executor.get_name()}: {executor.get_supported_extensions()}")
            - spice: ['.cir', '.sp', '.spice', '.net', '.ckt']
            - python: ['.py']
        """
        with self._lock:
            return list(self._executors.values())
    
    def get_all_supported_extensions(self) -> List[str]:
        """
        获取所有支持的文件扩展名
        
        Returns:
            List[str]: 扩展名列表（去重后的，包含点号）
            
        示例：
            >>> extensions = registry.get_all_supported_extensions()
            >>> print(extensions)
            ['.cir', '.sp', '.spice', '.net', '.ckt', '.py']
        """
        with self._lock:
            return list(self._extension_map.keys())
    
    # ============================================================
    # 调试与信息
    # ============================================================
    
    def get_registry_info(self) -> Dict:
        """
        获取注册表信息（用于调试和日志）
        
        Returns:
            Dict: 注册表信息字典，包含：
                - executor_count: 执行器数量
                - executors: 执行器列表（名称和支持的扩展名）
                - extension_map: 扩展名映射表
                
        示例：
            >>> info = registry.get_registry_info()
            >>> print(f"已注册 {info['executor_count']} 个执行器")
            已注册 2 个执行器
        """
        with self._lock:
            return {
                "executor_count": len(self._executors),
                "executors": [
                    {
                        "name": executor.get_name(),
                        "supported_extensions": executor.get_supported_extensions(),
                        "available_analyses": executor.get_available_analyses(),
                    }
                    for executor in self._executors.values()
                ],
                "extension_map": dict(self._extension_map),
            }
    
    def has_executor(self, name: str) -> bool:
        """
        检查是否存在指定名称的执行器
        
        Args:
            name: 执行器名称
            
        Returns:
            bool: 是否存在
            
        示例：
            >>> registry.has_executor("spice")
            True
            >>> registry.has_executor("nonexistent")
            False
        """
        with self._lock:
            return name in self._executors
    
    def can_handle_file(self, file_path: str) -> bool:
        """
        检查是否有执行器能处理指定文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否有执行器能处理该文件
            
        示例：
            >>> registry.can_handle_file("amplifier.cir")
            True
            >>> registry.can_handle_file("document.txt")
            False
        """
        return self.get_executor_for_file(file_path) is not None
    
    def clear(self) -> None:
        """
        清空注册表
        
        移除所有已注册的执行器。
        通常用于测试或重新初始化。
        
        示例：
            >>> registry.clear()
            >>> registry.get_all_executors()
            []
        """
        with self._lock:
            self._executors.clear()
            self._extension_map.clear()
            self._logger.info("注册表已清空")
    
    def __str__(self) -> str:
        """
        返回注册表的字符串表示
        
        Returns:
            str: 注册表描述
        """
        with self._lock:
            return (
                f"ExecutorRegistry("
                f"executors={len(self._executors)}, "
                f"extensions={len(self._extension_map)})"
            )
    
    def __repr__(self) -> str:
        """
        返回注册表的详细表示
        
        Returns:
            str: 注册表详细描述
        """
        with self._lock:
            executor_names = list(self._executors.keys())
            return (
                f"ExecutorRegistry("
                f"executors={executor_names}, "
                f"extension_map={dict(self._extension_map)})"
            )


# ============================================================
# 模块级单例实例
# ============================================================

# 创建全局单例实例，便于直接导入使用
executor_registry = ExecutorRegistry()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ExecutorRegistry",
    "executor_registry",
]
