# Recovery Log Service - WAL for Undo Operations
"""
WAL 恢复日志服务 - 撤回操作的崩溃恢复

职责：
- 管理撤回操作的恢复日志
- 支持崩溃恢复，确保最终一致性

设计原则：
- 原子写入：使用 "写临时文件 + os.replace" 保证日志文件完整性
- 简单结构：JSON 格式，包含操作类型、阶段、目标快照等信息
- 启动时检查：应用启动时检测未完成的恢复操作

存储路径：
- 恢复日志：{project_root}/.circuit_ai/recovery.json

被调用方：
- undo_node: 撤回操作时写入/更新/删除日志
- bootstrap.py: 启动时检查未完成的恢复

使用示例：
    from domain.services import recovery_log_service
    
    # 写入恢复日志
    recovery_log_service.write_log(project_root, {
        "action": "undo",
        "target_snapshot": "iter_001_20241220_143022",
        "phase": "started"
    })
    
    # 检查是否有未完成的恢复
    if recovery_log_service.has_pending_recovery(project_root):
        log = recovery_log_service.read_log(project_root)
        # 处理恢复...
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# 恢复日志文件路径（相对于 .circuit_ai/）
RECOVERY_LOG_FILE = ".circuit_ai/recovery.json"


@dataclass
class RecoveryLog:
    """恢复日志数据结构"""

    action: str
    """操作类型（"undo"）"""

    target_snapshot: str
    """目标快照 ID"""

    phase: str
    """当前阶段（started | files_restored | state_rebuilt | completed | failed）"""

    started_at: str
    """开始时间（ISO 格式）"""

    error: Optional[str] = None
    """错误信息（失败时）"""

    def to_dict(self) -> dict:
        """转换为字典"""
        result = {
            "action": self.action,
            "target_snapshot": self.target_snapshot,
            "phase": self.phase,
            "started_at": self.started_at,
        }
        if self.error:
            result["error"] = self.error
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "RecoveryLog":
        """从字典创建"""
        return cls(
            action=data.get("action", ""),
            target_snapshot=data.get("target_snapshot", ""),
            phase=data.get("phase", ""),
            started_at=data.get("started_at", ""),
            error=data.get("error"),
        )


def write_log(project_root: str, log_data: dict) -> None:
    """
    原子写入恢复日志
    
    使用 "写临时文件 + os.replace" 保证原子性。
    日志文件要么完整存在，要么不存在。
    
    Args:
        project_root: 项目根目录路径
        log_data: 日志数据字典
    """
    root = Path(project_root).resolve()
    log_path = root / RECOVERY_LOG_FILE
    tmp_path = log_path.with_suffix(".json.tmp")
    
    # 确保目录存在
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 添加时间戳（如果没有）
    if "started_at" not in log_data:
        log_data["started_at"] = datetime.now().isoformat()
    
    # 写入临时文件
    content = json.dumps(log_data, indent=2, ensure_ascii=False)
    tmp_path.write_text(content, encoding="utf-8")
    
    # 原子替换
    os.replace(tmp_path, log_path)


def read_log(project_root: str) -> Optional[RecoveryLog]:
    """
    读取恢复日志
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        Optional[RecoveryLog]: 恢复日志，不存在或解析失败返回 None
    """
    root = Path(project_root).resolve()
    log_path = root / RECOVERY_LOG_FILE
    
    if not log_path.exists():
        return None
    
    try:
        content = log_path.read_text(encoding="utf-8")
        data = json.loads(content)
        return RecoveryLog.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        # 日志文件损坏，返回 None
        return None


def delete_log(project_root: str) -> bool:
    """
    删除恢复日志
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        bool: 是否成功删除
    """
    root = Path(project_root).resolve()
    log_path = root / RECOVERY_LOG_FILE
    
    if not log_path.exists():
        return True
    
    try:
        log_path.unlink()
        return True
    except OSError:
        return False


def has_pending_recovery(project_root: str) -> bool:
    """
    检查是否有未完成的恢复操作
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        bool: 是否有未完成的恢复
    """
    log = read_log(project_root)
    if log is None:
        return False
    
    # completed 和 failed 状态不算未完成
    return log.phase not in ("completed", "failed", "")


def update_phase(project_root: str, phase: str, error: Optional[str] = None) -> bool:
    """
    更新恢复阶段
    
    Args:
        project_root: 项目根目录路径
        phase: 新的阶段
        error: 错误信息（可选）
        
    Returns:
        bool: 是否成功更新
    """
    log = read_log(project_root)
    if log is None:
        return False
    
    log.phase = phase
    if error:
        log.error = error
    
    write_log(project_root, log.to_dict())
    return True


def create_undo_log(project_root: str, target_snapshot: str) -> None:
    """
    创建撤回操作的恢复日志
    
    便捷方法，用于开始撤回操作时。
    
    Args:
        project_root: 项目根目录路径
        target_snapshot: 目标快照 ID
    """
    write_log(project_root, {
        "action": "undo",
        "target_snapshot": target_snapshot,
        "phase": "started",
    })


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "RecoveryLog",
    "write_log",
    "read_log",
    "delete_log",
    "has_pending_recovery",
    "update_phase",
    "create_undo_log",
    "RECOVERY_LOG_FILE",
]
