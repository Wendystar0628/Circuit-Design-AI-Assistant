# File Version Tracker - TOCTOU Race Condition Detection
"""
文件版本追踪器

职责：
- 追踪工具执行上下文中读取过的文件版本
- 写入前校验版本一致性
- 检测 TOCTOU（Time-of-check to time-of-use）竞态条件

设计背景：
LLM 工具调用存在"读取-思考-写入"的时间窗口（可能长达 10-30 秒），
期间用户可能在编辑器中修改并保存文件。若 LLM 基于旧内容生成修改方案并写入，
会覆盖用户的修改。本模块通过乐观锁机制检测此类冲突。

核心策略：乐观锁 + 版本校验（Fail Fast）
- 读取文件时记录内容哈希
- 写入文件前校验当前哈希是否与读取时一致
- 哈希不一致时返回结构化错误，由 LLM 决定下一步操作
- 不尝试自动合并（三路合并复杂度高，容易产生语法错误）

使用示例：
    from infrastructure.persistence.file_version_tracker import FileVersionTracker
    
    tracker = FileVersionTracker()
    
    # 读取文件时记录版本
    content = file_manager.read_file("amplifier.cir")
    tracker.record_read("amplifier.cir", content)
    
    # 写入前校验版本
    result = tracker.verify_before_write("amplifier.cir")
    if not result.is_consistent:
        raise FileModifiedExternallyError(...)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .content_hash import compute_content_hash, compute_file_hash


@dataclass
class VersionCheckResult:
    """
    版本校验结果
    
    Attributes:
        is_consistent: 版本是否一致
        file_path: 文件路径
        recorded_hash: 读取时记录的哈希
        current_hash: 当前文件哈希
        file_exists: 文件是否存在
        was_tracked: 是否在追踪列表中
    """
    is_consistent: bool
    file_path: str
    recorded_hash: Optional[str]
    current_hash: Optional[str]
    file_exists: bool
    was_tracked: bool


class FileVersionTracker:
    """
    文件版本追踪器
    
    追踪工具执行上下文中读取过的文件版本，写入前校验版本一致性。
    每轮工具调用应创建新的 tracker 实例。
    
    生命周期：
    - 每轮工具调用开始时创建新实例
    - read_file 工具执行时调用 record_read()
    - patch_file/rewrite_file 工具执行前调用 verify_before_write()
    - 工具调用轮次结束后实例被丢弃
    """
    
    def __init__(self):
        """初始化文件版本追踪器"""
        self._versions: Dict[str, str] = {}  # file_path -> content_hash
    
    def record_read(self, file_path: str, content: str) -> str:
        """
        记录文件读取
        
        Args:
            file_path: 文件路径
            content: 文件内容
            
        Returns:
            str: 内容哈希
        """
        # 规范化路径
        normalized_path = self._normalize_path(file_path)
        content_hash = compute_content_hash(content)
        self._versions[normalized_path] = content_hash
        return content_hash
    
    def verify_before_write(self, file_path: str) -> VersionCheckResult:
        """
        写入前校验版本
        
        校验逻辑：
        1. 检查文件是否在追踪列表中
        2. 若不在追踪列表 → 返回 is_consistent=True（新文件或未读取过的文件）
        3. 若在追踪列表 → 计算当前文件哈希
        4. 比对当前哈希与记录哈希
        5. 哈希一致 → 返回 is_consistent=True
        6. 哈希不一致 → 返回 is_consistent=False
        
        Args:
            file_path: 文件路径
            
        Returns:
            VersionCheckResult: 校验结果
        """
        normalized_path = self._normalize_path(file_path)
        
        # 检查是否在追踪列表中
        if normalized_path not in self._versions:
            # 未追踪的文件，允许写入（可能是新文件或未读取过的文件）
            return VersionCheckResult(
                is_consistent=True,
                file_path=file_path,
                recorded_hash=None,
                current_hash=None,
                file_exists=Path(file_path).exists(),
                was_tracked=False
            )
        
        recorded_hash = self._versions[normalized_path]
        
        # 计算当前文件哈希
        current_hash = compute_file_hash(file_path)
        file_exists = current_hash is not None
        
        # 文件被删除的情况
        if not file_exists:
            return VersionCheckResult(
                is_consistent=False,
                file_path=file_path,
                recorded_hash=recorded_hash,
                current_hash=None,
                file_exists=False,
                was_tracked=True
            )
        
        # 比对哈希
        is_consistent = (recorded_hash == current_hash)
        
        return VersionCheckResult(
            is_consistent=is_consistent,
            file_path=file_path,
            recorded_hash=recorded_hash,
            current_hash=current_hash,
            file_exists=True,
            was_tracked=True
        )
    
    def clear(self) -> None:
        """清空追踪记录"""
        self._versions.clear()
    
    def get_tracked_files(self) -> List[str]:
        """
        获取已追踪的文件列表
        
        Returns:
            List[str]: 文件路径列表
        """
        return list(self._versions.keys())
    
    def get_version(self, file_path: str) -> Optional[str]:
        """
        获取文件的记录哈希
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[str]: 记录的哈希值，未追踪时返回 None
        """
        normalized_path = self._normalize_path(file_path)
        return self._versions.get(normalized_path)
    
    def is_tracked(self, file_path: str) -> bool:
        """
        检查文件是否在追踪列表中
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否在追踪列表中
        """
        normalized_path = self._normalize_path(file_path)
        return normalized_path in self._versions
    
    @property
    def tracked_count(self) -> int:
        """获取追踪的文件数量"""
        return len(self._versions)
    
    def _normalize_path(self, file_path: str) -> str:
        """
        规范化文件路径
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 规范化后的路径
        """
        # 使用 Path 规范化路径，确保不同写法的同一路径使用同一个键
        try:
            return str(Path(file_path).resolve())
        except (OSError, ValueError):
            # 路径无效时返回原始路径
            return file_path
    
    def __repr__(self) -> str:
        return f"FileVersionTracker(tracked_files={self.tracked_count})"


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "VersionCheckResult",
    "FileVersionTracker",
]
