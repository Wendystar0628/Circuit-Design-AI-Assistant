# Cache Stats Tracker - API Cache Statistics
"""
缓存统计追踪 - 记录和分析 API 缓存统计

职责：
- 记录单次请求的缓存统计
- 计算会话级别的缓存统计
- 计算缓存命中率

使用示例：
    from domain.llm.cache_stats_tracker import CacheStatsTracker
    
    tracker = CacheStatsTracker()
    tracker.record_cache_stats(usage_info)
    stats = tracker.get_session_cache_stats()
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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


# ============================================================
# 缓存统计追踪器
# ============================================================

class CacheStatsTracker:
    """
    缓存统计追踪器
    
    线程安全的缓存统计记录和分析。
    """
    
    def __init__(self):
        """初始化追踪器"""
        self._lock = threading.RLock()
        self._stats_history: List[CacheStats] = []
        self._session_stats = SessionCacheStats()
    
    def record_cache_stats(self, usage_info: Dict[str, Any]) -> None:
        """
        记录单次请求的缓存统计
        
        Args:
            usage_info: API 返回的 usage 信息
        """
        import time
        
        with self._lock:
            stats = CacheStats(
                total_tokens=usage_info.get("total_tokens", 0),
                prompt_tokens=usage_info.get("prompt_tokens", 0),
                completion_tokens=usage_info.get("completion_tokens", 0),
                cached_tokens=usage_info.get("cached_tokens", 0),
                timestamp=time.time(),
            )
            
            self._stats_history.append(stats)
            
            # 更新会话统计
            self._session_stats.total_requests += 1
            self._session_stats.total_tokens += stats.total_tokens
            self._session_stats.total_prompt_tokens += stats.prompt_tokens
            self._session_stats.total_completion_tokens += stats.completion_tokens
            self._session_stats.total_cached_tokens += stats.cached_tokens
    
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
            统计列表
        """
        with self._lock:
            return list(self._stats_history[-n:])
    
    def reset_stats(self) -> None:
        """重置统计数据"""
        with self._lock:
            self._stats_history.clear()
            self._session_stats = SessionCacheStats()
    
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
            }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CacheStats",
    "SessionCacheStats",
    "CacheStatsTracker",
]
