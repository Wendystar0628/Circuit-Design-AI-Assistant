# Orphaned Data Cleaner Service - Stateless Orphan File Cleanup
"""
孤儿数据清理服务 - 无状态孤儿文件清理

职责：
- 扫描并清理不再被 GraphState 历史引用的孤儿数据文件
- 在撤回操作后执行，确保无"幽灵数据"残留

设计原则：
- 无状态设计，不持有内存数据
- 只删除明确为孤儿的文件，保守策略
- 删除前记录日志，支持审计

清理范围：
- .circuit_ai/sim_results/ - 仿真结果文件
- .circuit_ai/conversations/ - 对话历史文件

不清理的目录：
- .circuit_ai/snapshots/ - 由 SnapshotService 管理
- .circuit_ai/checkpoints.sqlite3 - 由 LangGraph 管理
- .circuit_ai/design_goals.json - 单文件覆盖更新

被调用方：
- undo_node: 撤回操作后清理孤儿数据

使用示例：
    from domain.services import orphaned_data_cleaner
    
    # 执行清理
    result = orphaned_data_cleaner.cleanup(
        project_root="/path/to/project",
        checkpointer=sqlite_saver,
        thread_id="session_001"
    )
    
    print(f"Deleted {result.deleted_count} files, freed {result.freed_bytes} bytes")
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Any

logger = logging.getLogger(__name__)

# 参与孤儿清理的目录（相对于 .circuit_ai/）
CLEANABLE_DIRS = [
    "sim_results",
    "conversations",
]

# GraphState 中的文件指针字段名
FILE_POINTER_FIELDS = [
    "sim_result_path",
    "design_goals_path",
]


@dataclass
class CleanupResult:
    """清理结果"""

    deleted_files: List[str] = field(default_factory=list)
    """已删除的文件路径列表"""

    deleted_count: int = 0
    """删除文件数量"""

    freed_bytes: int = 0
    """释放的磁盘空间（字节）"""

    errors: List[str] = field(default_factory=list)
    """删除过程中的错误信息"""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "deleted_files": self.deleted_files,
            "deleted_count": self.deleted_count,
            "freed_bytes": self.freed_bytes,
            "errors": self.errors,
        }


def cleanup(
    project_root: str,
    checkpointer: Any,
    thread_id: str,
    *,
    dry_run: bool = False,
) -> CleanupResult:
    """
    执行孤儿数据清理

    Args:
        project_root: 项目根目录路径
        checkpointer: LangGraph SqliteSaver 实例
        thread_id: 线程/会话 ID
        dry_run: 是否为试运行模式（仅扫描不删除）

    Returns:
        CleanupResult: 清理结果
    """
    result = CleanupResult()

    try:
        # 1. 收集所有检查点引用的文件路径
        referenced_paths = collect_referenced_paths(checkpointer, thread_id)
        logger.debug(f"Collected {len(referenced_paths)} referenced paths")

        # 2. 扫描孤儿文件
        orphaned_files = scan_orphaned_files(project_root, referenced_paths)
        logger.debug(f"Found {len(orphaned_files)} orphaned files")

        if not orphaned_files:
            return result

        # 3. 删除孤儿文件（或仅记录）
        if dry_run:
            result.deleted_files = orphaned_files
            result.deleted_count = len(orphaned_files)
            # 计算大小但不删除
            for file_path in orphaned_files:
                try:
                    result.freed_bytes += Path(file_path).stat().st_size
                except Exception:
                    pass
        else:
            deleted_count, freed_bytes, errors = delete_files(orphaned_files)
            result.deleted_files = [f for f in orphaned_files if f not in errors]
            result.deleted_count = deleted_count
            result.freed_bytes = freed_bytes
            result.errors = errors

        logger.info(
            f"Orphan cleanup: deleted={result.deleted_count}, "
            f"freed={result.freed_bytes} bytes, errors={len(result.errors)}"
        )

    except Exception as e:
        error_msg = f"Cleanup failed: {e}"
        logger.error(error_msg)
        result.errors.append(error_msg)

    return result


def collect_referenced_paths(
    checkpointer: Any,
    thread_id: str,
) -> Set[str]:
    """
    从所有检查点收集被引用的文件路径

    Args:
        checkpointer: LangGraph SqliteSaver 实例
        thread_id: 线程/会话 ID

    Returns:
        Set[str]: 被引用的文件路径集合（相对路径）
    """
    referenced = set()

    try:
        # 获取所有检查点
        config = {"configurable": {"thread_id": thread_id}}
        checkpoints = list(checkpointer.list(config))

        for checkpoint_tuple in checkpoints:
            # checkpoint_tuple 结构: (config, checkpoint, metadata, ...)
            if len(checkpoint_tuple) >= 2:
                checkpoint = checkpoint_tuple[1]
                if checkpoint and hasattr(checkpoint, "channel_values"):
                    state = checkpoint.channel_values

                    # 提取文件指针字段
                    for field_name in FILE_POINTER_FIELDS:
                        if field_name in state:
                            path = state[field_name]
                            if path and isinstance(path, str):
                                # 标准化路径
                                normalized = _normalize_path(path)
                                if normalized:
                                    referenced.add(normalized)

    except Exception as e:
        logger.warning(f"Failed to collect referenced paths: {e}")

    return referenced


def scan_orphaned_files(
    project_root: str,
    referenced_paths: Set[str],
) -> List[str]:
    """
    扫描孤儿文件

    Args:
        project_root: 项目根目录路径
        referenced_paths: 被引用的文件路径集合

    Returns:
        List[str]: 孤儿文件的完整路径列表
    """
    orphaned = []
    root = Path(project_root).resolve()
    circuit_ai_dir = root / ".circuit_ai"

    if not circuit_ai_dir.exists():
        return orphaned

    for dir_name in CLEANABLE_DIRS:
        target_dir = circuit_ai_dir / dir_name

        if not target_dir.exists():
            continue

        for file_path in target_dir.iterdir():
            if not file_path.is_file():
                continue

            # 计算相对路径
            try:
                rel_path = file_path.relative_to(root)
                rel_str = str(rel_path).replace("\\", "/")

                # 检查是否被引用
                if not _is_referenced(rel_str, referenced_paths):
                    orphaned.append(str(file_path))

            except ValueError:
                continue

    return orphaned


def delete_files(file_paths: List[str]) -> tuple:
    """
    删除文件

    Args:
        file_paths: 要删除的文件路径列表

    Returns:
        tuple: (deleted_count, freed_bytes, errors)
    """
    deleted_count = 0
    freed_bytes = 0
    errors = []

    for file_path in file_paths:
        try:
            path = Path(file_path)

            if not path.exists():
                continue

            # 安全检查：确保文件在清理范围内
            if not _is_in_cleanable_scope(path):
                errors.append(f"Skipped (out of scope): {file_path}")
                continue

            # 记录大小
            size = path.stat().st_size

            # 删除文件
            path.unlink()

            deleted_count += 1
            freed_bytes += size
            logger.debug(f"Deleted orphan file: {file_path}")

        except Exception as e:
            error_msg = f"Failed to delete {file_path}: {e}"
            logger.warning(error_msg)
            errors.append(error_msg)

    return deleted_count, freed_bytes, errors


def _normalize_path(path: str) -> Optional[str]:
    """
    标准化路径

    - 统一使用正斜杠
    - 移除开头的 ./ 或 /
    """
    if not path:
        return None

    # 统一分隔符
    normalized = path.replace("\\", "/")

    # 移除开头的 ./
    if normalized.startswith("./"):
        normalized = normalized[2:]

    # 移除开头的 /
    if normalized.startswith("/"):
        normalized = normalized[1:]

    return normalized if normalized else None


def _is_referenced(rel_path: str, referenced_paths: Set[str]) -> bool:
    """
    检查路径是否被引用

    支持多种匹配方式：
    - 完全匹配
    - 带 .circuit_ai/ 前缀匹配
    - 不带前缀匹配
    """
    if not rel_path:
        return False

    # 直接匹配
    if rel_path in referenced_paths:
        return True

    # 尝试添加/移除 .circuit_ai/ 前缀
    if rel_path.startswith(".circuit_ai/"):
        without_prefix = rel_path[len(".circuit_ai/"):]
        if without_prefix in referenced_paths:
            return True
    else:
        with_prefix = f".circuit_ai/{rel_path}"
        if with_prefix in referenced_paths:
            return True

    return False


def _is_in_cleanable_scope(path: Path) -> bool:
    """
    检查文件是否在可清理范围内

    安全机制：防止误删非清理范围的文件
    """
    path_str = str(path).replace("\\", "/")

    for dir_name in CLEANABLE_DIRS:
        if f"/.circuit_ai/{dir_name}/" in path_str:
            return True
        if f"\\.circuit_ai\\{dir_name}\\" in str(path):
            return True

    return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CleanupResult",
    "cleanup",
    "collect_referenced_paths",
    "scan_orphaned_files",
    "delete_files",
    "CLEANABLE_DIRS",
    "FILE_POINTER_FIELDS",
]
