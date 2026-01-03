# Implicit Context Aggregator - Coordinate Multiple Context Collectors
"""
隐式上下文聚合器 - 协调多个专职收集器，聚合隐式上下文

职责：
- 协调多个专职收集器
- 并发执行所有收集器
- 按优先级排序结果
- 维护文件变更缓存

默认注册的收集器：
- CircuitFileCollector - 电路文件收集
- SimulationContextCollector - 仿真上下文收集
- DesignGoalsCollector - 设计目标收集

扩展机制：
- 支持运行时注册新的收集器
- 阶段十可通过 register_collector() 添加元器件上下文收集器
- 无需修改聚合器代码

被调用方：context_retriever.py
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from domain.llm.context_retrieval.context_source_protocol import (
    CollectionContext,
    ContextPriority,
    ContextResult,
    ContextSource,
)
from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
from domain.llm.context_retrieval.simulation_context_collector import (
    SimulationContextCollector,
)
from domain.llm.context_retrieval.design_goals_collector import DesignGoalsCollector
from domain.llm.context_retrieval.diagnostics_collector import DiagnosticsCollector


# ============================================================
# 常量定义
# ============================================================

# 文件变更缓存过期时间（秒）
FILE_CACHE_EXPIRY_SECONDS = 30

# 最大并发收集器数量
MAX_CONCURRENT_COLLECTORS = 10


class ImplicitContextAggregator:
    """
    隐式上下文聚合器
    
    协调多个专职收集器，聚合隐式上下文。
    支持运行时注册新的收集器。
    """

    def __init__(self):
        # 收集器列表
        self._collectors: List[ContextSource] = []
        
        # 文件变更缓存
        self._recently_modified_files: Dict[str, float] = {}  # path -> timestamp
        
        # 事件订阅状态
        self._subscribed = False
        
        # 延迟获取的服务
        self._event_bus = None
        self._logger = None
        
        # 注册默认收集器
        self._register_default_collectors()

    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def event_bus(self):
        """延迟获取事件总线"""
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
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("implicit_context_aggregator")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 收集器管理
    # ============================================================

    def _register_default_collectors(self):
        """注册默认收集器"""
        self._collectors = [
            DiagnosticsCollector(),      # CRITICAL 优先级
            CircuitFileCollector(),       # HIGH 优先级
            SimulationContextCollector(), # HIGH 优先级
            DesignGoalsCollector(),       # MEDIUM 优先级
        ]

    def register_collector(self, collector: ContextSource) -> None:
        """
        注册新的收集器
        
        Args:
            collector: 实现 ContextSource 协议的收集器
        """
        # 检查是否已注册
        source_name = collector.get_source_name()
        for existing in self._collectors:
            if existing.get_source_name() == source_name:
                if self.logger:
                    self.logger.warning(
                        f"Collector '{source_name}' already registered, skipping"
                    )
                return
        
        self._collectors.append(collector)
        
        if self.logger:
            self.logger.info(f"Registered collector: {source_name}")

    def unregister_collector(self, source_name: str) -> bool:
        """
        注销收集器
        
        Args:
            source_name: 收集器名称
            
        Returns:
            bool: 是否成功注销
        """
        for i, collector in enumerate(self._collectors):
            if collector.get_source_name() == source_name:
                self._collectors.pop(i)
                if self.logger:
                    self.logger.info(f"Unregistered collector: {source_name}")
                return True
        return False

    def get_registered_collectors(self) -> List[str]:
        """获取已注册的收集器名称列表"""
        return [c.get_source_name() for c in self._collectors]

    # ============================================================
    # 主入口
    # ============================================================

    async def collect_async(
        self, context: CollectionContext
    ) -> List[ContextResult]:
        """
        异步收集所有隐式上下文
        
        并发执行所有注册的收集器，按优先级排序结果。
        
        Args:
            context: 收集上下文
            
        Returns:
            List[ContextResult]: 收集结果列表（按优先级排序）
        """
        # 确保已订阅文件变更事件
        self._ensure_subscribed()
        
        if not self._collectors:
            if self.logger:
                self.logger.warning("No collectors registered")
            return []
        
        if self.logger:
            self.logger.debug(
                f"Collecting context with {len(self._collectors)} collectors"
            )
        
        # 并发执行所有收集器
        results = await self._collect_all_async(context)
        
        # 过滤空结果
        results = [r for r in results if not r.is_empty]
        
        # 按优先级排序
        results = self._sort_by_priority(results)
        
        if self.logger:
            self.logger.info(
                f"Collected {len(results)} context items "
                f"(total tokens: {sum(r.token_count for r in results)})"
            )
        
        return results

    async def _collect_all_async(
        self, context: CollectionContext
    ) -> List[ContextResult]:
        """
        并发调用所有收集器
        
        Args:
            context: 收集上下文
            
        Returns:
            List[ContextResult]: 收集结果列表
        """
        results: List[ContextResult] = []
        
        # 创建收集任务
        tasks = []
        for collector in self._collectors[:MAX_CONCURRENT_COLLECTORS]:
            task = self._safe_collect(collector, context)
            tasks.append(task)
        
        # 并发执行
        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(task_results):
                if isinstance(result, Exception):
                    collector_name = self._collectors[i].get_source_name()
                    if self.logger:
                        self.logger.warning(
                            f"Collector '{collector_name}' failed: {result}"
                        )
                    # 返回空结果
                    results.append(ContextResult.empty(collector_name))
                elif isinstance(result, ContextResult):
                    results.append(result)
        
        return results

    async def _safe_collect(
        self,
        collector: ContextSource,
        context: CollectionContext,
    ) -> ContextResult:
        """
        安全执行收集器（捕获异常）
        
        Args:
            collector: 收集器
            context: 收集上下文
            
        Returns:
            ContextResult: 收集结果
        """
        try:
            return await collector.collect_async(context)
        except Exception as e:
            source_name = collector.get_source_name()
            if self.logger:
                self.logger.error(f"Collector '{source_name}' error: {e}")
            return ContextResult.empty(source_name)

    def _sort_by_priority(
        self, results: List[ContextResult]
    ) -> List[ContextResult]:
        """
        按优先级排序结果
        
        Args:
            results: 收集结果列表
            
        Returns:
            List[ContextResult]: 排序后的结果
        """
        return sorted(results, key=lambda r: r.priority.value)

    # ============================================================
    # 文件变更感知
    # ============================================================

    def _ensure_subscribed(self):
        """确保已订阅文件变更事件"""
        if self._subscribed or self.event_bus is None:
            return
        
        try:
            from shared.event_types import EVENT_FILE_CHANGED
            self.event_bus.subscribe(EVENT_FILE_CHANGED, self._on_file_changed)
            self._subscribed = True
            
            if self.logger:
                self.logger.debug("Subscribed to file change events")
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to subscribe to events: {e}")

    def _on_file_changed(self, event_data: Dict[str, Any]):
        """
        文件变更事件处理
        
        Args:
            event_data: 事件数据
        """
        path = event_data.get("path", "")
        if path:
            self._recently_modified_files[path] = time.time()
            
            # 清理过期条目
            self._cleanup_expired_cache()

    def _cleanup_expired_cache(self):
        """清理过期的文件变更缓存"""
        now = time.time()
        expired_keys = [
            path for path, timestamp in self._recently_modified_files.items()
            if now - timestamp > FILE_CACHE_EXPIRY_SECONDS
        ]
        for key in expired_keys:
            del self._recently_modified_files[key]

    def get_recently_modified_files(self) -> Set[str]:
        """
        获取最近修改的文件列表
        
        Returns:
            Set[str]: 文件路径集合
        """
        self._cleanup_expired_cache()
        return set(self._recently_modified_files.keys())

    def is_recently_modified(self, file_path: str) -> bool:
        """
        检查文件是否最近被修改
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否最近被修改
        """
        self._cleanup_expired_cache()
        return file_path in self._recently_modified_files

    # ============================================================
    # 辅助方法
    # ============================================================

    def get_status(self) -> Dict[str, Any]:
        """获取聚合器状态"""
        return {
            "collector_count": len(self._collectors),
            "collectors": self.get_registered_collectors(),
            "subscribed": self._subscribed,
            "recently_modified_count": len(self._recently_modified_files),
        }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ImplicitContextAggregator",
    "FILE_CACHE_EXPIRY_SECONDS",
    "MAX_CONCURRENT_COLLECTORS",
]
