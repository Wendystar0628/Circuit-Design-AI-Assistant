# Simulation Service - Stateless Simulation Execution
"""
仿真执行服务 - 无状态仿真执行与结果管理

职责：
- 执行仿真并将结果存储到文件
- 加载仿真结果
- 提取性能指标摘要
- 执行高级仿真（PVT、蒙特卡洛、参数扫描）

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
"""

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.models.load_result import LoadResult, LoadErrorCode
from domain.simulation.models import (
    AnalysisType,
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
    MetricsSummary,
    PVTCorner,
    MonteCarloConfig,
    ParametricSweepConfig,
)
from domain.simulation.executor import SpiceExecutor, SpiceExecutorError

logger = logging.getLogger(__name__)

# 仿真结果目录相对路径
SIM_RESULTS_DIR = ".circuit_ai/sim_results"

# 线程池（用于异步执行）
_executor_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sim_")


# ============================================================
# 核心仿真执行
# ============================================================

def run_simulation(
    project_root: str,
    circuit_file: str,
    config: Optional[SimulationConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    执行仿真并返回结果文件路径和指标摘要
    
    Args:
        project_root: 项目根目录路径
        circuit_file: 电路文件相对路径
        config: 仿真配置（None 时使用默认 AC 分析）
        progress_callback: 进度回调 (progress: 0-1, message: str)
        
    Returns:
        Tuple[str, Dict]: (结果文件相对路径, 指标摘要)
        
    Raises:
        FileNotFoundError: 电路文件不存在
        RuntimeError: 仿真执行失败
    """
    root = Path(project_root)
    circuit_path = root / circuit_file
    
    # 验证电路文件存在
    if not circuit_path.exists():
        raise FileNotFoundError(f"电路文件不存在: {circuit_file}")
    
    # 使用默认配置
    if config is None:
        config = SimulationConfig(analysis_type=AnalysisType.AC)
    
    # 生成结果 ID 和路径
    result_id = _generate_result_id()
    result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
    result_path = root / result_rel_path
    
    # 确保目录存在
    result_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 创建初始结果对象
    sim_result = SimulationResult.create_pending(
        result_id=result_id,
        circuit_file=circuit_file,
        analysis_type=config.analysis_type.value,
        config=config.to_dict()
    )
    
    start_time = datetime.now()
    
    try:
        # 执行仿真
        executor = SpiceExecutor()
        raw_data = executor.run_analysis(
            circuit_path=str(circuit_path),
            config=config,
            progress_callback=progress_callback
        )
        
        # 更新结果
        sim_result.status = SimulationStatus.COMPLETED
        sim_result.data = raw_data.get("vectors", {})
        sim_result.duration = (datetime.now() - start_time).total_seconds()
        
        # 提取指标
        sim_result.metrics = _extract_metrics_from_data(
            raw_data,
            config.analysis_type
        )
        
    except SpiceExecutorError as e:
        logger.error(f"仿真执行失败: {e}")
        sim_result.status = SimulationStatus.FAILED
        sim_result.error = str(e)
        sim_result.duration = (datetime.now() - start_time).total_seconds()
        
    except Exception as e:
        logger.exception("仿真执行异常")
        sim_result.status = SimulationStatus.FAILED
        sim_result.error = f"未知错误: {e}"
        sim_result.duration = (datetime.now() - start_time).total_seconds()
    
    # 写入结果文件
    _write_json_file(result_path, sim_result.to_dict())
    
    # 生成指标摘要
    metrics_summary = MetricsSummary.from_simulation_result(sim_result).to_dict()
    
    return result_rel_path, metrics_summary


async def run_simulation_async(
    project_root: str,
    circuit_file: str,
    config: Optional[SimulationConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    异步执行仿真
    
    在线程池中执行仿真，不阻塞事件循环。
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor_pool,
        lambda: run_simulation(project_root, circuit_file, config, progress_callback)
    )


# ============================================================
# 结果读取
# ============================================================

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
    """
    if not result_path:
        return LoadResult.path_empty()
    
    root = Path(project_root)
    file_path = root / result_path
    
    if not file_path.exists():
        return LoadResult.file_missing(result_path)
    
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
    """从仿真结果中提取性能指标摘要"""
    if not sim_data:
        return {"status": "no_data"}
    
    metrics = {
        "status": sim_data.get("status", "unknown"),
        "timestamp": sim_data.get("timestamp", ""),
    }
    
    raw_metrics = sim_data.get("metrics", {})
    
    if goals:
        for goal_key in goals.keys():
            if goal_key in raw_metrics:
                metrics[goal_key] = raw_metrics[goal_key]
    else:
        metrics.update(raw_metrics)
    
    return metrics


def list_sim_results(
    project_root: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """列出最近的仿真结果"""
    root = Path(project_root)
    results_dir = root / SIM_RESULTS_DIR
    
    if not results_dir.exists():
        return []
    
    json_files = list(results_dir.glob("*.json"))
    json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    results = []
    for file_path in json_files[:limit]:
        data = _read_json_file(file_path)
        if data:
            results.append({
                "id": data.get("id", file_path.stem),
                "circuit_file": data.get("circuit_file", ""),
                "analysis_type": data.get("analysis_type", ""),
                "status": data.get("status", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "path": str(file_path.relative_to(root)),
            })
    
    return results


def get_latest_sim_result(project_root: str) -> LoadResult[Dict[str, Any]]:
    """获取最新的仿真结果"""
    results = list_sim_results(project_root, limit=1)
    if results:
        return load_sim_result(project_root, results[0]["path"])
    return LoadResult.file_missing("")


def delete_sim_result(project_root: str, result_path: str) -> bool:
    """删除仿真结果文件"""
    root = Path(project_root)
    file_path = root / result_path
    
    if file_path.exists():
        try:
            file_path.unlink()
            return True
        except Exception:
            return False
    return False


def get_sim_result_path(
    project_root: str,
    result_id: Optional[str] = None
) -> str:
    """获取仿真结果文件路径"""
    root = Path(project_root)
    if result_id:
        return str(root / SIM_RESULTS_DIR / f"{result_id}.json")
    return str(root / SIM_RESULTS_DIR)


# ============================================================
# 高级仿真
# ============================================================

def run_pvt_analysis(
    project_root: str,
    circuit_file: str,
    corners: List[PVTCorner],
    base_config: Optional[SimulationConfig] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    执行 PVT 角点分析
    
    对每个 PVT 角点执行仿真，汇总结果。
    
    Args:
        project_root: 项目根目录路径
        circuit_file: 电路文件相对路径
        corners: PVT 角点列表
        base_config: 基础仿真配置
        
    Returns:
        Tuple[str, Dict]: (结果文件相对路径, 指标摘要)
    """
    root = Path(project_root)
    result_id = _generate_result_id("pvt")
    result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
    result_path = root / result_rel_path
    result_path.parent.mkdir(parents=True, exist_ok=True)
    
    if base_config is None:
        base_config = SimulationConfig(analysis_type=AnalysisType.AC)
    
    corner_results = []
    all_metrics = {}
    
    for corner in corners:
        # 为每个角点创建配置
        corner_config = SimulationConfig(
            analysis_type=base_config.analysis_type,
            parameters=base_config.parameters.copy(),
            temperature=corner.temperature,
            include_files=base_config.include_files.copy(),
            options=base_config.options.copy(),
            timeout=base_config.timeout,
        )
        
        try:
            _, metrics = run_simulation(
                project_root, circuit_file, corner_config
            )
            corner_results.append({
                "corner": corner.to_dict(),
                "status": "completed",
                "metrics": metrics,
            })
            all_metrics[corner.name] = metrics
        except Exception as e:
            corner_results.append({
                "corner": corner.to_dict(),
                "status": "failed",
                "error": str(e),
            })
    
    # 汇总结果
    pvt_result = {
        "id": result_id,
        "type": "pvt_analysis",
        "circuit_file": circuit_file,
        "timestamp": datetime.now().isoformat(),
        "corners": corner_results,
        "summary": _summarize_pvt_results(all_metrics),
    }
    
    _write_json_file(result_path, pvt_result)
    
    return result_rel_path, pvt_result["summary"]


def run_monte_carlo(
    project_root: str,
    circuit_file: str,
    mc_config: MonteCarloConfig,
    base_config: Optional[SimulationConfig] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    执行蒙特卡洛分析
    
    Args:
        project_root: 项目根目录路径
        circuit_file: 电路文件相对路径
        mc_config: 蒙特卡洛配置
        base_config: 基础仿真配置
        
    Returns:
        Tuple[str, Dict]: (结果文件相对路径, 统计摘要)
    """
    root = Path(project_root)
    result_id = _generate_result_id("mc")
    result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
    result_path = root / result_rel_path
    result_path.parent.mkdir(parents=True, exist_ok=True)
    
    if base_config is None:
        base_config = SimulationConfig(analysis_type=AnalysisType.AC)
    
    # TODO: 实现参数变化逻辑
    # 当前为框架实现，实际蒙特卡洛需要修改电路参数
    
    iteration_results = []
    all_metrics_values: Dict[str, List[float]] = {}
    
    for i in range(mc_config.iterations):
        try:
            _, metrics = run_simulation(
                project_root, circuit_file, base_config
            )
            iteration_results.append({
                "iteration": i,
                "status": "completed",
                "metrics": metrics,
            })
            
            # 收集指标值用于统计
            for key, value in metrics.items():
                if isinstance(value, (int, float)):
                    if key not in all_metrics_values:
                        all_metrics_values[key] = []
                    all_metrics_values[key].append(value)
                    
        except Exception as e:
            iteration_results.append({
                "iteration": i,
                "status": "failed",
                "error": str(e),
            })
    
    # 统计分析
    statistics = _compute_statistics(all_metrics_values)
    
    mc_result = {
        "id": result_id,
        "type": "monte_carlo",
        "circuit_file": circuit_file,
        "timestamp": datetime.now().isoformat(),
        "config": mc_config.to_dict(),
        "iterations": iteration_results,
        "statistics": statistics,
    }
    
    _write_json_file(result_path, mc_result)
    
    return result_rel_path, statistics


def run_parametric_sweep(
    project_root: str,
    circuit_file: str,
    sweep_config: ParametricSweepConfig,
    base_config: Optional[SimulationConfig] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    执行参数扫描
    
    Args:
        project_root: 项目根目录路径
        circuit_file: 电路文件相对路径
        sweep_config: 参数扫描配置
        base_config: 基础仿真配置
        
    Returns:
        Tuple[str, Dict]: (结果文件相对路径, 扫描摘要)
    """
    root = Path(project_root)
    result_id = _generate_result_id("sweep")
    result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
    result_path = root / result_rel_path
    result_path.parent.mkdir(parents=True, exist_ok=True)
    
    if base_config is None:
        base_config = SimulationConfig(analysis_type=AnalysisType.AC)
    
    # 生成扫描点
    sweep_points = _generate_sweep_points(sweep_config)
    
    sweep_results = []
    
    for point_value in sweep_points:
        # TODO: 实现参数修改逻辑
        try:
            _, metrics = run_simulation(
                project_root, circuit_file, base_config
            )
            sweep_results.append({
                "parameter_value": point_value,
                "status": "completed",
                "metrics": metrics,
            })
        except Exception as e:
            sweep_results.append({
                "parameter_value": point_value,
                "status": "failed",
                "error": str(e),
            })
    
    sweep_result = {
        "id": result_id,
        "type": "parametric_sweep",
        "circuit_file": circuit_file,
        "timestamp": datetime.now().isoformat(),
        "config": sweep_config.to_dict(),
        "results": sweep_results,
    }
    
    _write_json_file(result_path, sweep_result)
    
    return result_rel_path, {"points": len(sweep_results)}


# ============================================================
# 内部辅助函数
# ============================================================

def _generate_result_id(prefix: str = "sim") -> str:
    """生成仿真结果 ID"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"


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


def _extract_metrics_from_data(
    raw_data: Dict[str, Any],
    analysis_type: AnalysisType
) -> Dict[str, Any]:
    """从原始仿真数据中提取关键指标"""
    metrics = {}
    vectors = raw_data.get("vectors", {})
    
    if analysis_type == AnalysisType.AC:
        # AC 分析：提取增益、带宽、相位裕度
        metrics.update(_extract_ac_metrics(vectors))
    elif analysis_type == AnalysisType.TRAN:
        # 瞬态分析：提取上升时间、过冲等
        metrics.update(_extract_tran_metrics(vectors))
    elif analysis_type == AnalysisType.DC:
        # DC 分析：提取工作点信息
        metrics.update(_extract_dc_metrics(vectors))
    elif analysis_type == AnalysisType.OP:
        # 工作点分析
        metrics.update(_extract_op_metrics(vectors))
    
    return metrics


def _extract_ac_metrics(vectors: Dict[str, List[float]]) -> Dict[str, Any]:
    """提取 AC 分析指标"""
    metrics = {}
    
    # 查找输出节点的增益数据
    for key, values in vectors.items():
        if "_db" in key and values:
            # 找到最大增益
            max_gain = max(values)
            metrics["max_gain_db"] = round(max_gain, 2)
            
            # 计算 -3dB 带宽
            if "frequency" in vectors:
                freq = vectors["frequency"]
                threshold = max_gain - 3
                for i, gain in enumerate(values):
                    if gain < threshold:
                        if i > 0:
                            metrics["bandwidth_hz"] = freq[i]
                        break
            break
    
    # 查找相位数据
    for key, values in vectors.items():
        if "_phase" in key and values:
            # 相位裕度（简化计算）
            if len(values) > 0:
                metrics["phase_at_dc"] = round(values[0], 1)
            break
    
    return metrics


def _extract_tran_metrics(vectors: Dict[str, List[float]]) -> Dict[str, Any]:
    """提取瞬态分析指标"""
    metrics = {}
    
    # 查找输出电压
    for key, values in vectors.items():
        if key.startswith("v(") and values:
            v_max = max(values)
            v_min = min(values)
            metrics["v_max"] = round(v_max, 4)
            metrics["v_min"] = round(v_min, 4)
            metrics["v_pp"] = round(v_max - v_min, 4)
            break
    
    return metrics


def _extract_dc_metrics(vectors: Dict[str, List[float]]) -> Dict[str, Any]:
    """提取 DC 分析指标"""
    metrics = {}
    
    for key, values in vectors.items():
        if key.startswith("v(") and values:
            metrics[f"{key}_range"] = [
                round(min(values), 4),
                round(max(values), 4)
            ]
    
    return metrics


def _extract_op_metrics(vectors: Dict[str, List[float]]) -> Dict[str, Any]:
    """提取工作点分析指标"""
    metrics = {}
    
    for key, values in vectors.items():
        if values:
            metrics[key] = round(values[0], 6) if len(values) == 1 else values
    
    return metrics


def _summarize_pvt_results(all_metrics: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """汇总 PVT 分析结果"""
    if not all_metrics:
        return {"status": "no_data"}
    
    summary = {"corner_count": len(all_metrics)}
    
    # 收集各角点的关键指标
    metric_values: Dict[str, List[float]] = {}
    for corner_name, metrics in all_metrics.items():
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                if key not in metric_values:
                    metric_values[key] = []
                metric_values[key].append(value)
    
    # 计算最差情况
    for key, values in metric_values.items():
        if values:
            summary[f"{key}_min"] = min(values)
            summary[f"{key}_max"] = max(values)
    
    return summary


def _compute_statistics(values_dict: Dict[str, List[float]]) -> Dict[str, Any]:
    """计算统计数据"""
    import math
    
    stats = {}
    
    for key, values in values_dict.items():
        if not values:
            continue
        
        n = len(values)
        mean = sum(values) / n
        
        # 标准差
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance)
        
        stats[key] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "count": n,
        }
    
    return stats


def _generate_sweep_points(config: ParametricSweepConfig) -> List[float]:
    """生成参数扫描点"""
    import math
    
    if config.points:
        n = config.points
    elif config.step:
        n = int((config.stop - config.start) / config.step) + 1
    else:
        n = 11  # 默认 11 个点
    
    if config.scale == "log" and config.start > 0:
        # 对数刻度
        log_start = math.log10(config.start)
        log_stop = math.log10(config.stop)
        return [10 ** (log_start + i * (log_stop - log_start) / (n - 1)) for i in range(n)]
    else:
        # 线性刻度
        return [config.start + i * (config.stop - config.start) / (n - 1) for i in range(n)]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 核心仿真
    "run_simulation",
    "run_simulation_async",
    # 结果读取
    "load_sim_result",
    "extract_metrics",
    "list_sim_results",
    "get_latest_sim_result",
    "delete_sim_result",
    "get_sim_result_path",
    # 高级仿真
    "run_pvt_analysis",
    "run_monte_carlo",
    "run_parametric_sweep",
    # 常量
    "SIM_RESULTS_DIR",
    # 类型导出
    "LoadResult",
    "LoadErrorCode",
]
