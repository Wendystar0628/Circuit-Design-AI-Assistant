# Tracing Store - SQLite Persistence
"""
追踪数据存储

职责：
- 管理追踪数据的持久化存储
- 提供查询接口供 DevToolsPanel 使用
- 自动清理过期数据

存储位置：
- ~/.circuit_design_ai/traces.sqlite3（全局，跨项目）

设计说明：
- 使用 aiosqlite 实现异步操作，不阻塞事件循环
- 主表和数据表分离，避免 JSON 查询性能问题
- 批量插入提高写入效率
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from shared.tracing.tracing_types import SpanRecord, TraceStatus


# ============================================================
# SQL 语句
# ============================================================

_SQL_CREATE_SPANS_TABLE = """
CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL UNIQUE,
    parent_span_id TEXT,
    operation_name TEXT NOT NULL,
    service_name TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_SQL_CREATE_SPAN_DATA_TABLE = """
CREATE TABLE IF NOT EXISTS span_data (
    span_id TEXT PRIMARY KEY,
    inputs TEXT,
    outputs TEXT,
    metadata TEXT,
    FOREIGN KEY (span_id) REFERENCES spans(span_id) ON DELETE CASCADE
)
"""

_SQL_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id)",
    "CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans(start_time)",
    "CREATE INDEX IF NOT EXISTS idx_spans_status ON spans(status)",
    "CREATE INDEX IF NOT EXISTS idx_spans_service ON spans(service_name)",
]

_SQL_INSERT_SPAN = """
INSERT OR REPLACE INTO spans 
    (trace_id, span_id, parent_span_id, operation_name, 
     service_name, start_time, end_time, status, error_message)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_INSERT_SPAN_DATA = """
INSERT OR REPLACE INTO span_data (span_id, inputs, outputs, metadata)
VALUES (?, ?, ?, ?)
"""

_SQL_UPDATE_SPAN = """
UPDATE spans SET end_time = ?, status = ?, error_message = ?
WHERE span_id = ?
"""

_SQL_GET_TRACE = """
SELECT id, trace_id, span_id, parent_span_id, operation_name,
       service_name, start_time, end_time, status, error_message, created_at
FROM spans
WHERE trace_id = ?
ORDER BY start_time ASC
"""

_SQL_GET_SPAN_DATA = """
SELECT span_id, inputs, outputs, metadata
FROM span_data
WHERE span_id = ?
"""

_SQL_GET_RECENT_TRACES = """
SELECT DISTINCT trace_id, MIN(start_time) as trace_start
FROM spans
GROUP BY trace_id
ORDER BY trace_start DESC
LIMIT ? OFFSET ?
"""

_SQL_GET_SPANS_BY_TRACE = """
SELECT id, trace_id, span_id, parent_span_id, operation_name,
       service_name, start_time, end_time, status, error_message, created_at
FROM spans
WHERE trace_id = ?
ORDER BY start_time ASC
"""

_SQL_GET_SPANS_BY_STATUS = """
SELECT id, trace_id, span_id, parent_span_id, operation_name,
       service_name, start_time, end_time, status, error_message, created_at
FROM spans
WHERE status = ?
ORDER BY start_time DESC
LIMIT ?
"""

_SQL_CLEANUP_OLD_SPANS = """
DELETE FROM spans
WHERE start_time < ?
"""

_SQL_CLEANUP_ORPHAN_DATA = """
DELETE FROM span_data
WHERE span_id NOT IN (SELECT span_id FROM spans)
"""

_SQL_GET_STATS = """
SELECT 
    COUNT(*) as total_spans,
    COUNT(DISTINCT trace_id) as total_traces,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
    AVG(CASE WHEN end_time IS NOT NULL THEN (end_time - start_time) * 1000 END) as avg_duration_ms
FROM spans
WHERE start_time > ?
"""


# ============================================================
# TracingStore
# ============================================================

class TracingStore:
    """
    追踪数据存储
    
    使用 aiosqlite 实现异步 SQLite 操作。
    
    初始化顺序：Phase 1.7（核心管理器初始化阶段）
    依赖：Logger
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化存储
        
        Args:
            db_path: 数据库路径，默认为 ~/.circuit_design_ai/traces.sqlite3
        """
        if db_path is None:
            db_path = Path.home() / ".circuit_design_ai" / "traces.sqlite3"
        
        self._db_path = db_path
        self._initialized = False
        self._logger = None
    
    @property
    def db_path(self) -> Path:
        """数据库路径"""
        return self._db_path
    
    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized
    
    # --------------------------------------------------------
    # 初始化
    # --------------------------------------------------------
    
    async def initialize(self) -> bool:
        """
        初始化数据库
        
        创建表结构和索引。应用启动时调用。
        
        Returns:
            bool: 是否成功
        """
        try:
            # 确保目录存在
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            
            async with aiosqlite.connect(self._db_path) as db:
                # 启用外键约束
                await db.execute("PRAGMA foreign_keys = ON")
                
                # 创建表
                await db.execute(_SQL_CREATE_SPANS_TABLE)
                await db.execute(_SQL_CREATE_SPAN_DATA_TABLE)
                
                # 创建索引
                for sql in _SQL_CREATE_INDEXES:
                    await db.execute(sql)
                
                await db.commit()
            
            self._initialized = True
            self._log_info(f"TracingStore 初始化完成: {self._db_path}")
            return True
            
        except Exception as e:
            self._log_error(f"TracingStore 初始化失败: {e}")
            return False
    
    # --------------------------------------------------------
    # 写入操作
    # --------------------------------------------------------
    
    async def insert_spans(self, spans: List[SpanRecord]) -> int:
        """
        批量插入 Span 记录
        
        Args:
            spans: Span 记录列表
            
        Returns:
            int: 成功插入的数量
        """
        if not spans:
            return 0
        
        try:
            async with aiosqlite.connect(self._db_path) as db:
                # 插入主表
                await db.executemany(
                    _SQL_INSERT_SPAN,
                    [span.to_main_tuple() for span in spans]
                )
                
                # 插入数据表
                await db.executemany(
                    _SQL_INSERT_SPAN_DATA,
                    [span.to_data_tuple() for span in spans]
                )
                
                await db.commit()
            
            return len(spans)
            
        except Exception as e:
            self._log_error(f"批量插入 Span 失败: {e}")
            return 0
    
    async def update_span(
        self,
        span_id: str,
        end_time: Optional[float] = None,
        status: Optional[TraceStatus] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        更新 Span 状态
        
        Args:
            span_id: Span ID
            end_time: 结束时间
            status: 状态
            error_message: 错误信息
            
        Returns:
            bool: 是否成功
        """
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    _SQL_UPDATE_SPAN,
                    (
                        end_time,
                        status.value if status else None,
                        error_message,
                        span_id,
                    )
                )
                await db.commit()
            return True
            
        except Exception as e:
            self._log_error(f"更新 Span 失败: {e}")
            return False
    
    # --------------------------------------------------------
    # 查询操作
    # --------------------------------------------------------
    
    async def get_trace(self, trace_id: str) -> List[SpanRecord]:
        """
        获取完整追踪链路
        
        Args:
            trace_id: 追踪 ID
            
        Returns:
            list: Span 记录列表（按开始时间排序）
        """
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # 获取所有 Span
                cursor = await db.execute(_SQL_GET_TRACE, (trace_id,))
                rows = await cursor.fetchall()
                
                if not rows:
                    return []
                
                # 获取所有 Span 的数据
                span_ids = [row["span_id"] for row in rows]
                data_map = await self._get_span_data_batch(db, span_ids)
                
                # 构建 SpanRecord
                records = []
                for row in rows:
                    data_row = data_map.get(row["span_id"])
                    record = SpanRecord.from_db_row(tuple(row), data_row)
                    records.append(record)
                
                return records
                
        except Exception as e:
            self._log_error(f"获取追踪链路失败: {e}")
            return []
    
    async def get_span_with_data(self, span_id: str) -> Optional[SpanRecord]:
        """
        获取单个 Span 详情（含输入输出）
        
        Args:
            span_id: Span ID
            
        Returns:
            SpanRecord: Span 记录，不存在返回 None
        """
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # 获取主表数据
                cursor = await db.execute(
                    """SELECT id, trace_id, span_id, parent_span_id, operation_name,
                              service_name, start_time, end_time, status, error_message, created_at
                       FROM spans WHERE span_id = ?""",
                    (span_id,)
                )
                row = await cursor.fetchone()
                
                if not row:
                    return None
                
                # 获取数据表
                cursor = await db.execute(_SQL_GET_SPAN_DATA, (span_id,))
                data_row = await cursor.fetchone()
                
                return SpanRecord.from_db_row(
                    tuple(row),
                    tuple(data_row) if data_row else None
                )
                
        except Exception as e:
            self._log_error(f"获取 Span 详情失败: {e}")
            return None
    
    async def get_recent_traces(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        获取最近的追踪记录（摘要）
        
        Args:
            limit: 返回数量
            offset: 偏移量
            
        Returns:
            list: 追踪摘要列表，每项包含 trace_id, span_count, start_time, 
                  end_time, duration_ms, has_error, root_operation
        """
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # 获取最近的 trace_id
                cursor = await db.execute(_SQL_GET_RECENT_TRACES, (limit, offset))
                trace_rows = await cursor.fetchall()
                
                if not trace_rows:
                    return []
                
                # 获取每个 trace 的详细信息
                results = []
                for trace_row in trace_rows:
                    trace_id = trace_row["trace_id"]
                    
                    # 获取该 trace 的所有 span
                    cursor = await db.execute(_SQL_GET_SPANS_BY_TRACE, (trace_id,))
                    spans = await cursor.fetchall()
                    
                    if not spans:
                        continue
                    
                    # 计算摘要信息
                    start_time = min(s["start_time"] for s in spans)
                    end_times = [s["end_time"] for s in spans if s["end_time"]]
                    end_time = max(end_times) if end_times else None
                    duration_ms = (end_time - start_time) * 1000 if end_time else None
                    has_error = any(s["status"] == "error" for s in spans)
                    
                    # 找根节点
                    root_span = next(
                        (s for s in spans if s["parent_span_id"] is None),
                        spans[0]
                    )
                    
                    results.append({
                        "trace_id": trace_id,
                        "span_count": len(spans),
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration_ms": duration_ms,
                        "has_error": has_error,
                        "root_operation": root_span["operation_name"],
                        "root_service": root_span["service_name"],
                    })
                
                return results
                
        except Exception as e:
            self._log_error(f"获取最近追踪失败: {e}")
            return []
    
    async def get_spans_by_status(
        self,
        status: TraceStatus,
        limit: int = 100,
    ) -> List[SpanRecord]:
        """
        按状态查询 Span
        
        Args:
            status: 状态
            limit: 返回数量
            
        Returns:
            list: Span 记录列表
        """
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                
                cursor = await db.execute(
                    _SQL_GET_SPANS_BY_STATUS,
                    (status.value, limit)
                )
                rows = await cursor.fetchall()
                
                # 不加载输入输出数据（性能考虑）
                return [
                    SpanRecord.from_db_row(tuple(row), None)
                    for row in rows
                ]
                
        except Exception as e:
            self._log_error(f"按状态查询 Span 失败: {e}")
            return []
    
    async def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取统计信息
        
        Args:
            hours: 统计时间范围（小时）
            
        Returns:
            dict: 统计信息
        """
        try:
            since = time.time() - hours * 3600
            
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                
                cursor = await db.execute(_SQL_GET_STATS, (since,))
                row = await cursor.fetchone()
                
                if not row:
                    return {
                        "total_spans": 0,
                        "total_traces": 0,
                        "error_count": 0,
                        "error_rate": 0.0,
                        "avg_duration_ms": 0.0,
                    }
                
                total = row["total_spans"] or 0
                errors = row["error_count"] or 0
                
                return {
                    "total_spans": total,
                    "total_traces": row["total_traces"] or 0,
                    "error_count": errors,
                    "error_rate": errors / total if total > 0 else 0.0,
                    "avg_duration_ms": row["avg_duration_ms"] or 0.0,
                }
                
        except Exception as e:
            self._log_error(f"获取统计信息失败: {e}")
            return {}
    
    # --------------------------------------------------------
    # 清理操作
    # --------------------------------------------------------
    
    async def cleanup_old_traces(self, days: int = 7) -> int:
        """
        清理过期追踪数据
        
        Args:
            days: 保留天数
            
        Returns:
            int: 删除的记录数
        """
        try:
            cutoff_time = time.time() - days * 24 * 3600
            
            async with aiosqlite.connect(self._db_path) as db:
                # 删除旧的 span
                cursor = await db.execute(_SQL_CLEANUP_OLD_SPANS, (cutoff_time,))
                deleted_count = cursor.rowcount
                
                # 清理孤立的 span_data
                await db.execute(_SQL_CLEANUP_ORPHAN_DATA)
                
                await db.commit()
            
            if deleted_count > 0:
                self._log_info(f"清理了 {deleted_count} 条过期追踪记录")
            
            return deleted_count
            
        except Exception as e:
            self._log_error(f"清理过期数据失败: {e}")
            return 0
    
    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------
    
    async def close(self) -> None:
        """
        关闭存储
        
        aiosqlite 使用连接池模式，每次操作都是新连接，
        所以这里主要是标记状态。
        """
        self._initialized = False
        self._log_info("TracingStore 已关闭")
    
    # --------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------
    
    async def _get_span_data_batch(
        self,
        db: aiosqlite.Connection,
        span_ids: List[str],
    ) -> Dict[str, Tuple]:
        """批量获取 span_data"""
        if not span_ids:
            return {}
        
        placeholders = ",".join("?" * len(span_ids))
        cursor = await db.execute(
            f"SELECT span_id, inputs, outputs, metadata FROM span_data WHERE span_id IN ({placeholders})",
            span_ids
        )
        rows = await cursor.fetchall()
        
        return {row[0]: tuple(row) for row in rows}
    
    def _log_info(self, message: str) -> None:
        """记录信息日志"""
        if self._logger:
            self._logger.info(message)
        else:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("tracing_store")
                self._logger.info(message)
            except Exception:
                print(f"[TracingStore] {message}")
    
    def _log_error(self, message: str) -> None:
        """记录错误日志"""
        if self._logger:
            self._logger.error(message)
        else:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("tracing_store")
                self._logger.error(message)
            except Exception:
                print(f"[TracingStore ERROR] {message}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TracingStore",
]
