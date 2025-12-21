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
- LangGraph 节点和 UI 层必须使用异步方法，避免阻塞事件循环
- 异步方法通过 asyncio.to_thread() 将 shutil 操作卸载到线程池

存储路径：
- 快照目录：{project_root}/.circuit_ai/snapshots/{snapshot_id}/
- 每个快照是项目文件的完整副本

忽略规则：
- .circuit_ai/snapshots/ - 避免递归快照
- __pycache__/ - Python 缓存
- .git/ - Git 仓库
- *.pyc - 编译文件
- simulation_results/ - 仿真结果（可重新生成）

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

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 快照目录相对路径
SNAPSHOTS_DIR = ".circuit_ai/snapshots"

# 默认保留快照数量
DEFAULT_KEEP_COUNT = 10

# 快照时忽略的模式
IGNORE_PATTERNS = [
    ".circuit_ai/snapshots",  # 避免递归快照
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
]


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

    iteration_count: int = 0
    """对应的迭代次数（从快照 ID 解析）"""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "path": self.path,
            "iteration_count": self.iteration_count,
        }


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
    snapshot_dir = root / SNAPSHOTS_DIR / safe_id

    # 检查快照是否已存在
    if snapshot_dir.exists():
        raise ValueError(f"Snapshot already exists: {safe_id}")

    # 确保快照父目录存在
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)

    # 检查磁盘空间（粗略估计）
    _check_disk_space(root, snapshot_dir.parent)

    # 构建忽略函数
    all_patterns = IGNORE_PATTERNS.copy()
    if ignore_patterns:
        all_patterns.extend(ignore_patterns)
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
        _write_snapshot_metadata(snapshot_dir, safe_id)

        return f"{SNAPSHOTS_DIR}/{safe_id}"

    except Exception as e:
        # 清理不完整的快照目录
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to create snapshot: {e}") from e


def restore_snapshot(
    project_root: str,
    snapshot_id: str,
    *,
    backup_current: bool = True,
) -> None:
    """
    从快照恢复项目文件

    恢复策略：
    1. 如果 backup_current=True，先备份当前状态
    2. 删除项目中的可恢复文件（保留 .circuit_ai 等）
    3. 从快照复制文件到项目目录

    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识
        backup_current: 是否在恢复前备份当前状态

    Raises:
        ValueError: 快照不存在
        RuntimeError: 恢复失败
    """
    safe_id = _sanitize_snapshot_id(snapshot_id)
    root = Path(project_root).resolve()
    snapshot_dir = root / SNAPSHOTS_DIR / safe_id

    if not snapshot_dir.exists():
        raise ValueError(f"Snapshot not found: {safe_id}")

    # 备份当前状态（可选）
    backup_id = None
    if backup_current:
        backup_id = f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            create_snapshot(project_root, backup_id)
        except Exception:
            # 备份失败不阻止恢复，但记录警告
            backup_id = None

    try:
        # 恢复文件
        _restore_files_from_snapshot(root, snapshot_dir)

    except Exception as e:
        # 恢复失败，尝试从备份恢复
        if backup_id:
            try:
                _restore_files_from_snapshot(
                    root, root / SNAPSHOTS_DIR / backup_id
                )
            except Exception:
                pass  # 备份恢复也失败，保持当前状态
        raise RuntimeError(f"Failed to restore snapshot: {e}") from e

    finally:
        # 清理临时备份
        if backup_id:
            try:
                delete_snapshot(project_root, backup_id)
            except Exception:
                pass


def list_snapshots(project_root: str) -> List[SnapshotInfo]:
    """
    列出所有快照

    Args:
        project_root: 项目根目录路径

    Returns:
        List[SnapshotInfo]: 快照信息列表，按时间倒序排列
    """
    root = Path(project_root).resolve()
    snapshots_dir = root / SNAPSHOTS_DIR

    if not snapshots_dir.exists():
        return []

    snapshots = []
    for item in snapshots_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
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
    snapshot_dir = root / SNAPSHOTS_DIR / safe_id

    if not snapshot_dir.exists():
        raise ValueError(f"Snapshot not found: {safe_id}")

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
    snapshot_dir = root / SNAPSHOTS_DIR / safe_id

    if not snapshot_dir.exists():
        return None

    return _get_snapshot_info(snapshot_dir)


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
    snapshot_dir = root / SNAPSHOTS_DIR / safe_id
    return snapshot_dir.exists()


def get_snapshots_dir(project_root: str) -> str:
    """
    获取快照目录路径

    Args:
        project_root: 项目根目录路径

    Returns:
        str: 快照目录的完整路径
    """
    return str(Path(project_root).resolve() / SNAPSHOTS_DIR)


def get_previous_snapshot(project_root: str) -> Optional[SnapshotInfo]:
    """
    获取上一个快照（用于线性撤回）
    
    返回按时间排序的第二新的快照（最新的是当前迭代，上一个是撤回目标）
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        Optional[SnapshotInfo]: 上一个快照信息，若不存在返回 None
    """
    snapshots = list_snapshots(project_root)
    
    # 过滤掉临时快照（以 _ 开头）
    regular_snapshots = [s for s in snapshots if not s.snapshot_id.startswith("_")]
    
    # 需要至少 2 个快照才能撤回
    if len(regular_snapshots) < 2:
        return None
    
    # 返回第二新的快照（索引 1，因为已按时间倒序排列）
    return regular_snapshots[1]


def pop_snapshot(project_root: str) -> Optional[str]:
    """
    弹出并删除最新快照（撤回后清理）
    
    用于撤回操作完成后，删除当前迭代的快照。
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        Optional[str]: 被删除的快照 ID，若无快照返回 None
    """
    snapshots = list_snapshots(project_root)
    
    # 过滤掉临时快照
    regular_snapshots = [s for s in snapshots if not s.snapshot_id.startswith("_")]
    
    if not regular_snapshots:
        return None
    
    # 删除最新的快照（索引 0）
    latest = regular_snapshots[0]
    try:
        delete_snapshot(project_root, latest.snapshot_id)
        return latest.snapshot_id
    except Exception:
        return None


def generate_snapshot_id(iteration_count: int) -> str:
    """
    生成快照 ID
    
    格式：iter_{iteration_count:03d}_{timestamp}
    示例：iter_001_20241220_143022
    
    Args:
        iteration_count: 迭代次数
        
    Returns:
        str: 快照 ID
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"iter_{iteration_count:03d}_{timestamp}"


def parse_iteration_from_snapshot_id(snapshot_id: str) -> int:
    """
    从快照 ID 解析迭代次数
    
    Args:
        snapshot_id: 快照 ID
        
    Returns:
        int: 迭代次数，解析失败返回 0
    """
    try:
        # 格式：iter_001_20241220_143022
        if snapshot_id.startswith("iter_"):
            parts = snapshot_id.split("_")
            if len(parts) >= 2:
                return int(parts[1])
    except (ValueError, IndexError):
        pass
    return 0


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


def _create_ignore_function(root: Path, patterns: List[str]):
    """
    创建忽略函数

    结合 shutil.ignore_patterns 和自定义路径匹配
    """
    # 分离文件模式和目录模式
    file_patterns = [p for p in patterns if "*" in p]
    dir_patterns = [p for p in patterns if "*" not in p]

    # 创建文件模式忽略函数
    file_ignore = shutil.ignore_patterns(*file_patterns) if file_patterns else None

    def ignore_func(directory: str, contents: List[str]) -> set:
        ignored = set()
        dir_path = Path(directory)

        # 应用文件模式
        if file_ignore:
            ignored.update(file_ignore(directory, contents))

        # 应用目录模式
        for name in contents:
            item_path = dir_path / name

            # 检查是否匹配目录模式
            for pattern in dir_patterns:
                # 相对于项目根目录的路径
                try:
                    rel_path = item_path.relative_to(root)
                    rel_str = str(rel_path).replace("\\", "/")

                    # 检查路径是否以模式开头或完全匹配
                    if rel_str == pattern or rel_str.startswith(f"{pattern}/"):
                        ignored.add(name)
                        break

                    # 检查目录名是否匹配
                    if name == pattern:
                        ignored.add(name)
                        break
                except ValueError:
                    pass

        return ignored

    return ignore_func


def _check_disk_space(source: Path, dest_parent: Path) -> None:
    """
    检查磁盘空间是否足够

    粗略估计：要求可用空间至少是源目录大小的 1.5 倍
    """
    try:
        # 获取源目录大小（快速估计，只计算顶层）
        source_size = sum(
            f.stat().st_size for f in source.rglob("*") if f.is_file()
        )

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


def _write_snapshot_metadata(snapshot_dir: Path, snapshot_id: str) -> None:
    """写入快照元数据"""
    import json

    metadata = {
        "snapshot_id": snapshot_id,
        "timestamp": datetime.now().isoformat(),
        "created_by": "snapshot_service",
    }

    metadata_file = snapshot_dir / ".snapshot_meta.json"
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _get_snapshot_info(snapshot_dir: Path) -> Optional[SnapshotInfo]:
    """获取快照信息"""
    import json

    if not snapshot_dir.is_dir():
        return None

    # 读取元数据
    metadata_file = snapshot_dir / ".snapshot_meta.json"
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
        for f in snapshot_dir.rglob("*"):
            if f.is_file():
                size_bytes += f.stat().st_size
                file_count += 1
    except Exception:
        pass

    # 解析迭代次数
    iteration_count = parse_iteration_from_snapshot_id(snapshot_id)

    return SnapshotInfo(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        size_bytes=size_bytes,
        file_count=file_count,
        path=str(snapshot_dir),
        iteration_count=iteration_count,
    )


def _restore_files_from_snapshot(root: Path, snapshot_dir: Path) -> None:
    """
    从快照恢复文件到项目目录

    策略：
    1. 遍历快照中的文件
    2. 复制到项目目录对应位置
    3. 跳过 .circuit_ai 目录
    """
    # 需要跳过的目录（不从快照恢复）
    skip_dirs = {".circuit_ai", ".git", "__pycache__", ".pytest_cache"}

    for item in snapshot_dir.iterdir():
        if item.name in skip_dirs:
            continue

        if item.name == ".snapshot_meta.json":
            continue

        dest = root / item.name

        try:
            if item.is_dir():
                # 删除目标目录（如果存在）
                if dest.exists():
                    shutil.rmtree(dest)
                # 复制目录
                shutil.copytree(item, dest)
            else:
                # 复制文件
                shutil.copy2(item, dest)
        except Exception as e:
            raise RuntimeError(f"Failed to restore {item.name}: {e}") from e


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SnapshotInfo",
    "create_snapshot",
    "restore_snapshot",
    "list_snapshots",
    "delete_snapshot",
    "cleanup_old_snapshots",
    "get_snapshot_info",
    "snapshot_exists",
    "get_snapshots_dir",
    # 线性撤回支持
    "get_previous_snapshot",
    "pop_snapshot",
    "generate_snapshot_id",
    "parse_iteration_from_snapshot_id",
    # 异步方法
    "create_snapshot_async",
    "restore_snapshot_async",
    "list_snapshots_async",
    "delete_snapshot_async",
    "cleanup_old_snapshots_async",
    # 常量
    "SNAPSHOTS_DIR",
    "DEFAULT_KEEP_COUNT",
]


# ============================================================
# 异步包装方法（应用层接口）
# ============================================================

import asyncio


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
) -> None:
    """
    异步从快照恢复项目文件
    
    通过 asyncio.to_thread() 将文件恢复操作卸载到线程池。
    
    Args:
        project_root: 项目根目录路径
        snapshot_id: 快照标识
        backup_current: 是否在恢复前备份当前状态
    """
    return await asyncio.to_thread(
        restore_snapshot,
        project_root,
        snapshot_id,
        backup_current=backup_current
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
