# Simulation Service - Stateless Simulation Execution
"""
仿真执行服务 - 无状态仿真执行与结果管理

职责：
- 执行仿真并将结果存储到文件
- 加载仿真结果
- 提取性能指标摘要

设计原则：
- 纯函数式：输入 → 执行仿真 → 输出到文件 → 返回路径/摘要
- 无状态：仿真结果直接写入文件，不缓存
- 幂等性：相同输入产生相同输出

存储路径：
- 仿真结果：{project_root}/.circuit_ai/sim_results/{uuid}.json

被调用方：
- simulation_node: 执行仿真
- analysis_node: 读取仿真结果进行分析
- UI 面板: 显示仿真结果

注意：
- 实际仿真执行逻辑在阶段四实现
- 本模块提供接口骨架和结果管理功能

使用示例：
    from domain.services import simulation_service
    
    # 执行仿真
    result_path, metrics = simulation_service.run_simulation(
        project_root="/path/to/project",
        circuit_file="amplifier.cir"
    )
    
    # 加载仿真结果
    result = simulation_service.load_sim_result(
        project_root="/path/to/project",
        result_path=result_path
    )
    
    # 提取指标
    metrics = simulation_service.extract_metrics(result, goals)
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.models.load_result import LoadResult, LoadErrorCode

# 仿真结果目录相对路径
SIM_RESULTS_DIR = ".circuit_ai/sim_results"


def run_simulation(
    project_root: str,
    circuit_file: str,
    *,
    analysis_type: str = "ac",
    parameters: Optional[Dict[str, Any]] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    执行仿真并返回结果文件路径和指标摘要
    
    Args:
        project_root: 项目根目录路径
        circuit_file: 电路文件相对路径
        analysis_type: 分析类型（ac, dc, tran, op）
        parameters: 仿真参数
        
    Returns:
        Tuple[str, Dict]: (结果文件相对路径, 指标摘要)
        
    Raises:
        FileNotFoundError: 电路文件不存在
        RuntimeError: 仿真执行失败
        
    注意：
        实际仿真执行逻辑在阶段四实现
        当前返回占位结果
    """
    root = Path(project_root)
    circuit_path = root / circuit_file
    
    # 验证电路文件存在
    if not circuit_path.exists():
        raise FileNotFoundError(f"Circuit file not found: {circuit_file}")
    
    # 生成结果文件路径
    result_id = _generate_result_id()
    result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
    result_path = root / result_rel_path
    
    # 确保目录存在
    result_path.parent.mkdir(parents=True, exist_ok=True)
    
    # TODO: 阶段四实现实际仿真执行
    # 当前返回占位结果
    result_data = {
        "id": result_id,
        "circuit_file": circuit_file,
        "analysis_type": analysis_type,
        "parameters": parameters or {},
        "timestamp": datetime.now().isoformat(),
        "status": "pending",  # pending | completed | failed
        "data": {},
        "metrics": {},
        "error": None,
    }
    
    # 写入结果文件
    _write_json_file(result_path, result_data)
    
    # 提取指标摘要
    metrics_summary = extract_metrics(result_data, {})
    
    return result_rel_path, metrics_summary


def load_sim_result(
    project_root: str,
    result_path: str
) -> LoadResult[Dict[str, Any]]:
    """
    从文件加载仿真结果
    
    Args:
        project_root: 项目根目录路径
        result_path: 结果文件相对路径
        
    Returns:
        LoadResult[Dict]: 加载结果对象
        - 成功时：result.success=True, result.data 包含仿真数据
        - 路径为空：result.error_code=PATH_EMPTY
        - 文件不存在：result.error_code=FILE_MISSING
        - 解析失败：result.error_code=PARSE_ERROR
        
    使用示例：
        result = load_sim_result(project_root, path)
        if result.success:
            data = result.data
        elif result.is_file_missing():
            # 显示文件缺失占位图
            pass
    """
    # 路径为空检查
    if not result_path:
        return LoadResult.path_empty()
    
    root = Path(project_root)
    file_path = root / result_path
    
    # 文件存在性检查
    if not file_path.exists():
        return LoadResult.file_missing(result_path)
    
    # 尝试读取和解析
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            return LoadResult.parse_error(result_path, "文件内容为空")
        
        data = json.loads(content)
        return LoadResult.ok(data, result_path)
        
    except json.JSONDecodeError as e:
        return LoadResult.parse_error(result_path, f"JSON 解析失败: {e}")
    except PermissionError:
        return LoadResult.permission_denied(result_path)
    except Exception as e:
        return LoadResult.unknown_error(result_path, str(e))


def extract_metrics(
    sim_data: Dict[str, Any],
    goals: Dict[str, Any]
) -> Dict[str, Any]:
    """
    从仿真结果中提取性能指标摘要
    
    根据设计目标提取对应的性能指标，用于：
    - 存入 GraphState.last_metrics
    - UI 显示
    - 条件边判断
    
    Args:
        sim_data: 仿真结果数据
        goals: 设计目标（用于确定需要提取哪些指标）
        
    Returns:
        Dict: 性能指标摘要
        
    示例输出：
        {
            "gain": "18.5dB",
            "bandwidth": "9.2MHz",
            "phase_margin": "45°",
            "status": "completed",
            "timestamp": "2024-01-01T12:00:00"
        }
    """
    if not sim_data:
        return {"status": "no_data"}
    
    metrics = {
        "status": sim_data.get("status", "unknown"),
        "timestamp": sim_data.get("timestamp", ""),
    }
    
    # 从仿真数据中提取指标
    raw_metrics = sim_data.get("metrics", {})
    
    # 如果有设计目标，只提取目标相关的指标
    if goals:
        for goal_key in goals.keys():
            if goal_key in raw_metrics:
                metrics[goal_key] = raw_metrics[goal_key]
    else:
        # 无目标时，提取所有指标
        metrics.update(raw_metrics)
    
    return metrics


def get_sim_result_path(
    project_root: str,
    result_id: Optional[str] = None
) -> str:
    """
    获取仿真结果文件路径
    
    Args:
        project_root: 项目根目录路径
        result_id: 结果 ID，为空时返回目录路径
        
    Returns:
        str: 仿真结果文件或目录的完整路径
    """
    root = Path(project_root)
    if result_id:
        return str(root / SIM_RESULTS_DIR / f"{result_id}.json")
    return str(root / SIM_RESULTS_DIR)


def list_sim_results(
    project_root: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    列出最近的仿真结果
    
    Args:
        project_root: 项目根目录路径
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 仿真结果摘要列表，按时间倒序
    """
    root = Path(project_root)
    results_dir = root / SIM_RESULTS_DIR
    
    if not results_dir.exists():
        return []
    
    # 获取所有 JSON 文件
    json_files = list(results_dir.glob("*.json"))
    
    # 按修改时间排序
    json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    results = []
    for file_path in json_files[:limit]:
        data = _read_json_file(file_path)
        if data:
            results.append({
                "id": data.get("id", file_path.stem),
                "circuit_file": data.get("circuit_file", ""),
                "status": data.get("status", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "path": str(file_path.relative_to(root)),
            })
    
    return results


def get_latest_sim_result(project_root: str) -> LoadResult[Dict[str, Any]]:
    """
    获取最新的仿真结果
    
    Args:
        project_root: 项目根目录路径
        
    Returns:
        LoadResult[Dict]: 加载结果对象
    """
    results = list_sim_results(project_root, limit=1)
    if results:
        return load_sim_result(project_root, results[0]["path"])
    return LoadResult.file_missing("")


def delete_sim_result(
    project_root: str,
    result_path: str
) -> bool:
    """
    删除仿真结果文件
    
    Args:
        project_root: 项目根目录路径
        result_path: 结果文件相对路径
        
    Returns:
        bool: 是否删除成功
    """
    root = Path(project_root)
    file_path = root / result_path
    
    if file_path.exists():
        try:
            file_path.unlink()
            return True
        except Exception:
            return False
    return False


# ============================================================
# 内部辅助函数
# ============================================================

def _generate_result_id() -> str:
    """生成仿真结果 ID"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"sim_{timestamp}_{short_uuid}"


def _read_json_file(file_path: Path) -> Dict[str, Any]:
    """读取 JSON 文件"""
    try:
        content = file_path.read_text(encoding="utf-8")
        return json.loads(content) if content.strip() else {}
    except (json.JSONDecodeError, Exception):
        return {}


def _write_json_file(file_path: Path, data: Dict[str, Any]) -> None:
    """写入 JSON 文件"""
    content = json.dumps(data, indent=2, ensure_ascii=False)
    file_path.write_text(content, encoding="utf-8")


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "run_simulation",
    "load_sim_result",
    "extract_metrics",
    "get_sim_result_path",
    "list_sim_results",
    "get_latest_sim_result",
    "delete_sim_result",
    "SIM_RESULTS_DIR",
    "LoadResult",
    "LoadErrorCode",
]
