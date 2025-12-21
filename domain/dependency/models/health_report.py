# Health Report Data Class
"""
依赖健康报告数据类

职责：
- 汇总项目的依赖健康状态
- 提供统计信息和问题摘要
- 支持序列化和缓存
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from domain.dependency.models.dependency_item import (
    DependencyItem,
    DependencyStatus,
)


@dataclass
class HealthReport:
    """
    依赖健康报告
    
    汇总项目中所有依赖的健康状态
    """
    # 项目路径
    project_path: str
    
    # 扫描时间
    scan_time: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # 所有依赖项列表
    dependencies: List[DependencyItem] = field(default_factory=list)
    
    # 扫描的文件数量
    scanned_files: int = 0
    
    # 扫描耗时（毫秒）
    scan_duration_ms: float = 0.0
    
    # 是否为增量扫描
    is_incremental: bool = False
    
    # 扫描警告信息
    warnings: List[str] = field(default_factory=list)
    
    @property
    def total_count(self) -> int:
        """总依赖数"""
        return len(self.dependencies)
    
    @property
    def resolved_count(self) -> int:
        """已解析依赖数"""
        return sum(1 for d in self.dependencies if d.status == DependencyStatus.RESOLVED)
    
    @property
    def missing_count(self) -> int:
        """缺失依赖数"""
        return sum(1 for d in self.dependencies if d.status == DependencyStatus.MISSING)
    
    @property
    def pending_count(self) -> int:
        """待确认依赖数"""
        return sum(1 for d in self.dependencies if d.status == DependencyStatus.PENDING_CONFIRMATION)
    
    @property
    def error_count(self) -> int:
        """错误依赖数"""
        return sum(1 for d in self.dependencies if d.status == DependencyStatus.ERROR)
    
    @property
    def has_issues(self) -> bool:
        """是否存在问题"""
        return self.missing_count > 0 or self.error_count > 0
    
    @property
    def is_healthy(self) -> bool:
        """是否健康（无缺失、无错误）"""
        return not self.has_issues
    
    def get_missing_dependencies(self) -> List[DependencyItem]:
        """获取缺失的依赖列表"""
        return [d for d in self.dependencies if d.status == DependencyStatus.MISSING]
    
    def get_dependencies_by_status(self, status: DependencyStatus) -> List[DependencyItem]:
        """按状态筛选依赖"""
        return [d for d in self.dependencies if d.status == status]
    
    def get_dependencies_by_source_file(self, source_file: str) -> List[DependencyItem]:
        """按来源文件筛选依赖"""
        return [d for d in self.dependencies if d.source_file == source_file]
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "project_path": self.project_path,
            "scan_time": self.scan_time,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "scanned_files": self.scanned_files,
            "scan_duration_ms": self.scan_duration_ms,
            "is_incremental": self.is_incremental,
            "warnings": self.warnings,
            "summary": {
                "total": self.total_count,
                "resolved": self.resolved_count,
                "missing": self.missing_count,
                "pending": self.pending_count,
                "error": self.error_count,
                "has_issues": self.has_issues,
            },
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "HealthReport":
        """从字典反序列化"""
        report = cls(
            project_path=data["project_path"],
            scan_time=data.get("scan_time", datetime.now().isoformat()),
            scanned_files=data.get("scanned_files", 0),
            scan_duration_ms=data.get("scan_duration_ms", 0.0),
            is_incremental=data.get("is_incremental", False),
            warnings=data.get("warnings", []),
        )
        report.dependencies = [
            DependencyItem.from_dict(d) for d in data.get("dependencies", [])
        ]
        return report
    
    def get_summary_text(self) -> str:
        """获取摘要文本（用于状态栏显示）"""
        if self.is_healthy:
            return f"依赖健康: {self.resolved_count} 个依赖已解析"
        else:
            parts = []
            if self.missing_count > 0:
                parts.append(f"{self.missing_count} 个缺失")
            if self.error_count > 0:
                parts.append(f"{self.error_count} 个错误")
            return f"依赖问题: {', '.join(parts)}"


__all__ = ["HealthReport"]
