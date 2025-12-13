# Service Locator - Dependency Injection Container
"""
服务定位器 - 轻量级依赖注入容器

职责：
- 管理服务实例的注册与获取
- 提供全局唯一的服务访问点
- 解耦组件间的直接依赖

初始化顺序：
- Phase 0.2，Logger 之后创建空容器
- 后续各 Phase 逐步注册服务

设计原则：
- 单例模式，全局唯一实例
- 启动时注册，运行时只读
- 服务名使用常量定义，避免字符串硬编码

使用示例：
    # 注册服务（启动时）
    from shared.service_locator import ServiceLocator
    from shared.service_names import SVC_EVENT_BUS
    ServiceLocator.register(SVC_EVENT_BUS, event_bus_instance)
    
    # 获取服务（运行时）
    event_bus = ServiceLocator.get(SVC_EVENT_BUS)
    
    # 延迟获取模式（推荐）
    class MyClass:
        def __init__(self):
            self._event_bus = None
        
        @property
        def event_bus(self):
            if self._event_bus is None:
                self._event_bus = ServiceLocator.get(SVC_EVENT_BUS)
            return self._event_bus
"""

from typing import Any, Dict, Optional, TypeVar

T = TypeVar('T')


class ServiceNotFoundError(Exception):
    """服务未找到异常"""

    def __init__(self, service_name: str, message: str = None):
        self.service_name = service_name
        if message is None:
            message = (
                f"服务 '{service_name}' 未注册。\n"
                f"可能的原因：\n"
                f"  1. 服务尚未初始化（检查初始化顺序）\n"
                f"  2. 服务名拼写错误（使用 service_names.py 中的常量）\n"
                f"  3. 在 __init__ 中过早获取服务（使用延迟获取模式）"
            )
        super().__init__(message)



class ServiceLocator:
    """
    服务定位器 - 轻量级依赖注入容器
    
    采用单例模式，提供全局唯一的服务注册和获取点。
    
    线程安全说明：
    - 注册操作仅在启动阶段（单线程）执行
    - 运行时仅执行读取操作，无需加锁
    """

    # 单例实例
    _instance: Optional['ServiceLocator'] = None

    # 服务注册表
    _services: Dict[str, Any] = {}

    def __new__(cls) -> 'ServiceLocator':
        """确保单例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> 'ServiceLocator':
        """
        获取 ServiceLocator 单例实例
        
        Returns:
            ServiceLocator: 单例实例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def register(cls, name: str, service: Any) -> None:
        """
        注册服务实例
        
        Args:
            name: 服务名（建议使用 service_names.py 中的常量）
            service: 服务实例
            
        Raises:
            ValueError: 服务名为空或服务实例为 None
            
        Note:
            重复注册同名服务会覆盖旧实例（仅用于测试场景）
        """
        if not name:
            raise ValueError("服务名不能为空")
        if service is None:
            raise ValueError(f"服务实例不能为 None: {name}")

        cls._services[name] = service

    @classmethod
    def get(cls, name: str) -> Any:
        """
        获取服务实例
        
        Args:
            name: 服务名
            
        Returns:
            服务实例
            
        Raises:
            ServiceNotFoundError: 服务未注册
        """
        if name not in cls._services:
            raise ServiceNotFoundError(name)
        return cls._services[name]

    @classmethod
    def get_optional(cls, name: str) -> Optional[Any]:
        """
        获取服务实例（可选模式）
        
        与 get() 不同，服务不存在时返回 None 而非抛出异常。
        适用于可选依赖或初始化阶段的安全获取。
        
        Args:
            name: 服务名
            
        Returns:
            服务实例，不存在时返回 None
        """
        return cls._services.get(name)

    @classmethod
    def has(cls, name: str) -> bool:
        """
        检查服务是否已注册
        
        Args:
            name: 服务名
            
        Returns:
            bool: 服务是否存在
        """
        return name in cls._services

    @classmethod
    def clear(cls) -> None:
        """
        清空所有注册的服务
        
        仅用于测试场景，生产环境不应调用此方法。
        """
        cls._services.clear()

    @classmethod
    def get_all_names(cls) -> list:
        """
        获取所有已注册的服务名列表
        
        用于调试和诊断。
        
        Returns:
            list: 服务名列表
        """
        return list(cls._services.keys())

    @classmethod
    def get_service_count(cls) -> int:
        """
        获取已注册服务数量
        
        Returns:
            int: 服务数量
        """
        return len(cls._services)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ServiceLocator",
    "ServiceNotFoundError",
]
