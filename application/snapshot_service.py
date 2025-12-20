# Snapshot Service - Full Project Snapshot Management
"""
全量快照服务

职责：
- 创建项目文件的全量快照
- 从快照恢复项目文件
- 管理快照生命周期（清理旧快照）

核心原理：
- 使用 shutil.copytree 进行全量拷贝，简单可靠
- 快照存储在 .circuit_ai/snapshots/ 目录
- 每个快照是一个带时间戳的子目录
- 回滚时配合 LangGraph Time Travel 使用

使用示例：
    from application.snapshot_service import SnapshotService
    
    service = SnapshotService(project_root="/path/to/project")
    
    # 创建快照
    snapshot_id = service.create_snapshot()
    
    # 恢复快照
    service.restore_snapshot(snapshot_id)
    
    # 清理旧快照
    service.cleanup_old_snapshots(keep_count=5)
"""

import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


# ============================================================
# 常量定义
# ============================================================

# 快照目录名
SNAPSHOTS_DIR = "snapshots"

# 默认保留的快照数量
DEFAULT_KEEP_COUNT = 10

# 排除的目录（不纳入快照）
EXCLUDE_DIRS = {
    ".git",
    ".circuit_ai",  # 系统目录本身不快照
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
}

# 排除的文件模式
EXCLUDE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
}


# ============================================================
# 快照信息数据类
# ============================================================

@dataclass
class SnapshotInfo:
    """快照信息"""
    snapshot_id: str
    path: Path
    created_at: datetime
    size_bytes: int
    file_count: int
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "path": str(self.path),
            "created_at": self.created_at.isoformat(),
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
        }


# ============================================================
# 快照服务主类
# ============================================================

class SnapshotService:
    """
    全量快照服务
    
    使用 shutil.copytree 进行全量拷贝，简单可靠。
    """
    
    def __init__(self, project_root: str = None):
        """
        初始化快照服务
        
        Args:
            project_root: 项目根目录，不传则延迟设置
        """
        self._project_root: Optional[Path] = None
        if project_root:
            self._project_root = Path(project_root).resolve()
        
        self._logger = None
    
    @property
    def project_root(self) -> Optional[Path]:
        """获取项目根目录"""
        return self._project_root
    
    @project_root.setter
    def project_root(self, value: str):
        """设置项目根目录"""
        self._project_root = Path(value).resolve() if value else None
    
    @property
    def snapshots_dir(self) -> Optional[Path]:
        """获取快照目录"""
        if self._project_root:
            return self._project_root / ".circuit_ai" / SNAPSHOTS_DIR
        return None
    
    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("snapshot_service")
            except Exception:
                pass
        return self._logger
    
    # ============================================================
    # 核心功能
    # ============================================================
    
    def create_snapshot(
        self,
        snapshot_id: str = None,
        description: str = ""
    ) -> Tuple[bool, str, Optional[str]]:
        """
        创建项目文件的全量快照
        
        Args:
            snapshot_id: 快照 ID，不传则自动生成
            description: 快照描述
            
        Returns:
            Tuple[bool, str, Optional[str]]: (是否成功, 消息, 快照ID)
        """
        if not self._project_root:
            return False, "项目根目录未设置", None
        
        if not self._project_root.exists():
            return False, f"项目目录不存在: {self._project_root}", None
        
        # 确保快照目录存在
        snapshots_dir = self.snapshots_dir
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成快照 ID
        if not snapshot_id:
            snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        
        snapshot_path = snapshots_dir / snapshot_id
        
        try:
            # 使用 shutil.copytree 进行全量拷贝
            shutil.copytree(
                self._project_root,
                snapshot_path,
                ignore=self._get_ignore_function(),
                dirs_exist_ok=False
            )
            
            # 写入元数据
            self._write_metadata(snapshot_path, description)
            
            # 计算快照大小
            size_bytes, file_count = self._calculate_size(snapshot_path)
            
            if self.logger:
                self.logger.info(
                    f"创建快照成功: {snapshot_id} "
                    f"({file_count} 文件, {size_bytes / 1024 / 1024:.2f} MB)"
                )
            
            return True, f"快照创建成功: {snapshot_id}", snapshot_id
            
        except Exception as e:
            # 清理失败的快照
            if snapshot_path.exists():
                shutil.rmtree(snapshot_path, ignore_errors=True)
            
            error_msg = f"创建快照失败: {e}"
            if self.logger:
                self.logger.error(error_msg)
            return False, error_msg, None
    
    def restore_snapshot(
        self,
        snapshot_id: str,
        backup_current: bool = True
    ) -> Tuple[bool, str]:
        """
        从快照恢复项目文件
        
        Args:
            snapshot_id: 快照 ID
            backup_current: 是否备份当前状态
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        if not self._project_root:
            return False, "项目根目录未设置"
        
        snapshot_path = self.snapshots_dir / snapshot_id
        
        if not snapshot_path.exists():
            return False, f"快照不存在: {snapshot_id}"
        
        try:
            # 可选：备份当前状态
            backup_id = None
            if backup_current:
                success, msg, backup_id = self.create_snapshot(
                    snapshot_id=f"backup_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    description=f"恢复快照 {snapshot_id} 前的自动备份"
                )
                if not success:
                    if self.logger:
                        self.logger.warning(f"备份当前状态失败: {msg}")
            
            # 清理当前项目文件（保留 .circuit_ai）
            self._clean_project_files()
            
            # 从快照恢复
            for item in snapshot_path.iterdir():
                if item.name == ".circuit_ai":
                    continue  # 不恢复系统目录
                
                dest = self._project_root / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
            
            if self.logger:
                self.logger.info(f"恢复快照成功: {snapshot_id}")
            
            return True, f"快照恢复成功: {snapshot_id}"
            
        except Exception as e:
            error_msg = f"恢复快照失败: {e}"
            if self.logger:
                self.logger.error(error_msg)
            return False, error_msg
    
    def cleanup_old_snapshots(
        self,
        keep_count: int = DEFAULT_KEEP_COUNT
    ) -> Tuple[int, List[str]]:
        """
        清理旧快照，保留最近的 N 个
        
        Args:
            keep_count: 保留的快照数量
            
        Returns:
            Tuple[int, List[str]]: (删除数量, 删除的快照ID列表)
        """
        if not self.snapshots_dir or not self.snapshots_dir.exists():
            return 0, []
        
        # 获取所有快照并按时间排序
        snapshots = self.list_snapshots()
        
        if len(snapshots) <= keep_count:
            return 0, []
        
        # 删除旧快照
        to_delete = snapshots[keep_count:]
        deleted = []
        
        for snapshot in to_delete:
            try:
                shutil.rmtree(snapshot.path)
                deleted.append(snapshot.snapshot_id)
                if self.logger:
                    self.logger.debug(f"删除旧快照: {snapshot.snapshot_id}")
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"删除快照失败: {snapshot.snapshot_id} - {e}")
        
        if self.logger and deleted:
            self.logger.info(f"清理了 {len(deleted)} 个旧快照")
        
        return len(deleted), deleted
    
    def delete_snapshot(self, snapshot_id: str) -> Tuple[bool, str]:
        """
        删除指定快照
        
        Args:
            snapshot_id: 快照 ID
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        if not self.snapshots_dir:
            return False, "快照目录未设置"
        
        snapshot_path = self.snapshots_dir / snapshot_id
        
        if not snapshot_path.exists():
            return False, f"快照不存在: {snapshot_id}"
        
        try:
            shutil.rmtree(snapshot_path)
            if self.logger:
                self.logger.info(f"删除快照: {snapshot_id}")
            return True, f"快照已删除: {snapshot_id}"
        except Exception as e:
            return False, f"删除快照失败: {e}"
    
    # ============================================================
    # 查询功能
    # ============================================================
    
    def list_snapshots(self) -> List[SnapshotInfo]:
        """
        列出所有快照（按创建时间降序）
        
        Returns:
            List[SnapshotInfo]: 快照列表
        """
        if not self.snapshots_dir or not self.snapshots_dir.exists():
            return []
        
        snapshots = []
        
        for item in self.snapshots_dir.iterdir():
            if not item.is_dir():
                continue
            
            # 解析创建时间
            try:
                # 从目录名解析时间
                parts = item.name.split("_")
                if len(parts) >= 2:
                    date_str = parts[0]
                    time_str = parts[1]
                    created_at = datetime.strptime(
                        f"{date_str}_{time_str}",
                        "%Y%m%d_%H%M%S"
                    )
                else:
                    created_at = datetime.fromtimestamp(item.stat().st_mtime)
            except Exception:
                created_at = datetime.fromtimestamp(item.stat().st_mtime)
            
            # 计算大小
            size_bytes, file_count = self._calculate_size(item)
            
            snapshots.append(SnapshotInfo(
                snapshot_id=item.name,
                path=item,
                created_at=created_at,
                size_bytes=size_bytes,
                file_count=file_count,
            ))
        
        # 按创建时间降序排序
        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        
        return snapshots
    
    def get_snapshot(self, snapshot_id: str) -> Optional[SnapshotInfo]:
        """
        获取指定快照信息
        
        Args:
            snapshot_id: 快照 ID
            
        Returns:
            SnapshotInfo: 快照信息，不存在返回 None
        """
        if not self.snapshots_dir:
            return None
        
        snapshot_path = self.snapshots_dir / snapshot_id
        
        if not snapshot_path.exists():
            return None
        
        snapshots = self.list_snapshots()
        for snapshot in snapshots:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        
        return None
    
    def get_total_size(self) -> int:
        """
        获取所有快照的总大小（字节）
        
        Returns:
            int: 总大小
        """
        snapshots = self.list_snapshots()
        return sum(s.size_bytes for s in snapshots)
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _get_ignore_function(self):
        """获取 shutil.copytree 的 ignore 函数"""
        def ignore_func(directory, files):
            ignored = set()
            
            # 排除目录
            for name in files:
                if name in EXCLUDE_DIRS:
                    ignored.add(name)
                    continue
                
                # 排除文件模式
                for pattern in EXCLUDE_PATTERNS:
                    if pattern.startswith("*"):
                        if name.endswith(pattern[1:]):
                            ignored.add(name)
                            break
            
            return ignored
        
        return ignore_func
    
    def _write_metadata(self, snapshot_path: Path, description: str) -> None:
        """写入快照元数据"""
        import json
        
        metadata = {
            "created_at": datetime.now().isoformat(),
            "description": description,
            "project_root": str(self._project_root),
        }
        
        metadata_file = snapshot_path / ".snapshot_metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    
    def _calculate_size(self, path: Path) -> Tuple[int, int]:
        """计算目录大小和文件数量"""
        total_size = 0
        file_count = 0
        
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    total_size += item.stat().st_size
                    file_count += 1
        except Exception:
            pass
        
        return total_size, file_count
    
    def _clean_project_files(self) -> None:
        """清理项目文件（保留 .circuit_ai）"""
        if not self._project_root:
            return
        
        for item in self._project_root.iterdir():
            if item.name == ".circuit_ai":
                continue
            if item.name in EXCLUDE_DIRS:
                continue
            
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"清理文件失败: {item} - {e}")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SnapshotService",
    "SnapshotInfo",
]
