# Cache Stats Tracker - API Cache Statistics
"""
缓存统计追踪 - 记录和分析 API 缓存统计

职责：
- 记录单次请求的缓存统计
- 计算会话级别的缓存统计
- 计算缓存命中率
- 生成缓存效率报告
- 支持时间窗口统计

设计说明：
- 线程安全：使用 RLock 保护所有状态访问
- 日志记录：当缓存命中时自动记录日志
- 成本分析：支持计算缓存节省的 token 数

使用示例：
    from domain.llm.cache_stats_tracker import CacheStatsTracker
    
    tracker = CacheStatsTracker()
    tracker.record_cache_stats(usage_info)
    stats = tracker.get_session_cache_stats()
    report = tracker.generate_efficiency_report()
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# 日志配置
# ============================================================

_logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CacheStats:
    """单次请求的缓存统计"""
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    timestamp: float = 0.0

    @property
    def cache_hit_ratio(self) -> float:
        """计算缓存命中率"""
        if self.prompt_tokens == 0:
            return 0.0
        return self.cached_tokens / self.prompt_tokens
    
    @property
    def has_cache_hit(self) -> bool:
        """是否有缓存命中"""
        return self.cached_tokens > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "timestamp": self.timestamp,
            "cache_hit_ratio": self.cache_hit_ratio,
        }


@dataclass
class SessionCacheStats:
    """会话级别的缓存统计"""
    total_requests: int = 0
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    
    @property
    def cache_hit_ratio(self) -> float:
        """计算整体缓存命中率"""
        if self.total_prompt_tokens == 0:
            return 0.0
        return self.total_cached_tokens / self.total_prompt_tokens
    
    @property
    def avg_tokens_per_request(self) -> float:
        """平均每次请求的 token 数"""
        if self.total_requests == 0:
            return 0.0
        return self.total_tokens / self.total_requests
    
    @property
    def requests_with_cache_hit(self) -> int:
        """有缓存命中的请求数（需要外部计算）"""
        # 此属性需要通过 CacheStatsTracker 计算
        return 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "cache_hit_ratio": self.cache_hit_ratio,
            "avg_tokens_per_request": self.avg_tokens_per_request,
        }


@dataclass
class CacheEfficiencyReport:
    """缓存效率报告"""
    # 基础统计
    total_requests: int = 0
    requests_with_cache_hit: int = 0
    
    # Token 统计
    total_prompt_tokens: int = 0
    total_cached_tokens: int = 0
    total_completion_tokens: int = 0
    
    # 效率指标
    cache_hit_ratio: float = 0.0
    request_hit_rate: float = 0.0  # 有缓存命中的请求占比
    
    # 时间范围
    time_range_seconds: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_requests": self.total_requests,
            "requests_with_cache_hit": self.requests_with_cache_hit,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "cache_hit_ratio": round(self.cache_hit_ratio, 4),
            "request_hit_rate": round(self.request_hit_rate, 4),
            "time_range_seconds": round(self.time_range_seconds, 2),
            "tokens_saved": self.total_cached_tokens,
        }


# ============================================================
# 缓存统计追踪器
# ============================================================

class CacheStatsTracker:
    """
    缓存统计追踪器
    
    线程安全的缓存统计记录和分析。
    支持会话级别统计、时间窗口统计和效率报告生成。
    """
    
    def __init__(self):
        """初始化追踪器"""
        self._lock = threading.RLock()
        self._stats_history: List[CacheStats] = []
        self._session_stats = SessionCacheStats()
        self._requests_with_cache_hit = 0
    
    def record_cache_stats(self, usage_info: Dict[str, Any]) -> None:
        """
        记录单次请求的缓存统计
        
        Args:
            usage_info: API 返回的 usage 信息，支持以下格式：
                - 标准格式: {"total_tokens", "prompt_tokens", "completion_tokens", "cached_tokens"}
                - 智谱格式: {"prompt_tokens_details": {"cached_tokens": N}}
        """
        with self._lock:
            # 提取缓存 token 数（支持多种格式）
            cached_tokens = usage_info.get("cached_tokens", 0)
            if cached_tokens == 0 and "prompt_tokens_details" in usage_info:
                details = usage_info["prompt_tokens_details"]
                cached_tokens = details.get("cached_tokens", 0)
            
            stats = CacheStats(
                total_tokens=usage_info.get("total_tokens", 0),
                prompt_tokens=usage_info.get("prompt_tokens", 0),
                completion_tokens=usage_info.get("completion_tokens", 0),
                cached_tokens=cached_tokens,
                timestamp=time.time(),
            )
            
            self._stats_history.append(stats)
            
            # 更新会话统计
            self._session_stats.total_requests += 1
            self._session_stats.total_tokens += stats.total_tokens
            self._session_stats.total_prompt_tokens += stats.prompt_tokens
            self._session_stats.total_completion_tokens += stats.completion_tokens
            self._session_stats.total_cached_tokens += stats.cached_tokens
            
            # 统计有缓存命中的请求数
            if stats.has_cache_hit:
                self._requests_with_cache_hit += 1
                
                # 记录缓存命中日志
                hit_ratio = stats.cache_hit_ratio * 100
                _logger.info(
                    f"Cache hit: {stats.cached_tokens}/{stats.prompt_tokens} tokens "
                    f"({hit_ratio:.1f}%)"
                )
    
    def get_session_cache_stats(self) -> SessionCacheStats:
        """
        获取会话级别的缓存统计
        
        Returns:
            SessionCacheStats: 会话统计对象
        """
        with self._lock:
            return SessionCacheStats(
                total_requests=self._session_stats.total_requests,
                total_tokens=self._session_stats.total_tokens,
                total_prompt_tokens=self._session_stats.total_prompt_tokens,
                total_completion_tokens=self._session_stats.total_completion_tokens,
                total_cached_tokens=self._session_stats.total_cached_tokens,
            )
    
    def get_cache_hit_ratio(self) -> float:
        """
        计算缓存命中率
        
        Returns:
            缓存命中率（0.0 - 1.0）
        """
        with self._lock:
            return self._session_stats.cache_hit_ratio
    
    def get_recent_stats(self, n: int = 10) -> List[CacheStats]:
        """
        获取最近 N 次请求的统计
        
        Args:
            n: 返回数量
            
        Returns:
            统计列表（从旧到新）
        """
        with self._lock:
            return list(self._stats_history[-n:])
    
    def get_cache_savings(self) -> Dict[str, Any]:
        """
        计算缓存节省的 token 数
        
        Returns:
            节省统计字典，包含：
            - total_cached_tokens: 总缓存命中 token 数
            - requests_with_cache_hit: 有缓存命中的请求数
            - avg_cached_per_hit: 平均每次命中的缓存 token 数
        """
        with self._lock:
            avg_cached = 0.0
            if self._requests_with_cache_hit > 0:
                avg_cached = (
                    self._session_stats.total_cached_tokens / 
                    self._requests_with_cache_hit
                )
            
            return {
                "total_cached_tokens": self._session_stats.total_cached_tokens,
                "requests_with_cache_hit": self._requests_with_cache_hit,
                "total_requests": self._session_stats.total_requests,
                "avg_cached_per_hit": round(avg_cached, 2),
            }

    
    def get_stats_by_time_window(self, seconds: float) -> SessionCacheStats:
        """
        按时间窗口统计
        
        Args:
            seconds: 时间窗口大小（秒）
            
        Returns:
            时间窗口内的统计
        """
        with self._lock:
            cutoff_time = time.time() - seconds
            
            # 筛选时间窗口内的统计
            window_stats = [
                s for s in self._stats_history 
                if s.timestamp >= cutoff_time
            ]
            
            # 计算窗口统计
            result = SessionCacheStats()
            result.total_requests = len(window_stats)
            
            for stats in window_stats:
                result.total_tokens += stats.total_tokens
                result.total_prompt_tokens += stats.prompt_tokens
                result.total_completion_tokens += stats.completion_tokens
                result.total_cached_tokens += stats.cached_tokens
            
            return result
    
    def generate_efficiency_report(
        self, 
        time_window_seconds: Optional[float] = None
    ) -> CacheEfficiencyReport:
        """
        生成缓存效率报告
        
        Args:
            time_window_seconds: 可选的时间窗口（秒），None 表示全部历史
            
        Returns:
            CacheEfficiencyReport: 效率报告
        """
        with self._lock:
            if not self._stats_history:
                return CacheEfficiencyReport()
            
            # 确定统计范围
            if time_window_seconds is not None:
                cutoff_time = time.time() - time_window_seconds
                stats_list = [
                    s for s in self._stats_history 
                    if s.timestamp >= cutoff_time
                ]
            else:
                stats_list = self._stats_history
            
            if not stats_list:
                return CacheEfficiencyReport()
            
            # 计算统计
            total_requests = len(stats_list)
            requests_with_hit = sum(1 for s in stats_list if s.has_cache_hit)
            total_prompt = sum(s.prompt_tokens for s in stats_list)
            total_cached = sum(s.cached_tokens for s in stats_list)
            total_completion = sum(s.completion_tokens for s in stats_list)
            
            # 计算效率指标
            cache_hit_ratio = total_cached / total_prompt if total_prompt > 0 else 0.0
            request_hit_rate = requests_with_hit / total_requests if total_requests > 0 else 0.0
            
            # 时间范围
            start_time = stats_list[0].timestamp
            end_time = stats_list[-1].timestamp
            time_range = end_time - start_time
            
            return CacheEfficiencyReport(
                total_requests=total_requests,
                requests_with_cache_hit=requests_with_hit,
                total_prompt_tokens=total_prompt,
                total_cached_tokens=total_cached,
                total_completion_tokens=total_completion,
                cache_hit_ratio=cache_hit_ratio,
                request_hit_rate=request_hit_rate,
                time_range_seconds=time_range,
                start_time=start_time,
                end_time=end_time,
            )
    
    def reset_stats(self) -> None:
        """重置统计数据"""
        with self._lock:
            self._stats_history.clear()
            self._session_stats = SessionCacheStats()
            self._requests_with_cache_hit = 0
            _logger.debug("Cache stats reset")
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """
        获取统计摘要
        
        Returns:
            统计摘要字典
        """
        with self._lock:
            return {
                "session": self._session_stats.to_dict(),
                "history_count": len(self._stats_history),
                "requests_with_cache_hit": self._requests_with_cache_hit,
                "savings": self.get_cache_savings(),
            }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CacheStats",
    "SessionCacheStats",
    "CacheEfficiencyReport",
    "CacheStatsTracker",
]
