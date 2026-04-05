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

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from domain.simulation.executor.executor_registry import ExecutorRegistry, executor_registry
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
)
from shared.constants.paths import SIM_RESULTS_DIR

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
    ):
        """
        初始化仿真服务
        
        Args:
            registry: 执行器注册表（可选，默认使用全局单例）
        """
        self._logger = logging.getLogger(__name__)
        self._registry = registry or executor_registry
        
        # 内部状态
        self._is_running = False
        self._last_simulation_file: Optional[Path] = None
        self._last_progress_time = 0.0
    
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
                    saved_result_path = self.save_sim_result(project_root, result)
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
                saved_result_path = self.save_sim_result(project_root, result)
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
                saved_result_path = self.save_sim_result(project_root, result)
                self._logger.info(f"仿真结果已保存: {saved_result_path}")
            self._publish_complete_event(result, saved_result_path)
            return result
            
        finally:
            self._is_running = False
    
    # ============================================================
    # 仿真控制方法
    # ============================================================
    
    def cancel_simulation(self) -> bool:
        """
        取消当前仿真
        
        注意：由于使用 ngspice 共享库模式，无法真正中断正在执行的仿真。
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
