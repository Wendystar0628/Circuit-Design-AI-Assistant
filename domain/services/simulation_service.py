# Simulation Service - Simulation Execution and Result Management
"""
仿真服务 - 仿真执行与结果管理

职责：
- 提供仿真执行的统一入口
- 管理仿真状态
- 协调执行器和配置
- 存储和加载仿真结果
- 发布仿真事件

设计原则：
- 作为仿真域的核心服务，直接实现仿真执行逻辑
- 无状态设计：仿真结果直接写入文件
- 幂等性：相同输入产生相同输出

存储路径：
- 仿真结果：{project_root}/.circuit_ai/sim_results/{uuid}.json

被调用方：
- simulation_worker.py: 后台仿真任务
- main_window.py: UI 触发仿真
- tool_executor.py: LLM 工具调用

使用示例：
    from domain.services.simulation_service import SimulationService
    
    service = SimulationService()
    
    # 执行仿真
    result = service.run_simulation(
        file_path="amplifier.cir",
        analysis_config={"analysis_type": "ac"}
    )
    
    # 自动检测主电路并执行仿真
    result = service.run_with_auto_detect(
        project_path="/path/to/project",
        analysis_config={"analysis_type": "ac"}
    )
    
    # 获取可仿真文件列表
    files = service.get_simulatable_files("/path/to/project")
"""

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from domain.simulation.executor.executor_registry import ExecutorRegistry, executor_registry
from domain.simulation.executor.circuit_analyzer import (
    CircuitAnalyzer,
    MainCircuitDetectionResult,
    ScanResult,
)
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
    create_error_result,
)
from domain.simulation.models.simulation_error import (
    SimulationError,
    SimulationErrorType,
    ErrorSeverity,
)
from shared.models.load_result import LoadResult
from shared.event_bus import EventBus
from shared.event_types import (
    EVENT_SIM_STARTED,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_PROGRESS,
    EVENT_SIM_ERROR,
    EVENT_MAIN_CIRCUIT_DETECTED,
    EVENT_SIMULATION_NEED_SELECTION,
    EVENT_SIMULATION_NO_MAIN_CIRCUIT,
)

# 全局事件总线实例（延迟获取）
_event_bus: Optional[EventBus] = None


def _get_event_bus() -> Optional[EventBus]:
    """获取事件总线实例"""
    global _event_bus
    if _event_bus is None:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SERVICE_EVENT_BUS
            _event_bus = ServiceLocator.get(SERVICE_EVENT_BUS)
        except Exception:
            # 服务未注册，创建临时实例
            _event_bus = EventBus()
    return _event_bus


# ============================================================
# 常量定义
# ============================================================

# 仿真结果目录相对路径
SIM_RESULTS_DIR = ".circuit_ai/sim_results"

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 300

# 进度事件节流间隔（秒）
PROGRESS_THROTTLE_INTERVAL = 0.5


# ============================================================
# SimulationService - 仿真服务
# ============================================================

class SimulationService:
    """
    仿真服务
    
    提供仿真执行的统一入口，管理仿真状态，协调执行器和配置。
    
    特性：
    - 统一入口：所有仿真请求通过此服务
    - 自动选择执行器：根据文件扩展名自动选择合适的执行器
    - 事件发布：仿真开始、进度、完成时发布事件
    - 结果持久化：仿真结果自动保存到文件
    """
    
    def __init__(
        self,
        registry: Optional[ExecutorRegistry] = None,
        analyzer: Optional[CircuitAnalyzer] = None,
    ):
        """
        初始化仿真服务
        
        Args:
            registry: 执行器注册表（可选，默认使用全局单例）
            analyzer: 电路分析器（可选，默认创建新实例）
        """
        self._logger = logging.getLogger(__name__)
        self._registry = registry or executor_registry
        self._analyzer = analyzer or CircuitAnalyzer(self._registry)
        
        # 内部状态
        self._is_running = False
        self._last_simulation_file: Optional[Path] = None
        self._main_circuit_candidates: List[Path] = []
        self._last_progress_time = 0.0
    
    # ============================================================
    # 核心仿真方法
    # ============================================================
    
    def run_simulation(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        *,
        project_root: Optional[str] = None,
        version: int = 1,
        session_id: str = "",
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> SimulationResult:
        """
        执行仿真并返回结果
        
        Args:
            file_path: 电路文件路径
            analysis_config: 仿真配置字典
            project_root: 项目根目录（用于保存结果）
            version: 版本号（对应 GraphState.iteration_count + 1）
            session_id: 会话 ID
            on_progress: 进度回调函数
            
        Returns:
            SimulationResult: 仿真结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 标记正在运行
        self._is_running = True
        self._last_simulation_file = Path(file_path)
        
        try:
            # 发布仿真开始事件
            self._publish_started_event(file_path, analysis_type, analysis_config)
            
            # 获取执行器
            executor = self._registry.get_executor_for_file(file_path)
            if executor is None:
                error = SimulationError(
                    code="E011",
                    type=SimulationErrorType.PARAMETER_INVALID,
                    severity=ErrorSeverity.HIGH,
                    message=f"没有执行器支持文件类型: {Path(file_path).suffix}",
                    file_path=file_path,
                    recovery_suggestion=f"支持的扩展名: {', '.join(self._registry.get_all_supported_extensions())}",
                )
                result = create_error_result(
                    executor="unknown",
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=error,
                    duration_seconds=time.time() - start_time,
                    version=version,
                    session_id=session_id,
                )
                self._publish_error_event(result)
                return result
            
            # 执行仿真
            self._logger.info(f"使用执行器 '{executor.get_name()}' 执行仿真: {file_path}")
            result = executor.execute(file_path, analysis_config)
            
            # 补充版本和会话信息
            result.version = version
            result.session_id = session_id
            
            # 保存结果到文件
            if project_root:
                result_path = self.save_sim_result(project_root, result)
                self._logger.info(f"仿真结果已保存: {result_path}")
            
            # 发布完成事件
            self._publish_complete_event(result)
            
            return result
            
        except Exception as e:
            self._logger.exception(f"仿真执行异常: {e}")
            error = SimulationError(
                code="E999",
                type=SimulationErrorType.NGSPICE_CRASH,
                severity=ErrorSeverity.CRITICAL,
                message=str(e),
                file_path=file_path,
            )
            result = create_error_result(
                executor="unknown",
                file_path=file_path,
                analysis_type=analysis_type,
                error=error,
                duration_seconds=time.time() - start_time,
                version=version,
                session_id=session_id,
            )
            self._publish_error_event(result)
            return result
            
        finally:
            self._is_running = False

    def run_with_auto_detect(
        self,
        project_path: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        *,
        version: int = 1,
        session_id: str = "",
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> SimulationResult:
        """
        自动检测主电路并执行仿真
        
        流程：
        1. 扫描项目目录，检测主电路候选
        2. 如果只有一个候选，直接执行仿真
        3. 如果有多个候选，发布 EVENT_SIMULATION_NEED_SELECTION 事件
        4. 如果没有候选，发布 EVENT_SIMULATION_NO_MAIN_CIRCUIT 事件
        
        Args:
            project_path: 项目根目录路径
            analysis_config: 仿真配置字典
            version: 版本号
            session_id: 会话 ID
            on_progress: 进度回调函数
            
        Returns:
            SimulationResult: 仿真结果
        """
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 检测主电路
        detection_result = self._analyzer.detect_main_circuit(project_path)
        
        # 更新候选列表
        self._main_circuit_candidates = []
        if detection_result.main_circuit:
            self._main_circuit_candidates.append(Path(detection_result.main_circuit))
        for candidate in detection_result.candidates:
            self._main_circuit_candidates.append(Path(candidate["path"]))
        
        # 发布检测完成事件
        bus = _get_event_bus()
        if bus:
            bus.publish(EVENT_MAIN_CIRCUIT_DETECTED, {
                "candidates": [str(p) for p in self._main_circuit_candidates],
                "count": len(self._main_circuit_candidates),
            })
        
        # 根据候选数量决定下一步
        if not self._main_circuit_candidates:
            # 没有候选
            bus = _get_event_bus()
            if bus:
                bus.publish(EVENT_SIMULATION_NO_MAIN_CIRCUIT, {
                    "reason": "no_main_circuit",
                })
            return create_error_result(
                executor="unknown",
                file_path="",
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E012",
                    type=SimulationErrorType.FILE_ACCESS,
                    severity=ErrorSeverity.HIGH,
                    message="未找到主电路文件",
                    recovery_suggestion="请确保项目中包含带有仿真控制语句的电路文件",
                ),
                version=version,
                session_id=session_id,
            )
        
        if len(self._main_circuit_candidates) > 1:
            # 多个候选，需要用户选择
            bus = _get_event_bus()
            if bus:
                bus.publish(EVENT_SIMULATION_NEED_SELECTION, {
                    "candidates": [str(p) for p in self._main_circuit_candidates],
                    "reason": "multiple_main_circuits",
                })
            return create_error_result(
                executor="unknown",
                file_path="",
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E013",
                    type=SimulationErrorType.PARAMETER_INVALID,
                    severity=ErrorSeverity.MEDIUM,
                    message=f"检测到 {len(self._main_circuit_candidates)} 个主电路候选，请选择一个",
                    recovery_suggestion="请从候选列表中选择要仿真的主电路文件",
                ),
                version=version,
                session_id=session_id,
            )
        
        # 只有一个候选，直接执行
        main_circuit = self._main_circuit_candidates[0]
        file_path = str(Path(project_path) / main_circuit)
        
        return self.run_simulation(
            file_path=file_path,
            analysis_config=analysis_config,
            project_root=project_path,
            version=version,
            session_id=session_id,
            on_progress=on_progress,
        )
    
    # ============================================================
    # 文件扫描方法
    # ============================================================
    
    def get_simulatable_files(self, project_path: str) -> List[Path]:
        """
        获取可仿真文件列表
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            List[Path]: 可仿真文件路径列表（相对路径）
        """
        scan_result = self._analyzer.scan_simulatable_files(project_path)
        return scan_result.files
    
    def get_main_circuit_candidates(self, project_path: str) -> List[Path]:
        """
        获取主电路候选列表
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            List[Path]: 主电路候选路径列表（相对路径）
        """
        scan_result = self._analyzer.scan_simulatable_files(project_path)
        return scan_result.main_circuit_candidates
    
    def scan_project(self, project_path: str) -> ScanResult:
        """
        扫描项目目录
        
        Args:
            project_path: 项目根目录路径
            
        Returns:
            ScanResult: 扫描结果
        """
        return self._analyzer.scan_simulatable_files(project_path)
    
    # ============================================================
    # 仿真控制方法
    # ============================================================
    
    def cancel_simulation(self) -> bool:
        """
        取消当前仿真
        
        注意：由于 PySpice 使用共享库模式，无法真正中断正在执行的仿真。
        此方法仅设置标志位，仿真会在下一个检查点停止。
        
        Returns:
            bool: 是否成功发送取消请求
        """
        if not self._is_running:
            self._logger.warning("没有正在运行的仿真")
            return False
        
        self._logger.info("请求取消仿真")
        # 实际取消逻辑需要在执行器中实现超时机制
        return True
    
    def is_running(self) -> bool:
        """
        检查是否有仿真正在运行
        
        Returns:
            bool: 是否正在运行
        """
        return self._is_running
    
    def get_last_simulation_file(self) -> Optional[Path]:
        """
        获取上次仿真的文件路径
        
        Returns:
            Optional[Path]: 文件路径，若无则返回 None
        """
        return self._last_simulation_file

    # ============================================================
    # 结果存储方法
    # ============================================================
    
    def save_sim_result(
        self,
        project_root: str,
        result: SimulationResult,
    ) -> str:
        """
        保存仿真结果到文件
        
        Args:
            project_root: 项目根目录路径
            result: 仿真结果对象
            
        Returns:
            str: 结果文件相对路径
        """
        root = Path(project_root)
        
        # 生成结果文件路径
        result_id = self._generate_result_id()
        result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
        result_path = root / result_rel_path
        
        # 确保目录存在
        result_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 序列化并写入
        result_dict = result.to_dict()
        result_dict["id"] = result_id
        
        content = json.dumps(result_dict, indent=2, ensure_ascii=False)
        result_path.write_text(content, encoding="utf-8")
        
        return result_rel_path
    
    def load_sim_result(
        self,
        project_root: str,
        result_path: str,
    ) -> LoadResult[SimulationResult]:
        """
        从文件加载仿真结果
        
        Args:
            project_root: 项目根目录路径
            result_path: 结果文件相对路径
            
        Returns:
            LoadResult[SimulationResult]: 加载结果对象
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
            result = SimulationResult.from_dict(data)
            return LoadResult.ok(result, result_path)
            
        except json.JSONDecodeError as e:
            return LoadResult.parse_error(result_path, f"JSON 解析失败: {e}")
        except KeyError as e:
            return LoadResult.parse_error(result_path, f"缺少必需字段: {e}")
        except Exception as e:
            return LoadResult.unknown_error(result_path, str(e))
    
    def list_sim_results(
        self,
        project_root: str,
        limit: int = 10,
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
            try:
                content = file_path.read_text(encoding="utf-8")
                data = json.loads(content)
                results.append({
                    "id": data.get("id", file_path.stem),
                    "file_path": data.get("file_path", ""),
                    "analysis_type": data.get("analysis_type", ""),
                    "success": data.get("success", False),
                    "timestamp": data.get("timestamp", ""),
                    "path": str(file_path.relative_to(root)),
                })
            except Exception:
                continue
        
        return results
    
    def get_latest_sim_result(
        self,
        project_root: str,
    ) -> LoadResult[SimulationResult]:
        """
        获取最新的仿真结果
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            LoadResult[SimulationResult]: 加载结果对象
        """
        results = self.list_sim_results(project_root, limit=1)
        if results:
            return self.load_sim_result(project_root, results[0]["path"])
        return LoadResult.file_missing("")
    
    def delete_sim_result(
        self,
        project_root: str,
        result_path: str,
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
            except Exception as e:
                self._logger.error(f"删除仿真结果失败: {e}")
                return False
        return False

    # ============================================================
    # 内部辅助方法
    # ============================================================
    
    def _get_analysis_type(self, analysis_config: Optional[Dict[str, Any]]) -> str:
        """从配置中提取分析类型"""
        if analysis_config is None:
            return "ac"
        return analysis_config.get("analysis_type", "ac")
    
    def _generate_result_id(self) -> str:
        """生成仿真结果 ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"sim_{timestamp}_{short_uuid}"
    
    def _publish_started_event(
        self,
        file_path: str,
        analysis_type: str,
        config: Optional[Dict[str, Any]],
    ) -> None:
        """发布仿真开始事件"""
        bus = _get_event_bus()
        if bus:
            bus.publish(EVENT_SIM_STARTED, {
                "circuit_file": file_path,
                "simulation_type": analysis_type,
                "config": config or {},
            })
    
    def _publish_progress_event(
        self,
        progress: float,
        current_step: str,
        elapsed_seconds: float,
    ) -> None:
        """发布仿真进度事件（带节流）"""
        current_time = time.time()
        if current_time - self._last_progress_time < PROGRESS_THROTTLE_INTERVAL:
            return
        
        self._last_progress_time = current_time
        bus = _get_event_bus()
        if bus:
            bus.publish(EVENT_SIM_PROGRESS, {
                "progress": progress,
                "current_step": current_step,
                "elapsed_seconds": elapsed_seconds,
            })
    
    def _publish_complete_event(self, result: SimulationResult) -> None:
        """发布仿真完成事件"""
        bus = _get_event_bus()
        if bus:
            bus.publish(EVENT_SIM_COMPLETE, {
                "result_path": "",  # 由调用方填充
                "metrics": result.metrics or {},
                "duration_seconds": result.duration_seconds,
                "success": result.success,
            })
    
    def _publish_error_event(self, result: SimulationResult) -> None:
        """发布仿真错误事件"""
        error = result.error
        error_type = ""
        error_message = ""
        
        if isinstance(error, SimulationError):
            error_type = error.type.value if error.type else ""
            error_message = error.message
        elif error is not None:
            error_message = str(error)
        
        bus = _get_event_bus()
        if bus:
            bus.publish(EVENT_SIM_ERROR, {
                "error_type": error_type,
                "error_message": error_message,
                "file": result.file_path,
                "recoverable": False,
            })


# ============================================================
# 模块级便捷函数（兼容旧接口）
# ============================================================

# 全局服务实例
_service: Optional[SimulationService] = None


def _get_service() -> SimulationService:
    """获取全局服务实例"""
    global _service
    if _service is None:
        _service = SimulationService()
    return _service


def run_simulation(
    project_root: str,
    circuit_file: str,
    *,
    analysis_type: str = "ac",
    parameters: Optional[Dict[str, Any]] = None,
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
    """
    service = _get_service()
    
    # 构建完整路径
    file_path = str(Path(project_root) / circuit_file)
    
    # 构建配置
    config = {"analysis_type": analysis_type}
    if parameters:
        config.update(parameters)
    
    # 执行仿真
    result = service.run_simulation(
        file_path=file_path,
        analysis_config=config,
        project_root=project_root,
    )
    
    # 保存结果
    result_path = service.save_sim_result(project_root, result)
    
    # 提取指标
    metrics = extract_metrics(result.to_dict(), {})
    
    return result_path, metrics


def load_sim_result(
    project_root: str,
    result_path: str,
) -> LoadResult[Dict[str, Any]]:
    """
    从文件加载仿真结果
    
    Args:
        project_root: 项目根目录路径
        result_path: 结果文件相对路径
        
    Returns:
        LoadResult[Dict]: 加载结果对象
    """
    service = _get_service()
    load_result = service.load_sim_result(project_root, result_path)
    
    if load_result.success and load_result.data is not None:
        return LoadResult.ok(load_result.data.to_dict(), result_path)
    
    return load_result


def extract_metrics(
    sim_data: Dict[str, Any],
    goals: Dict[str, Any],
) -> Dict[str, Any]:
    """
    从仿真结果中提取性能指标摘要
    
    Args:
        sim_data: 仿真结果数据
        goals: 设计目标
        
    Returns:
        Dict: 性能指标摘要
    """
    if not sim_data:
        return {"status": "no_data"}
    
    metrics = {
        "status": "completed" if sim_data.get("success") else "failed",
        "timestamp": sim_data.get("timestamp", ""),
    }
    
    # 从仿真数据中提取指标
    raw_metrics = sim_data.get("metrics", {})
    
    if goals:
        for goal_key in goals.keys():
            if goal_key in raw_metrics:
                metrics[goal_key] = raw_metrics[goal_key]
    else:
        metrics.update(raw_metrics)
    
    return metrics


def get_sim_result_path(
    project_root: str,
    result_id: Optional[str] = None,
) -> str:
    """获取仿真结果文件路径"""
    root = Path(project_root)
    if result_id:
        return str(root / SIM_RESULTS_DIR / f"{result_id}.json")
    return str(root / SIM_RESULTS_DIR)


def list_sim_results(
    project_root: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """列出最近的仿真结果"""
    return _get_service().list_sim_results(project_root, limit)


def get_latest_sim_result(project_root: str) -> LoadResult[Dict[str, Any]]:
    """获取最新的仿真结果"""
    service = _get_service()
    load_result = service.get_latest_sim_result(project_root)
    
    if load_result.success and load_result.data is not None:
        return LoadResult.ok(load_result.data.to_dict(), load_result.file_path or "")
    
    return load_result


def delete_sim_result(
    project_root: str,
    result_path: str,
) -> bool:
    """删除仿真结果文件"""
    return _get_service().delete_sim_result(project_root, result_path)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 类
    "SimulationService",
    # 便捷函数
    "run_simulation",
    "load_sim_result",
    "extract_metrics",
    "get_sim_result_path",
    "list_sim_results",
    "get_latest_sim_result",
    "delete_sim_result",
    # 常量
    "SIM_RESULTS_DIR",
    # 类型
    "LoadResult",
]
