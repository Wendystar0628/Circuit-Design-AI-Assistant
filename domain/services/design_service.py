# Design Service - Stateless Design Goals Management
"""
设计目标服务 - 无状态设计目标读写

职责：
- 提供设计目标的读写接口
- 数据存储在文件系统中
- 不持有任何内存状态

设计原则：
- 纯函数式：输入 → 处理 → 输出到文件 → 返回路径/摘要
- 无状态：不缓存任何数据
- 幂等性：相同输入产生相同输出

存储路径：
- 设计目标：{project_root}/.circuit_ai/design_goals.json

被调用方：
- design_goals_node: 提取和保存设计目标
- analysis_node: 读取设计目标进行分析
- UI 面板: 显示设计目标

使用示例：
    from domain.services import design_service
    
    # 保存设计目标
    path = design_service.save_design_goals(
        project_root="/path/to/project",
        goals={"gain": {"target": "20dB", "tolerance": "±2dB"}}
    )
    
    # 加载设计目标
    goals = design_service.load_design_goals("/path/to/project")
    
    # 获取摘要
    summary = design_service.get_goals_summary(goals)
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 设计目标文件相对路径
DESIGN_GOALS_FILE = ".circuit_ai/design_goals.json"


def save_design_goals(
    project_root: str,
    goals: Dict[str, Any],
    *,
    merge: bool = False
) -> str:
    """
    保存设计目标到文件
    
    Args:
        project_root: 项目根目录路径
        goals: 设计目标字典
        merge: 是否与现有目标合并（默认覆盖）
        
    Returns:
        str: 设计目标文件的相对路径
        
    Raises:
        ValueError: 目标格式无效
        IOError: 文件写入失败
    """
    # 验证目标格式
    is_valid, error_msg = validate_design_goals(goals)
    if not is_valid:
        raise ValueError(f"Invalid design goals: {error_msg}")
    
    root = Path(project_root)
    file_path = root / DESIGN_GOALS_FILE
    
    # 确保目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 合并模式
    if merge and file_path.exists():
        existing = _read_json_file(file_path)
        goals = _merge_goals(existing, goals)
    
    # 写入文件
    _write_json_file(file_path, goals)
    
    return DESIGN_GOALS_FILE


def load_design_goals(project_root: str) -> Dict[str, Any]:
    """
    从文件加载设计目标
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        Dict: 设计目标字典，文件不存在时返回空字典
    """
    root = Path(project_root)
    file_path = root / DESIGN_GOALS_FILE
    
    if not file_path.exists():
        return {}
    
    return _read_json_file(file_path)


def get_goals_summary(goals: Dict[str, Any]) -> Dict[str, Any]:
    """
    提取设计目标摘要（用于存入 GraphState）
    
    摘要包含：
    - 目标数量
    - 各目标的 target 值
    - 优先级信息（如有）
    
    Args:
        goals: 完整的设计目标字典
        
    Returns:
        Dict: 轻量摘要，适合存入 GraphState
        
    示例输出：
        {
            "count": 3,
            "targets": {
                "gain": "20dB",
                "bandwidth": "10MHz",
                "phase_margin": "45°"
            },
            "priorities": ["gain", "bandwidth"]
        }
    """
    if not goals:
        return {"count": 0, "targets": {}, "priorities": []}
    
    targets = {}
    priorities = []
    
    for key, value in goals.items():
        if isinstance(value, dict):
            # 结构化目标：{"target": "20dB", "tolerance": "±2dB"}
            targets[key] = value.get("target", str(value))
            if value.get("priority"):
                priorities.append((key, value.get("priority", 0)))
        else:
            # 简单目标：直接值
            targets[key] = str(value)
    
    # 按优先级排序
    priorities.sort(key=lambda x: x[1], reverse=True)
    priority_keys = [p[0] for p in priorities]
    
    return {
        "count": len(targets),
        "targets": targets,
        "priorities": priority_keys,
    }


def validate_design_goals(goals: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    验证设计目标格式
    
    Args:
        goals: 设计目标字典
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if goals is None:
        return False, "Goals cannot be None"
    
    if not isinstance(goals, dict):
        return False, f"Goals must be a dict, got {type(goals).__name__}"
    
    # 空目标是允许的（清空设计目标）
    if not goals:
        return True, None
    
    # 检查每个目标
    for key, value in goals.items():
        if not isinstance(key, str):
            return False, f"Goal key must be string, got {type(key).__name__}"
        
        if value is None:
            return False, f"Goal '{key}' value cannot be None"
        
        # 结构化目标必须包含 target
        if isinstance(value, dict) and "target" not in value:
            return False, f"Structured goal '{key}' must have 'target' field"
    
    return True, None


def get_design_goals_path(project_root: str) -> str:
    """
    获取设计目标文件的完整路径
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        str: 设计目标文件的完整路径
    """
    return str(Path(project_root) / DESIGN_GOALS_FILE)


def design_goals_exist(project_root: str) -> bool:
    """
    检查设计目标文件是否存在
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        bool: 文件是否存在
    """
    return (Path(project_root) / DESIGN_GOALS_FILE).exists()


# ============================================================
# 内部辅助函数
# ============================================================

def _read_json_file(file_path: Path) -> Dict[str, Any]:
    """读取 JSON 文件"""
    try:
        content = file_path.read_text(encoding="utf-8")
        return json.loads(content) if content.strip() else {}
    except json.JSONDecodeError:
        return {}
    except Exception:
        return {}


def _write_json_file(file_path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 文件"""
    content = json.dumps(data, indent=2, ensure_ascii=False)
    file_path.write_text(content, encoding="utf-8")


def _merge_goals(
    existing: Dict[str, Any],
    new: Dict[str, Any]
) -> Dict[str, Any]:
    """
    合并设计目标
    
    新目标覆盖同名旧目标，保留不冲突的旧目标
    """
    result = existing.copy()
    result.update(new)
    return result


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "save_design_goals",
    "load_design_goals",
    "get_goals_summary",
    "validate_design_goals",
    "get_design_goals_path",
    "design_goals_exist",
    "DESIGN_GOALS_FILE",
]
