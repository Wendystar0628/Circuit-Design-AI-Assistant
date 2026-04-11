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
    
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from domain.simulation.executor.executor_registry import ExecutorRegistry, executor_registry
from domain.simulation.models.simulation_result import (
    SimulationResult,
    create_error_result,
)
from domain.simulation.service.simulation_result_repository import SimulationResultRepository, simulation_result_repository
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
    EVENT_SIM_ERROR,
)

# 全局事件总线实例（延迟获取）
_event_bus: Optional[EventBus] = None


def _get_event_bus() -> Optional[EventBus]:
    """获取事件总线实例"""
    global _event_bus
    if _event_bus is None:
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_EVENT_BUS
            _event_bus = ServiceLocator.get(SVC_EVENT_BUS)
        except Exception:
            # 服务未注册，创建临时实例
            _event_bus = EventBus()
    return _event_bus


# ============================================================
# 常量定义
# ============================================================

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 300

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
    - 事件发布：仿真开始、完成、错误时发布事件
    - 结果持久化：仿真结果自动保存到文件
    """
    
    def __init__(
        self,
        registry: Optional[ExecutorRegistry] = None,
        result_repository: Optional[SimulationResultRepository] = None,
    ):
        """
        初始化仿真服务
        
        Args:
            registry: 执行器注册表（可选，默认使用全局单例）
        """
        self._logger = logging.getLogger(__name__)
        self._registry = registry or executor_registry
        self._result_repository = result_repository or simulation_result_repository
        
        # 内部状态
        self._is_running = False
        self._last_simulation_file: Optional[Path] = None
    
    # ============================================================
    # 核心仿真方法
    # ============================================================
    
    def run_simulation(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None,
        project_root: Optional[str] = None,
        version: int = 1,
        session_id: str = "",
    ) -> SimulationResult:
        """
        执行仿真并返回结果
        
        Args:
            file_path: 电路文件路径
            analysis_config: 仿真配置字典
            project_root: 项目根目录（用于保存结果）
            version: 版本号（对应 GraphState.iteration_count + 1）
            session_id: 会话 ID
            
        Returns:
            SimulationResult: 仿真结果
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        if not analysis_type:
            analysis_type = self._detect_analysis_type_from_file(file_path)
        
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
                saved_result_path = ""
                if project_root:
                    saved_result_path = self._result_repository.save(project_root, result)
                    self._logger.info(f"仿真结果已保存: {saved_result_path}")
                self._publish_complete_event(result, saved_result_path)
                return result
            
            # 执行仿真
            self._logger.info(f"使用执行器 '{executor.get_name()}' 执行仿真: {file_path}")
            result = executor.execute(file_path, analysis_config)
            
            # 补充版本和会话信息
            result.version = version
            result.session_id = session_id
            
            # 保存结果到文件
            saved_result_path = ""
            if project_root:
                saved_result_path = self._result_repository.save(project_root, result)
                self._logger.info(f"仿真结果已保存: {saved_result_path}")
            
            # 发布完成事件（传递保存的结果路径）
            self._publish_complete_event(result, saved_result_path)
            
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
            saved_result_path = ""
            if project_root:
                saved_result_path = self._result_repository.save(project_root, result)
                self._logger.info(f"仿真结果已保存: {saved_result_path}")
            self._publish_complete_event(result, saved_result_path)
            return result
            
        finally:
            self._is_running = False
    
    # ============================================================
    # 仿真控制方法
    # ============================================================

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
    # 内部辅助方法
    # ============================================================
    
    def _detect_analysis_type_from_file(self, file_path: str) -> str:
        """从网表文件中检测最后一条分析命令的类型"""
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

        analysis_type = ""
        for line in content.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("*"):
                continue
            for cmd in (".ac", ".dc", ".tran", ".noise", ".op"):
                if stripped == cmd or (
                    stripped.startswith(cmd)
                    and len(stripped) > len(cmd)
                    and stripped[len(cmd)] in (" ", "\t")
                ):
                    analysis_type = cmd[1:]
                    break
        return analysis_type

    def _get_analysis_type(self, analysis_config: Optional[Dict[str, Any]]) -> str:
        """从配置中提取分析类型，若未指定则返回空字符串（由执行器自动检测）"""
        if analysis_config is None:
            return ""
        return analysis_config.get("analysis_type", "")
    
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
    
    def _publish_complete_event(self, result: SimulationResult, result_path: str = "") -> None:
        """
        发布仿真完成事件
        
        Args:
            result: 仿真结果对象
            result_path: 仿真结果文件的相对路径
        """
        bus = _get_event_bus()
        if bus:
            bus.publish(EVENT_SIM_COMPLETE, {
                "result_path": result_path,
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
# 模块导出
# ============================================================

__all__ = [
    # 类
    "SimulationService",
    # 类型
    "LoadResult",
]
