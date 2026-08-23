# Snapshot Service - Stateless Full Snapshot Management
"""
全量快照服务 - 无状态项目文件快照管理

职责：
- 提供项目文件的全量快照创建、恢复、清理功能
- 支持撤回操作的文件级回滚

设计原则：
- 使用 shutil.copytree 实现全量拷贝，依赖标准库的可靠性
- 无状态设计，不持有内存数据
- 简单的保留策略：只保留最近 N 个快照（默认 10 个）

⚠️ 接口层级说明：
- 同步方法（create_snapshot, restore_snapshot 等）是底层接口
- 异步方法（create_snapshot_async, restore_snapshot_async 等）是应用层接口
- 事件循环中的调用方必须使用异步方法，避免阻塞 UI
- 异步方法通过 asyncio.to_thread() 将 shutil 操作卸载到线程池

存储路径：
- 快照目录：{project_root}/.circuit_ai/snapshots/{snapshot_id}/
- 每个快照是项目文件的完整副本

忽略规则：
- .circuit_ai/snapshots/ - 避免递归快照
- __pycache__/ - Python 缓存
- .git/ - Git 仓库
- *.pyc - 编译文件
- simulation_results/ - 仿真结果 bundle（可重新生成）
- .venv/ / venv/ / node_modules/ - 本地依赖（永不因恢复而删除）

被调用方：
- user_checkpoint_node: 用户确认时创建快照（使用 create_snapshot_async）
- undo_node: 撤回时恢复快照（使用 restore_snapshot_async）

使用示例：
    from domain.services import snapshot_service
    
    # ❌ 错误：在异步上下文中使用同步方法
    path = snapshot_service.create_snapshot(project_root, snapshot_id)  # 阻塞
    
    # ✅ 正确：使用异步方法
    path = await snapshot_service.create_snapshot_async(project_root, snapshot_id)
"""

import asyncio
import difflib
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from domain.llm.agent.utils.edit_diff import generate_diff_string

# 快照目录相对路径
SNAPSHOTS_DIR = ".circuit_ai/snapshots"

# Snapshot-owned metadata.  It is deliberately part of the ignore policy so a
# project file with the same name can never be mistaken for restore metadata.
SNAPSHOT_METADATA_FILE = ".snapshot_meta.json"
SNAPSHOT_RESTORE_MANIFEST_VERSION = 1

# 默认保留快照数量
DEFAULT_KEEP_COUNT = 10

# 快照时忽略的模式
IGNORE_PATTERNS = [
    ".circuit_ai/snapshots",  # 避免递归快照
    ".circuit_ai/vector_store",  # RAG 向量库可重建
    ".circuit_ai/rag_storage",  # RAG 索引元数据可重建
    ".circuit_ai/temp",  # 对话/仿真临时附件不属于工作区状态
    "simulation_results",     # 仿真 bundle 可重新生成
    "__pycache__",
    ".git",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    "*.egg-info",
    ".venv",
    "venv",
    "node_modules",
    SNAPSHOT_METADATA_FILE,
]

TEXT_PREVIEW_SUFFIXES = {
    "",
    ".py",
    ".json",
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".cir",
    ".sp",
    ".net",
    ".csv",
    ".tsv",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".kt",
    ".rs",
    ".go",
    ".sh",
    ".bat",
    ".ps1",
    ".log",
    ".gitignore",
}


@dataclass
class SnapshotInfo:
    """快照信息"""

    snapshot_id: str
    """快照标识"""

    timestamp: str
    """创建时间（ISO 格式）"""

    size_bytes: int
    """快照大小（字节）"""

    file_count: int
    """文件数量"""

    path: str
    """快照路径"""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "path": self.path,
        }


@dataclass(frozen=True)
class SnapshotFileChange:
    relative_path: str
    change_type: str
    summary: str
    added_lines: int
    deleted_lines: int
    diff_preview: str = ""
    is_text: bool = False
    current_revision: str = ""
    snapshot_revision: str = ""


@dataclass(frozen=True)
class SnapshotRestorePreview:
    snapshot_id: str
    changed_files: List[SnapshotFileChange]
    changed_file_count: int
    total_added_lines: int
    total_deleted_lines: int


@dataclass(frozen=True)
class SnapshotRestoreScope:
    """Limit which paths a restore may mutate.

    Paths outside ``protected_roots`` remain part of the normal full-project
    restore.  Inside a protected root only ``allowed_paths`` (and their
    descendants) may be changed; ancestors are traversed without being
    replaced or removed.  Conversation rollback uses this to restore its own
    session files without time-travelling every other session and global
    application state.
    """

    protected_roots: Tuple[str, ...] = ()
    allowed_paths: Tuple[str, ...] = ()


@dataclass(frozen=True)
class _SnapshotRestorePolicy:
    excluded_patterns: Tuple[str, ...]
    allow_deletions: bool


def create_snapshot(
    project_root: str,
    snapshot_id: str,
    *,
    ignore_patterns: Optional[List[str]] = None,
) -> str:
    """
    创建项目文件的全量快照

    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识（建议使用 iter_001 格式）
        ignore_patterns: 额外的忽略模式列表

    Returns:
        str: 快照目录的相对路径

    Raises:
        ValueError: snapshot_id 无效
        OSError: 磁盘空间不足或权限问题
        RuntimeError: 快照创建失败
    """
    if not snapshot_id or not snapshot_id.strip():
        raise ValueError("Snapshot ID cannot be empty")

    # 清理 snapshot_id 中的非法字符
    safe_id = _sanitize_snapshot_id(snapshot_id)

    root = Path(project_root).resolve()
    snapshots_dir = _safe_snapshots_dir(root)
    snapshot_dir = snapshots_dir / safe_id

    # 检查快照是否已存在
    if snapshot_dir.exists():
        raise ValueError(f"Snapshot already exists: {safe_id}")

    # 预检和实际拷贝必须使用同一份捕获范围，否则可再生的大型
    # 缓存仍会让每次对话发送遍历整棵目录，甚至误报磁盘空间不足。
    all_patterns = IGNORE_PATTERNS.copy()
    if ignore_patterns:
        all_patterns.extend(ignore_patterns)

    # 确保快照父目录存在
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)

    # 检查实际捕获范围所需的磁盘空间（粗略估计）
    _check_disk_space(root, snapshot_dir.parent, all_patterns)

    # 构建忽略函数
    ignore_func = _create_ignore_function(root, all_patterns)

    try:
        # 执行全量拷贝
        shutil.copytree(
            src=root,
            dst=snapshot_dir,
            ignore=ignore_func,
            dirs_exist_ok=False,
        )

        # 写入元数据
        _write_snapshot_metadata(
            snapshot_dir,
            safe_id,
            excluded_patterns=all_patterns,
        )

        return f"{SNAPSHOTS_DIR}/{safe_id}"

    except Exception as e:
        # 清理不完整的快照目录
        if snapshot_dir.exists() and not _is_link_like(snapshot_dir):
            try:
                _validate_no_link_like_tree(snapshot_dir, label="incomplete snapshot")
                shutil.rmtree(snapshot_dir)
            except Exception:
                # A raced-in reparse point is safer left behind for manual
                # inspection than followed during best-effort cleanup.
                pass
        raise RuntimeError(f"Failed to create snapshot: {e}") from e


def restore_snapshot(
    project_root: str,
    snapshot_id: str,
    *,
    backup_current: bool = True,
    scope: Optional[SnapshotRestoreScope] = None,
) -> None:
    """
    从快照恢复项目文件

    恢复策略：
    1. 如果 backup_current=True，先备份当前状态
    2. 仅删除捕获清单明确覆盖、但快照中不存在的路径
    3. 从快照复制文件到项目目录

    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识
        backup_current: 是否在恢复前备份当前状态
        scope: 可选的局部恢复边界；预览与恢复必须使用同一实例

    Raises:
        ValueError: 快照不存在
        RuntimeError: 恢复失败
    """
    safe_id = _sanitize_snapshot_id(snapshot_id)
    root = Path(project_root).resolve()
    snapshots_dir = _safe_snapshots_dir(root)
    snapshot_dir = snapshots_dir / safe_id

    if not snapshot_dir.exists():
        raise ValueError(f"Snapshot not found: {safe_id}")

    # Reject a redirecting/corrupt source before even creating the safety
    # backup.  Otherwise the failed restore would immediately replay that
    # backup and needlessly replace live files (including breaking legitimate
    # hardlink topology) despite never having started the target restore.
    _validate_no_link_like_tree(snapshot_dir, label="snapshot restore source")

    # 备份当前状态（可选）。安全备份是破坏性恢复的先决条件；
    # 创建失败时必须在触碰目标工作区之前中止。
    backup_id = None
    backup_path: Optional[Path] = None
    if backup_current:
        backup_id = f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        backup_path = (snapshots_dir / backup_id).resolve()
        try:
            create_snapshot(project_root, backup_id)
        except Exception as backup_error:
            raise RuntimeError(
                "Failed to create safety backup; restore aborted before "
                f"modifying the project: {backup_error}"
            ) from backup_error

    restore_completed = False
    rollback_completed = False
    try:
        # 恢复文件
        _restore_files_from_snapshot(root, snapshot_dir, scope=scope)
        restore_completed = True

    except Exception as restore_error:
        # 恢复失败，尝试从备份恢复
        if backup_id and backup_path is not None:
            try:
                _restore_files_from_snapshot(
                    root,
                    backup_path,
                    scope=scope,
                )
                rollback_completed = True
            except Exception as rollback_error:
                # 这是唯一可用的恢复点，不得在 finally 中删除。
                # 绝对路径必须出现在异常中，便于人工恢复。
                raise RuntimeError(
                    "Failed to restore snapshot and failed to roll back the "
                    "partial restore. Safety backup preserved at: "
                    f"{backup_path}. Restore error: {restore_error}; "
                    f"rollback error: {rollback_error}"
                ) from rollback_error

            raise RuntimeError(
                f"Failed to restore snapshot: {restore_error}. "
                "The project was rolled back from its safety backup."
            ) from restore_error

        raise RuntimeError(f"Failed to restore snapshot: {restore_error}") from restore_error

    finally:
        # 只有目标恢复完成，或失败后已确认回滚成功，才能
        # 清理安全备份。双重失败时保留它供人工恢复。
        if backup_id and (restore_completed or rollback_completed):
            try:
                delete_snapshot(project_root, backup_id)
            except Exception:
                pass  # 清理失败只会留下可恢复备份，不会破坏已完成的结果


def list_snapshots(project_root: str) -> List[SnapshotInfo]:
    """
    列出所有快照

    Args:
        project_root: 项目根目录路径

    Returns:
        List[SnapshotInfo]: 快照信息列表，按时间倒序排列
    """
    root = Path(project_root).resolve()
    snapshots_dir = _safe_snapshots_dir(root)

    if not snapshots_dir.exists():
        return []

    snapshots = []
    for item in snapshots_dir.iterdir():
        if (
            not _is_link_like(item)
            and item.is_dir()
            and not item.name.startswith("_")
        ):
            info = _get_snapshot_info(item)
            if info:
                snapshots.append(info)

    # 按时间倒序排列
    snapshots.sort(key=lambda x: x.timestamp, reverse=True)
    return snapshots


def delete_snapshot(project_root: str, snapshot_id: str) -> None:
    """
    删除指定快照

    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识

    Raises:
        ValueError: 快照不存在
        OSError: 删除失败
    """
    safe_id = _sanitize_snapshot_id(snapshot_id)
    root = Path(project_root).resolve()
    snapshot_dir = _safe_snapshots_dir(root) / safe_id

    if not snapshot_dir.exists():
        raise ValueError(f"Snapshot not found: {safe_id}")

    if _is_link_like(snapshot_dir):
        raise RuntimeError("Refusing to delete link-like snapshot storage")
    _validate_no_link_like_tree(snapshot_dir, label="snapshot delete source")
    shutil.rmtree(snapshot_dir)


def cleanup_old_snapshots(
    project_root: str,
    keep_count: int = DEFAULT_KEEP_COUNT,
) -> int:
    """
    清理旧快照，只保留最近 N 个

    Args:
        project_root: 项目根目录路径
        keep_count: 保留的快照数量

    Returns:
        int: 删除的快照数量
    """
    if keep_count < 0:
        keep_count = 0

    snapshots = list_snapshots(project_root)

    # 跳过以 _ 开头的临时快照
    regular_snapshots = [s for s in snapshots if not s.snapshot_id.startswith("_")]

    if len(regular_snapshots) <= keep_count:
        return 0

    # 删除多余的快照（保留最新的 keep_count 个）
    to_delete = regular_snapshots[keep_count:]
    deleted_count = 0

    for snapshot in to_delete:
        try:
            delete_snapshot(project_root, snapshot.snapshot_id)
            deleted_count += 1
        except Exception:
            pass  # 删除失败继续处理其他快照

    return deleted_count


def get_snapshot_info(
    project_root: str,
    snapshot_id: str,
) -> Optional[SnapshotInfo]:
    """
    获取指定快照的信息

    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识

    Returns:
        Optional[SnapshotInfo]: 快照信息，不存在时返回 None
    """
    safe_id = _sanitize_snapshot_id(snapshot_id)
    root = Path(project_root).resolve()
    snapshot_dir = _safe_snapshots_dir(root) / safe_id

    if not snapshot_dir.exists():
        return None

    return _get_snapshot_info(snapshot_dir)


def preview_restore_snapshot(
    project_root: str,
    snapshot_id: str,
    *,
    scope: Optional[SnapshotRestoreScope] = None,
) -> SnapshotRestorePreview:
    safe_id = _sanitize_snapshot_id(snapshot_id)
    root = Path(project_root).resolve()
    snapshot_dir = _safe_snapshots_dir(root) / safe_id

    if not snapshot_dir.exists():
        raise ValueError(f"Snapshot not found: {safe_id}")

    return _build_restore_preview(root, snapshot_dir, safe_id, scope=scope)


def snapshot_exists(project_root: str, snapshot_id: str) -> bool:
    """
    检查快照是否存在

    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识

    Returns:
        bool: 快照是否存在
    """
    safe_id = _sanitize_snapshot_id(snapshot_id)
    root = Path(project_root).resolve()
    snapshot_dir = _safe_snapshots_dir(root) / safe_id
    return snapshot_dir.exists()


def get_snapshots_dir(project_root: str) -> str:
    """
    获取快照目录路径

    Args:
        project_root: 项目根目录路径

    Returns:
        str: 快照目录的完整路径
    """
    root = Path(project_root).resolve()
    return str(_safe_snapshots_dir(root))


# ============================================================
# 内部辅助函数
# ============================================================


def _sanitize_snapshot_id(snapshot_id: str) -> str:
    """清理快照 ID，移除非法字符"""
    # 只保留字母、数字、下划线、连字符
    safe_chars = []
    for c in snapshot_id.strip():
        if c.isalnum() or c in "_-":
            safe_chars.append(c)
    return "".join(safe_chars) or "snapshot"


def _is_link_like(path: Path) -> bool:
    """Return whether ``path`` may redirect I/O outside its lexical tree.

    On Windows an NTFS junction is a directory and is *not* reported by
    ``Path.is_symlink()``.  Treat every junction and every reparse point as a
    protected link-like node as well.  Snapshot code must never traverse,
    overwrite, or delete through one of these paths.
    """
    try:
        if path.is_symlink():
            return True

        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True

        path_stat = path.lstat()
        file_attributes = int(getattr(path_stat, "st_file_attributes", 0) or 0)
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
        return bool(reparse_flag and file_attributes & reparse_flag)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(f"Failed to inspect snapshot path {path}: {exc}") from exc


def _safe_snapshots_dir(root: Path) -> Path:
    """Return snapshot storage only when none of its ancestors redirects."""
    current = root
    for part in Path(SNAPSHOTS_DIR).parts:
        current = current / part
        if _is_link_like(current):
            raise RuntimeError(
                f"Snapshot storage contains a link-like path: {current}"
            )
    return current


def _validate_no_link_like_tree(root: Path, *, label: str) -> None:
    """Fail before mutation when a source tree contains a redirecting node."""
    if _is_link_like(root):
        raise RuntimeError(f"{label} is link-like: {root}")
    if not root.is_dir():
        raise RuntimeError(f"{label} is not a directory: {root}")

    for directory, dir_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        if directory_path != root and _is_link_like(directory_path):
            raise RuntimeError(f"{label} contains a link-like path: {directory_path}")
        for name in [*dir_names, *file_names]:
            item_path = directory_path / name
            if _is_link_like(item_path):
                raise RuntimeError(
                    f"{label} contains a link-like path: {item_path}"
                )


def _create_ignore_function(root: Path, patterns: List[str]):
    """
    创建忽略函数

    结合 shutil.ignore_patterns 和自定义路径匹配
    """
    def ignore_func(directory: str, contents: List[str]) -> set:
        ignored = set()
        dir_path = Path(directory)
        for name in contents:
            item_path = dir_path / name
            if _is_link_like(item_path):
                ignored.add(name)
                continue
            try:
                relative_path = item_path.relative_to(root)
            except ValueError:
                continue
            if _matches_any_snapshot_pattern(relative_path, patterns):
                ignored.add(name)

        return ignored

    return ignore_func


def _matches_any_snapshot_pattern(
    relative_path: Path,
    patterns: List[str] | Tuple[str, ...],
) -> bool:
    return any(
        _matches_snapshot_pattern(relative_path, pattern)
        for pattern in patterns
        if str(pattern or "").strip()
    )


def _matches_snapshot_pattern(relative_path: Path, pattern: str) -> bool:
    """Use the same path rules during capture, preview, and restore.

    A slash-containing pattern is project-root relative.  A basename pattern
    applies at any depth, which preserves the historical behavior for nested
    ``node_modules``/``__pycache__`` directories and compiled files.
    """
    normalized_pattern = str(pattern or "").replace("\\", "/").strip("/")
    if not normalized_pattern:
        return False

    relative_posix = relative_path.as_posix().strip("/")
    parts = tuple(part for part in relative_path.parts if part not in {"", "."})

    if "/" in normalized_pattern:
        if any(char in normalized_pattern for char in "*?["):
            return fnmatch.fnmatchcase(relative_posix, normalized_pattern)
        return (
            relative_posix == normalized_pattern
            or relative_posix.startswith(f"{normalized_pattern}/")
        )

    return any(fnmatch.fnmatchcase(part, normalized_pattern) for part in parts)


def _load_snapshot_restore_policy(snapshot_dir: Path) -> _SnapshotRestorePolicy:
    """Load the capture-time policy used to decide safe deletions.

    Legacy or damaged snapshots remain useful for copying old file contents,
    but are intentionally non-destructive because their custom ignore policy
    cannot be reconstructed safely.
    """
    excluded_patterns = list(IGNORE_PATTERNS)
    allow_deletions = False
    metadata_file = snapshot_dir / SNAPSHOT_METADATA_FILE

    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        manifest = metadata.get("restore_manifest", {})
        if (
            isinstance(manifest, dict)
            and manifest.get("version") == SNAPSHOT_RESTORE_MANIFEST_VERSION
            and manifest.get("captured_scope") == "."
            and manifest.get("capture_complete") is True
        ):
            stored_patterns = manifest.get("excluded_patterns", [])
            if isinstance(stored_patterns, list) and all(
                isinstance(item, str) for item in stored_patterns
            ):
                excluded_patterns.extend(stored_patterns)
                allow_deletions = True
    except Exception:
        # Copy-only restore is the safe fallback when metadata is absent or
        # corrupt.  In particular, never infer that an uncaptured path should
        # be deleted.
        pass

    return _SnapshotRestorePolicy(
        excluded_patterns=tuple(dict.fromkeys(excluded_patterns)),
        allow_deletions=allow_deletions,
    )


def _check_disk_space(
    source: Path,
    dest_parent: Path,
    patterns: List[str] | Tuple[str, ...],
) -> None:
    """
    检查磁盘空间是否足够

    粗略估计：要求可用空间至少是源目录大小的 1.5 倍
    """
    try:
        # Never follow a symlink/junction/reparse point while estimating.  Use
        # the capture policy top-down too, so excluded dependency/cache trees
        # are neither traversed nor counted.
        source_size = 0
        for directory, dir_names, file_names in os.walk(
            source,
            topdown=True,
            followlinks=False,
        ):
            directory_path = Path(directory)
            retained_dirs = []
            for name in dir_names:
                directory_item = directory_path / name
                if _is_link_like(directory_item):
                    continue
                relative_path = directory_item.relative_to(source)
                if _matches_any_snapshot_pattern(relative_path, patterns):
                    continue
                retained_dirs.append(name)
            dir_names[:] = retained_dirs

            for name in file_names:
                file_path = directory_path / name
                if _is_link_like(file_path):
                    continue
                relative_path = file_path.relative_to(source)
                if _matches_any_snapshot_pattern(relative_path, patterns):
                    continue
                source_size += file_path.stat().st_size

        # 获取目标磁盘可用空间
        disk_usage = shutil.disk_usage(dest_parent)
        available = disk_usage.free

        # 要求至少 1.5 倍空间
        required = int(source_size * 1.5)

        if available < required:
            raise OSError(
                f"Insufficient disk space: need {required / 1024 / 1024:.1f}MB, "
                f"available {available / 1024 / 1024:.1f}MB"
            )
    except OSError:
        raise
    except Exception:
        # 无法检查时不阻止操作
        pass


def _write_snapshot_metadata(
    snapshot_dir: Path,
    snapshot_id: str,
    *,
    excluded_patterns: List[str],
) -> None:
    """写入快照元数据"""
    metadata = {
        "snapshot_id": snapshot_id,
        "timestamp": datetime.now().isoformat(),
        "created_by": "snapshot_service",
        "restore_manifest": {
            "version": SNAPSHOT_RESTORE_MANIFEST_VERSION,
            "captured_scope": ".",
            "capture_complete": True,
            "excluded_patterns": list(dict.fromkeys(excluded_patterns)),
            "deletion_semantics": "missing_within_captured_scope",
        },
    }

    metadata_file = snapshot_dir / SNAPSHOT_METADATA_FILE
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _get_snapshot_info(snapshot_dir: Path) -> Optional[SnapshotInfo]:
    """获取快照信息"""
    if _is_link_like(snapshot_dir) or not snapshot_dir.is_dir():
        return None

    # 读取元数据
    metadata_file = snapshot_dir / SNAPSHOT_METADATA_FILE
    timestamp = ""
    snapshot_id = snapshot_dir.name

    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            timestamp = metadata.get("timestamp", "")
            snapshot_id = metadata.get("snapshot_id", snapshot_dir.name)
        except Exception:
            pass

    # 如果没有元数据，使用目录修改时间
    if not timestamp:
        mtime = snapshot_dir.stat().st_mtime
        timestamp = datetime.fromtimestamp(mtime).isoformat()

    # 计算大小和文件数
    size_bytes = 0
    file_count = 0

    try:
        for directory, dir_names, file_names in os.walk(
            snapshot_dir,
            topdown=True,
            followlinks=False,
        ):
            directory_path = Path(directory)
            dir_names[:] = [
                name
                for name in dir_names
                if not _is_link_like(directory_path / name)
            ]
            for name in file_names:
                file_path = directory_path / name
                if _is_link_like(file_path):
                    continue
                size_bytes += file_path.stat().st_size
                file_count += 1
    except Exception:
        pass

    return SnapshotInfo(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        size_bytes=size_bytes,
        file_count=file_count,
        path=str(snapshot_dir),
    )


def _build_restore_preview(
    root: Path,
    snapshot_dir: Path,
    snapshot_id: str,
    *,
    scope: Optional[SnapshotRestoreScope] = None,
) -> SnapshotRestorePreview:
    _validate_no_link_like_tree(snapshot_dir, label="snapshot preview source")
    policy = _load_snapshot_restore_policy(snapshot_dir)
    current_files = _collect_restore_files(root, policy=policy, scope=scope)
    snapshot_files = _collect_restore_files(
        snapshot_dir,
        policy=policy,
        scope=scope,
    )

    changes: List[SnapshotFileChange] = []
    total_added_lines = 0
    total_deleted_lines = 0

    for relative_path in sorted(
        set(current_files.keys()) | set(snapshot_files.keys()),
        key=lambda path: path.as_posix(),
    ):
        current_path = current_files.get(relative_path)
        snapshot_path = snapshot_files.get(relative_path)

        # Without a complete capture manifest, absence from a legacy snapshot
        # is not evidence that the live file should be deleted.  Preview and
        # restore deliberately share this non-destructive fallback.
        if current_path is not None and snapshot_path is None and not policy.allow_deletions:
            continue

        if current_path and snapshot_path and _files_are_equal(current_path, snapshot_path):
            continue

        change = _build_snapshot_file_change(
            relative_path,
            current_path=current_path,
            snapshot_path=snapshot_path,
        )
        changes.append(change)
        total_added_lines += change.added_lines
        total_deleted_lines += change.deleted_lines

    return SnapshotRestorePreview(
        snapshot_id=snapshot_id,
        changed_files=changes,
        changed_file_count=len(changes),
        total_added_lines=total_added_lines,
        total_deleted_lines=total_deleted_lines,
    )


def _collect_restore_files(
    base_dir: Path,
    *,
    policy: _SnapshotRestorePolicy,
    scope: Optional[SnapshotRestoreScope],
) -> Dict[Path, Path]:
    collected: Dict[Path, Path] = {}
    if not base_dir.exists():
        return collected
    if _is_link_like(base_dir):
        raise RuntimeError(f"Restore tree root is link-like: {base_dir}")

    # Top-down os.walk lets us prune excluded trees.  Previewing a project must
    # not descend into potentially huge or sensitive .venv/node_modules/.git
    # directories only to discard their files afterwards.
    for directory, dir_names, file_names in os.walk(base_dir, topdown=True):
        directory_path = Path(directory)
        relative_dir = directory_path.relative_to(base_dir)

        kept_directories: List[str] = []
        for name in dir_names:
            item_path = directory_path / name
            if _is_link_like(item_path):
                continue
            relative_path = relative_dir / name
            mode = _get_restore_path_mode(relative_path, policy=policy, scope=scope)
            if mode != "protected":
                kept_directories.append(name)
        dir_names[:] = kept_directories

        for name in file_names:
            item_path = directory_path / name
            if _is_link_like(item_path):
                continue
            relative_path = relative_dir / name
            if relative_path == Path(SNAPSHOT_METADATA_FILE):
                continue
            if _get_restore_path_mode(relative_path, policy=policy, scope=scope) != "included":
                continue
            collected[relative_path] = item_path

    return collected


def _files_are_equal(first_path: Path, second_path: Path) -> bool:
    if _is_link_like(first_path) or _is_link_like(second_path):
        raise RuntimeError("Refusing to compare a link-like restore path")
    try:
        return first_path.read_bytes() == second_path.read_bytes()
    except Exception:
        return False


def _build_snapshot_file_change(
    relative_path: Path,
    *,
    current_path: Optional[Path],
    snapshot_path: Optional[Path],
) -> SnapshotFileChange:
    relative_str = relative_path.as_posix()

    if current_path and snapshot_path:
        change_type = "modified"
        summary = "将恢复为快照中的版本"
    elif snapshot_path:
        change_type = "added"
        summary = "将恢复当前缺失的文件"
    else:
        change_type = "deleted"
        summary = "将删除该文件"

    current_text, current_is_text = _read_text_preview(current_path)
    snapshot_text, snapshot_is_text = _read_text_preview(snapshot_path)
    text_flags = []
    if current_path is not None:
        text_flags.append(current_is_text)
    if snapshot_path is not None:
        text_flags.append(snapshot_is_text)
    is_text = all(text_flags) if text_flags else False

    added_lines = 0
    deleted_lines = 0
    diff_preview = ""

    if is_text:
        current_content = current_text or ""
        snapshot_content = snapshot_text or ""
        added_lines, deleted_lines = _calculate_line_changes(
            current_content,
            snapshot_content,
        )
        diff_preview = _truncate_diff_preview(
            generate_diff_string(
                current_content,
                snapshot_content,
                context_lines=3,
            ).diff
        )

    return SnapshotFileChange(
        relative_path=relative_str,
        change_type=change_type,
        summary=summary,
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        diff_preview=diff_preview,
        is_text=is_text,
        current_revision=_file_revision(current_path),
        snapshot_revision=_file_revision(snapshot_path),
    )


def _read_text_preview(path: Optional[Path]) -> Tuple[str, bool]:
    if path is None or not path.exists():
        return "", True
    if _is_link_like(path):
        raise RuntimeError(f"Refusing to preview a link-like path: {path}")

    try:
        raw = path.read_bytes()
    except Exception:
        return "", False

    if b"\x00" in raw:
        return "", False

    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return _normalize_preview_text(raw.decode(encoding)), True
        except UnicodeError:
            continue

    if path.suffix.lower() in TEXT_PREVIEW_SUFFIXES:
        return _normalize_preview_text(raw.decode("utf-8", errors="replace")), True

    return "", False


def _file_revision(path: Optional[Path]) -> str:
    """Return an exact content identity for restore-plan validation."""
    if path is None:
        return "missing"
    if _is_link_like(path):
        raise RuntimeError(f"Refusing to fingerprint a link-like path: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fingerprint restore path {path}: {exc}"
        ) from exc
    return f"sha256:{digest.hexdigest()}"


def _normalize_preview_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _calculate_line_changes(old_content: str, new_content: str) -> Tuple[int, int]:
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

    added_lines = 0
    deleted_lines = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "insert"}:
            added_lines += j2 - j1
        if tag in {"replace", "delete"}:
            deleted_lines += i2 - i1

    return added_lines, deleted_lines


def _truncate_diff_preview(diff_text: str, *, max_chars: int = 20000) -> str:
    if len(diff_text) <= max_chars:
        return diff_text
    return f"{diff_text[:max_chars]}\n...\n[diff truncated]"


def _restore_files_from_snapshot(
    root: Path,
    snapshot_dir: Path,
    *,
    scope: Optional[SnapshotRestoreScope] = None,
) -> None:
    """
    从快照恢复文件到项目目录

    策略：
    1. 删除当前项目中快照不存在的可恢复文件
    2. 用快照内容覆盖当前项目文件
    3. 保留内部快照存储目录等受保护路径
    """
    # Validate the complete source before touching the destination.  A
    # hand-edited/corrupt snapshot containing a junction must not cause even a
    # partial restore before the unsafe node is discovered.
    _validate_no_link_like_tree(snapshot_dir, label="snapshot restore source")
    policy = _load_snapshot_restore_policy(snapshot_dir)
    _sync_directory_from_snapshot(
        snapshot_dir,
        root,
        Path(),
        policy=policy,
        scope=scope,
    )


def _sync_directory_from_snapshot(
    source_dir: Optional[Path],
    dest_dir: Path,
    relative_dir: Path,
    *,
    policy: _SnapshotRestorePolicy,
    scope: Optional[SnapshotRestoreScope],
) -> None:
    if source_dir is not None and _is_link_like(source_dir):
        raise RuntimeError(f"Snapshot source directory is link-like: {source_dir}")
    if relative_dir != Path() and _is_link_like(dest_dir):
        # Live link-like nodes are outside the captured restore authority.
        # Preserve the link and, critically, never enumerate its target.
        return
    dest_dir.mkdir(parents=True, exist_ok=True)

    source_entries: Dict[str, Path] = {}
    if source_dir is not None and source_dir.is_dir():
        for item in source_dir.iterdir():
            if relative_dir == Path() and item.name == SNAPSHOT_METADATA_FILE:
                continue
            if _is_link_like(item):
                raise RuntimeError(f"Snapshot source path is link-like: {item}")
            source_entries[item.name] = item
    dest_entries = {item.name: item for item in dest_dir.iterdir()}

    for name, dest_item in dest_entries.items():
        if _is_link_like(dest_item):
            # Preserve redirecting live paths whether or not a snapshot entry
            # has the same lexical name.
            continue
        relative_path = relative_dir / name
        mode = _get_restore_path_mode(relative_path, policy=policy, scope=scope)
        if mode == "protected":
            continue
        if name in source_entries:
            continue

        if dest_item.is_dir():
            # Recursively remove only captured files.  A direct rmtree here
            # could erase an excluded nested node_modules/.venv directory.
            _sync_directory_from_snapshot(
                None,
                dest_item,
                relative_path,
                policy=policy,
                scope=scope,
            )
            if mode == "included" and policy.allow_deletions:
                try:
                    dest_item.rmdir()
                except OSError:
                    # Protected or excluded descendants intentionally keep the
                    # containing directory alive.
                    pass
            continue

        if mode == "included" and policy.allow_deletions:
            _remove_restore_path(dest_item)

    for name, source_item in source_entries.items():
        relative_path = relative_dir / name
        mode = _get_restore_path_mode(relative_path, policy=policy, scope=scope)
        if mode == "protected":
            continue

        dest_item = dest_dir / name
        try:
            if _is_link_like(source_item):
                raise RuntimeError("snapshot source links are not restorable")
            if _is_link_like(dest_item):
                # A link may have appeared after the destination enumeration.
                # Never replace it and never recurse through it.
                continue
            if source_item.is_dir():
                if dest_item.exists() and not dest_item.is_dir():
                    if mode == "traverse":
                        raise RuntimeError(
                            "protected restore ancestor is not a directory"
                        )
                    _remove_restore_path(dest_item)
                dest_item.mkdir(parents=True, exist_ok=True)
                _sync_directory_from_snapshot(
                    source_item,
                    dest_item,
                    relative_path,
                    policy=policy,
                    scope=scope,
                )
            elif mode == "traverse":
                # A traversal-only path is never itself replaced.
                continue
            else:
                if dest_item.exists() and dest_item.is_dir():
                    _sync_directory_from_snapshot(
                        None,
                        dest_item,
                        relative_path,
                        policy=policy,
                        scope=scope,
                    )
                    try:
                        dest_item.rmdir()
                    except OSError as exc:
                        raise RuntimeError(
                            "cannot replace directory containing protected files"
                        ) from exc
                _copy_restore_file_atomic(source_item, dest_item)
        except Exception as e:
            raise RuntimeError(f"Failed to restore {relative_path.as_posix()}: {e}") from e


def _get_restore_path_mode(
    relative_path: Path,
    *,
    policy: _SnapshotRestorePolicy,
    scope: Optional[SnapshotRestoreScope],
) -> str:
    """Return ``included``, ``traverse``, or ``protected`` for a path."""
    normalized = Path(*relative_path.parts) if relative_path.parts else Path()
    if _matches_any_snapshot_pattern(normalized, policy.excluded_patterns):
        return "protected"

    if scope is None or not scope.protected_roots:
        return "included"

    protected_roots = tuple(_normalized_relative_path(item) for item in scope.protected_roots)
    allowed_paths = tuple(_normalized_relative_path(item) for item in scope.allowed_paths)

    containing_root = next(
        (
            root
            for root in protected_roots
            if normalized == root or root in normalized.parents
        ),
        None,
    )
    if containing_root is None:
        return "included"

    for allowed_path in allowed_paths:
        if not (allowed_path == containing_root or containing_root in allowed_path.parents):
            continue
        if normalized == allowed_path or allowed_path in normalized.parents:
            return "included"
        if normalized in allowed_path.parents:
            return "traverse"

    return "protected"


def _normalized_relative_path(value: str) -> Path:
    normalized = str(value or "").replace("\\", "/").strip("/")
    path = Path(*[part for part in normalized.split("/") if part not in {"", "."}])
    if ".." in path.parts:
        raise ValueError("Restore scope paths must stay within the project root")
    return path


def _remove_restore_path(path: Path) -> None:
    if _is_link_like(path):
        raise RuntimeError(f"Refusing to remove link-like restore path: {path}")
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _copy_restore_file_atomic(source_path: Path, dest_path: Path) -> None:
    """Copy one restore file without writing through an existing hardlink.

    ``shutil.copy2(source, dest)`` opens and truncates ``dest`` in place.  If
    the project path is an NTFS/POSIX hardlink, that mutates every other name
    for the same inode, including names outside the project.  Write a fresh
    same-directory file completely, then atomically replace only the project
    directory entry instead.
    """
    if _is_link_like(source_path):
        raise RuntimeError(f"Snapshot source file is link-like: {source_path}")
    if _is_link_like(dest_path):
        raise RuntimeError(f"Restore destination is link-like: {dest_path}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{dest_path.name}.restore-",
        suffix=".tmp",
        dir=str(dest_path.parent),
    )
    os.close(file_descriptor)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source_path, temp_path)
        # Ensure the complete temporary content reaches the OS before the
        # atomic directory-entry replacement.
        # Windows' ``_commit`` (used by ``os.fsync``) requires a descriptor
        # opened with write access; ``rb+`` does not alter the copied content.
        with temp_path.open("rb+") as temp_file:
            os.fsync(temp_file.fileno())
        os.replace(temp_path, dest_path)
    finally:
        if temp_path.exists() and not _is_link_like(temp_path):
            temp_path.unlink()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SnapshotInfo",
    "SnapshotFileChange",
    "SnapshotRestorePreview",
    "SnapshotRestoreScope",
    "create_snapshot",
    "restore_snapshot",
    "list_snapshots",
    "delete_snapshot",
    "cleanup_old_snapshots",
    "get_snapshot_info",
    "preview_restore_snapshot",
    "snapshot_exists",
    "get_snapshots_dir",
    # 异步方法
    "create_snapshot_async",
    "restore_snapshot_async",
    "list_snapshots_async",
    "delete_snapshot_async",
    "cleanup_old_snapshots_async",
    # 常量
    "SNAPSHOTS_DIR",
    "SNAPSHOT_METADATA_FILE",
    "DEFAULT_KEEP_COUNT",
]


# ============================================================
# 异步包装方法（应用层接口）
# ============================================================

async def create_snapshot_async(
    project_root: str,
    snapshot_id: str,
    *,
    ignore_patterns: Optional[List[str]] = None,
) -> str:
    """
    异步创建项目文件的全量快照
    
    通过 asyncio.to_thread() 将 shutil.copytree 卸载到线程池，
    确保主线程（事件循环）不被阻塞，UI 保持响应。
    
    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识
        ignore_patterns: 额外的忽略模式列表
        
    Returns:
        str: 快照目录的相对路径
    """
    return await asyncio.to_thread(
        create_snapshot,
        project_root,
        snapshot_id,
        ignore_patterns=ignore_patterns
    )


async def restore_snapshot_async(
    project_root: str,
    snapshot_id: str,
    *,
    backup_current: bool = True,
    scope: Optional[SnapshotRestoreScope] = None,
) -> None:
    """
    异步从快照恢复项目文件
    
    通过 asyncio.to_thread() 将文件恢复操作卸载到线程池。
    
    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识
        backup_current: 是否在恢复前备份当前状态
        scope: 可选的局部恢复边界
    """
    return await asyncio.to_thread(
        restore_snapshot,
        project_root,
        snapshot_id,
        backup_current=backup_current,
        scope=scope,
    )


async def list_snapshots_async(project_root: str) -> List[SnapshotInfo]:
    """
    异步列出所有快照
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        List[SnapshotInfo]: 快照信息列表
    """
    return await asyncio.to_thread(list_snapshots, project_root)


async def delete_snapshot_async(project_root: str, snapshot_id: str) -> None:
    """
    异步删除指定快照
    
    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识
    """
    return await asyncio.to_thread(delete_snapshot, project_root, snapshot_id)


async def cleanup_old_snapshots_async(
    project_root: str,
    keep_count: int = DEFAULT_KEEP_COUNT,
) -> int:
    """
    异步清理旧快照
    
    Args:
        project_root: 项目根目录路径
        keep_count: 保留的快照数量
        
    Returns:
        int: 删除的快照数量
    """
    return await asyncio.to_thread(
        cleanup_old_snapshots,
        project_root,
        keep_count
    )
