# SpiceExecutor - SPICE Simulation Executor
"""
SPICE 仿真执行器

职责：
- 通过 NgSpiceWrapper 执行 SPICE 电路仿真
- 执行主网表中唯一的 AC、DC、瞬态、噪声或工作点分析卡
- 把递归 include/lib 源闭包固定到不可变临时镜像后再运行

执行模式说明：
- 通过 ctypes 直接调用 ngspice 共享库
- ngspice 在同一进程内执行，不需要启动独立子进程
- 这种模式性能更高，且完全控制与 ngspice 的交互

源文件策略：
- 主文件与依赖各读取一次，由同一 source-closure graph 产生摘要与运行镜像
- ngspice 只读取该镜像，不修改进程工作目录，也不在执行期重读原始依赖

该类是 ``SimulationService`` 的内部 native adapter；产品调用统一经
``SimulationJobManager`` 提交，以保证取消、生命周期事件和结果落盘契约。
"""

import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from domain.simulation.executor.ngspice_shared import (
    NgSpiceWrapper,
    NgSpiceError,
    NgSpiceCancelledError,
    NgSpiceCommandError,
    NgSpiceTimeoutError,
    VectorType,
)
from domain.simulation.data.signal_semantics import (
    normalize_simulation_signal_name,
    resolve_vector_signal_type,
)
from domain.simulation.models.simulation_result import (
    NoiseTotals,
    SimulationData,
    SimulationResult,
    create_error_result,
    create_success_result,
)
from domain.simulation.models.simulation_error import (
    SimulationError,
    SimulationErrorType,
    ErrorSeverity,
)
from domain.simulation.measure.measure_authority import (
    MeasureRequest,
    measure_authority,
)
from domain.simulation.spice.directive_tokenizer import (
    is_spice_end_directive,
    tokenize_spice_directive,
)
from domain.simulation.spice.analysis_directive import validate_analysis_command
from domain.simulation.spice.numeric import parse_spice_number
from domain.simulation.spice.source_closure import (
    SpiceSourceClosureError,
    SpiceSourceView,
    snapshot_spice_source_closure,
)
from infrastructure.utils.ngspice_config import (
    is_ngspice_available,
    get_configuration_error,
    get_ngspice_dll_path,
)


# ============================================================
# 常量定义
# ============================================================

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = [".cir", ".sp", ".spice", ".net", ".ckt"]

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 300

# These native ngspice analyses produce additional plots or post-processing
# output that this product does not expose.  Admitting them beside the single
# supported source analysis would silently execute and then discard a user's
# request.  Runtime plot validation below remains the fail-closed backstop for
# future/unknown analysis cards.
_UNSUPPORTED_ANALYSIS_DIRECTIVES = frozenset(
    {
        ".disto",
        ".four",
        ".hb",
        ".pss",
        ".pz",
        ".sens",
        ".sens2",
        ".sp",
        ".tf",
    }
)

# ngspice silently ignores unknown solver options and clamps some invalid
# values (for example ``maxord``) without a machine-readable result contract.
# A partial allow-list would therefore still admit scientific false-successes.
_UNSUPPORTED_RUNTIME_DIRECTIVES = frozenset({".option", ".options"})

# Exact native diagnostics where ngspice continues by discarding or replacing
# user intent.  These are scientific failures, not harmless warnings: a model
# parameter, integration method, device level or requested temperature would
# otherwise silently differ from the source deck.
_NATIVE_SILENT_FALLBACK_PATTERNS = (
    r"(?im)^\s*stderr\s+warning:\s+could not set temperature\b",
    r"(?im)^\s*stderr\s+warning:\s+\.temp card\b",
    r"(?im)^\s*stderr\s+unrecognized parameter\s*\([^)]+\)\s*-\s*ignored\s*$",
    r"(?im)^\s*stderr\s+setanalysisparm\(options\)\s+ci_curopt:\s*"
    r"unsupported integration method\b",
    r"(?im)^\s*stderr\s+illegal value for level\.\s*$",
    r"(?im)^\s*stderr\s+level must be\s*<\s*\d+\s*"
    r"\(setting level to\s*\d+\)\s*$",
    r"(?im)^\s*stderr\s+warning\s*:\s*"
    r"(?:ic|nodeset) on non-existent node\b.*\bignored\s*$",
)

# ngspice exposes process-wide mutable state. The wrapper's per-call locks
# cannot make the multi-step
# destroy -> load -> run -> plot-qualified vector reads transaction atomic, so
# every SpiceExecutor instance shares one lock around the *entire* execute
# call. Manager workers may run concurrently, but native transactions do not.
_SPICE_EXECUTION_LOCK = threading.RLock()


# ============================================================
# SpiceExecutor - SPICE 仿真执行器
# ============================================================

class SpiceExecutor:
    """
    SPICE 仿真执行器
    
    通过 NgSpiceWrapper 直接调用 ngspice 共享库执行 SPICE 电路仿真。
    支持 AC、DC、瞬态、噪声和工作点分析。
    
    特性：
    - 直接调用 ngspice：不依赖 PySpice，避免版本兼容性问题
    - 标准化结果：返回统一的 SimulationResult 数据结构
    - 错误处理：解析 ngspice 输出，提供恢复建议
    - 源闭包隔离：摘要与 ngspice 输入共用同一不可变镜像
    
    注意：ngspice shared library 的电路、plot 和回调是进程级状态，
    多个调用会在完整 native transaction 外层串行化。
    """
    
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT):
        """初始化 SPICE 执行器"""
        self._logger = logging.getLogger(__name__)
        self._ngspice: Optional[NgSpiceWrapper] = None
        self._init_error: Optional[str] = None
        self._timeout_seconds = self._validate_timeout(timeout_seconds)
        
        # 尝试初始化 ngspice
        self._try_init_ngspice()
    
    def _try_init_ngspice(self):
        """尝试初始化 ngspice wrapper"""
        if not is_ngspice_available():
            self._init_error = get_configuration_error() or "ngspice 未正确配置"
            self._logger.warning(f"SpiceExecutor 初始化警告: {self._init_error}")
            return
        
        try:
            dll_path = get_ngspice_dll_path()
            if dll_path:
                self._ngspice = NgSpiceWrapper(dll_path)
                if self._ngspice.initialized:
                    self._logger.info("SpiceExecutor 初始化成功")
                else:
                    self._init_error = (
                        self._ngspice.fatal_error_message
                        or "ngspice 共享库未完成初始化"
                    )
                    self._logger.warning(
                        "SpiceExecutor 初始化失败: %s",
                        self._init_error,
                    )
            else:
                self._init_error = "无法获取 ngspice DLL 路径"
        except NgSpiceError as e:
            self._init_error = str(e)
            self._logger.warning(f"SpiceExecutor 初始化失败: {e}")
        except Exception as e:
            self._init_error = str(e)
            self._logger.exception(f"SpiceExecutor 初始化异常: {e}")

    # ============================================================
    # Public executor contract
    # ============================================================
    
    def get_name(self) -> str:
        """返回执行器名称"""
        return "spice"
    
    def get_supported_extensions(self) -> List[str]:
        """返回支持的文件扩展名列表"""
        return SUPPORTED_EXTENSIONS.copy()
    
    def can_handle(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS

    def _resolve_source_path(
        self,
        file_path: str,
    ) -> tuple[Optional[Path], Optional[str]]:
        path = Path(file_path).expanduser()
        if not path.exists():
            return None, f"文件不存在: {file_path}"
        if not path.is_file():
            return None, f"路径不是文件: {file_path}"
        if not self.can_handle(str(path)):
            return None, (
                "不支持的网表类型，支持: "
                + ", ".join(SUPPORTED_EXTENSIONS)
            )
        return path.resolve(), None

    @staticmethod
    def _validate_timeout(value: Any) -> float:
        try:
            timeout = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout must be a positive number") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        return timeout
    
    def execute(
        self,
        file_path: str,
        *,
        cancel_signal: Optional[object] = None,
    ) -> SimulationResult:
        """Execute one source-owned SPICE deck within one total deadline.

        Source resolution, closure snapshotting and policy validation happen
        before the native lock. Lock acquisition is deadline/cancellation
        aware; after acquisition the remaining budget covers the complete
        destroy/load/run/vector-read transaction.
        """
        started_at = time.monotonic()
        deadline = time.monotonic() + self._timeout_seconds
        if cancel_signal is not None and not all(
            callable(getattr(cancel_signal, method, None))
            for method in ("is_set", "wait")
        ):
            result = self._parameter_error(
                file_path,
                "unknown",
                "内部取消信号无效",
            )
        elif cancel_signal is not None and cancel_signal.is_set():
            result = self._cancelled_result(
                file_path,
                "unknown",
                raw_output="",
            )
        else:
            result = self._execute(
                file_path,
                cancel_signal=cancel_signal,
                deadline=deadline,
            )
        result.duration_seconds = time.monotonic() - started_at
        return result

    def _execute(
        self,
        file_path: str,
        *,
        cancel_signal: Optional[object],
        deadline: float,
    ) -> SimulationResult:
        """Build one immutable closure, then execute its single analysis."""
        analysis_type = "unknown"
        circuit_path, error_msg = self._resolve_source_path(file_path)
        if circuit_path is None:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.FILE_ACCESS,
                    severity=ErrorSeverity.HIGH,
                    message=error_msg or "文件校验失败",
                    file_path=file_path,
                ),
            )

        try:
            source_bytes = circuit_path.read_bytes()
        except OSError as exc:
            return create_error_result(
                executor=self.get_name(),
                file_path=str(circuit_path),
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.FILE_ACCESS,
                    severity=ErrorSeverity.HIGH,
                    message=f"网表读取失败: {exc}",
                    file_path=str(circuit_path),
                ),
            )

        try:
            source_closure = snapshot_spice_source_closure(
                circuit_path,
                main_bytes=source_bytes,
            )
        except SpiceSourceClosureError as exc:
            return create_error_result(
                executor=self.get_name(),
                file_path=str(circuit_path),
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.FILE_ACCESS,
                    severity=ErrorSeverity.HIGH,
                    message=f"无法建立完整 SPICE source closure: {exc}",
                    file_path=str(circuit_path),
                    recovery_suggestion=(
                        "请修正缺失、循环或无法解析的 include/lib 依赖"
                    ),
                ),
            )

        with source_closure:
            source_digest = source_closure.digest
            source_text = source_closure.main_text

            control_commands = source_closure.graph.control_commands
            if control_commands:
                details = "; ".join(
                    f"{source_id}:{line_number}: {command}"
                    for source_id, line_number, command in control_commands
                )
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    (
                        "不支持 ngspice .control/.endc 脚本；"
                        "每个任务只能执行主网表的一张顶层分析卡: "
                        + details
                    ),
                    source_digest=source_digest,
                )

            dependency_analyses = (
                source_closure.graph.dependency_analysis_commands
            )
            if dependency_analyses:
                details = "; ".join(
                    f"{source_id}:{line_number}: {command}"
                    for source_id, line_number, command in dependency_analyses
                )
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    (
                        "分析指令只允许出现在主网表，依赖文件包含分析卡: "
                        + details
                    ),
                    source_digest=source_digest,
                )

            analysis_commands = source_closure.graph.main_analysis_commands
            analysis_command = ""
            if len(analysis_commands) == 1:
                analysis_command = analysis_commands[0].statement
                analysis_type = analysis_commands[0].analysis_type

            unsupported_analysis_error = (
                self._unsupported_analysis_preflight_error(
                    source_closure.graph.active_views
                )
            )
            if unsupported_analysis_error:
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    unsupported_analysis_error,
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            runtime_options_error = self._runtime_options_preflight_error(
                source_closure.graph.active_views
            )
            if runtime_options_error:
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    runtime_options_error,
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            temperature_error = self._temperature_preflight_error(
                source_closure.graph.active_views
            )
            if temperature_error:
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    temperature_error,
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            if len(analysis_commands) != 1:
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    (
                        "主网表必须且只能包含一张顶层 .ac、.dc、.tran、"
                        f".noise 或 .op 分析卡；当前检测到 {len(analysis_commands)} 张"
                    ),
                    source_digest=source_digest,
                )

            netlist_lines = source_text.splitlines()
            if not any(is_spice_end_directive(line) for line in netlist_lines):
                return self._netlist_syntax_error(
                    str(circuit_path),
                    analysis_type,
                    "网表缺少必需的 .end 结束指令",
                    analysis_command,
                    source_digest,
                )
            if any("\x00" in line for line in netlist_lines):
                return self._netlist_syntax_error(
                    str(circuit_path),
                    analysis_type,
                    "网表包含不允许的 NUL 字符",
                    analysis_command,
                    source_digest,
                )

            preflight_error = self._analysis_preflight_error(
                analysis_type,
                analysis_command,
            )
            if preflight_error:
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    preflight_error,
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            reserved_node_error = self._reserved_node_preflight_error(
                source_closure.graph.active_views,
                analysis_type,
                analysis_command,
            )
            if reserved_node_error:
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    reserved_node_error,
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            measure_requests, measure_errors = (
                measure_authority.validate_source_views(
                    source_closure.graph.active_views,
                    analysis_commands[0],
                )
            )
            if measure_errors:
                details = "; ".join(error.message for error in measure_errors)
                return self._parameter_error(
                    str(circuit_path),
                    analysis_type,
                    f".measure 与唯一分析不一致: {details}",
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            if cancel_signal is not None and cancel_signal.is_set():
                return self._cancelled_result(
                    str(circuit_path),
                    analysis_type,
                    raw_output="",
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )
            if time.monotonic() >= deadline:
                return self._timeout_result(
                    str(circuit_path),
                    analysis_type,
                    "仿真在进入 ngspice 前已超过总超时预算",
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            if not self._ngspice or not self._ngspice.initialized:
                error_msg = self._init_error or "ngspice 未初始化"
                if self._ngspice and self._ngspice.fatal_error_message:
                    error_msg = self._ngspice.fatal_error_message
                return create_error_result(
                    executor=self.get_name(),
                    file_path=str(circuit_path),
                    analysis_type=analysis_type,
                    error=SimulationError(
                        type=SimulationErrorType.NGSPICE_CRASH,
                        severity=ErrorSeverity.CRITICAL,
                        message=error_msg,
                        recovery_suggestion="请检查 ngspice 安装和配置",
                    ),
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )

            wait_error = self._wait_for_native_slot(
                file_path=str(circuit_path),
                analysis_type=analysis_type,
                analysis_command=analysis_command,
                source_digest=source_digest,
                cancel_signal=cancel_signal,
                deadline=deadline,
            )
            if wait_error is not None:
                return wait_error

            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._timeout_result(
                        str(circuit_path),
                        analysis_type,
                        "仿真等待 ngspice 执行槽时已超过总超时预算",
                        source_digest=source_digest,
                        analysis_command=analysis_command,
                    )
                if cancel_signal is not None and cancel_signal.is_set():
                    return self._cancelled_result(
                        str(circuit_path),
                        analysis_type,
                        raw_output="",
                        source_digest=source_digest,
                        analysis_command=analysis_command,
                    )
                try:
                    result = self._run_simulation(
                        file_path=str(circuit_path),
                        source_text=source_text,
                        source_digest=source_digest,
                        runtime_input_path=source_closure.snapshot_root,
                        analysis_type=analysis_type,
                        analysis_command=analysis_command,
                        measure_requests=measure_requests,
                        cancel_signal=cancel_signal,
                        deadline=deadline,
                    )
                    return result
                except Exception as exc:
                    self._logger.exception("仿真执行异常: %s", exc)
                    return create_error_result(
                        executor=self.get_name(),
                        file_path=str(circuit_path),
                        analysis_type=analysis_type,
                        error=self._parse_ngspice_output(
                            str(exc),
                            str(circuit_path),
                        ),
                        source_digest=source_digest,
                        analysis_command=analysis_command,
                    )
            finally:
                _SPICE_EXECUTION_LOCK.release()

    # ============================================================
    # 公开辅助方法
    # ============================================================
    
    def is_available(self) -> bool:
        """
        检查执行器是否可用
        
        Returns:
            bool: ngspice 是否已正确配置且可用
        """
        return self._ngspice is not None and self._ngspice.initialized
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    @staticmethod
    def _detect_analysis_from_plot(plot_name: str) -> str:
        """
        从 ngspice plot 名称推断分析类型
        
        ngspice plot 命名规则：dc1, ac1, tran1, noise1, op1 等
        """
        if not plot_name:
            return ""
        name = str(plot_name).strip().casefold()
        match = re.fullmatch(r"(dc|ac|tran|noise|op)[1-9]\d*", name)
        return match.group(1) if match is not None else ""

    def _wait_for_native_slot(
        self,
        *,
        file_path: str,
        analysis_type: str,
        analysis_command: str,
        source_digest: str,
        cancel_signal: Optional[object],
        deadline: float,
    ) -> Optional[SimulationResult]:
        """Acquire the process-global ngspice slot without blind blocking."""

        while True:
            if cancel_signal is not None and cancel_signal.is_set():
                return self._cancelled_result(
                    file_path,
                    analysis_type,
                    raw_output="",
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._timeout_result(
                    file_path,
                    analysis_type,
                    "仿真等待进程级 ngspice 执行槽时超时",
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                )
            if _SPICE_EXECUTION_LOCK.acquire(timeout=min(0.05, remaining)):
                return None

    def _native_budget_error(
        self,
        *,
        file_path: str,
        analysis_type: str,
        analysis_command: str,
        source_digest: str,
        cancel_signal: Optional[object],
        deadline: float,
        stage: str,
    ) -> Optional[SimulationResult]:
        if cancel_signal is not None and cancel_signal.is_set():
            return self._cancelled_result(
                file_path,
                analysis_type,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        if time.monotonic() >= deadline:
            return self._timeout_result(
                file_path,
                analysis_type,
                f"仿真在{stage}阶段超过总超时预算",
                source_digest=source_digest,
                analysis_command=analysis_command,
                raw_output=self._collect_native_output(),
            )
        return None

    def _run_simulation(
        self,
        file_path: str,
        source_text: str,
        source_digest: str,
        runtime_input_path: Path,
        analysis_type: str,
        analysis_command: str,
        measure_requests: Tuple[MeasureRequest, ...],
        cancel_signal: Optional[object],
        deadline: float,
    ) -> SimulationResult:
        """执行仿真核心逻辑"""
        budget_error = self._native_budget_error(
            file_path=file_path,
            analysis_type=analysis_type,
            analysis_command=analysis_command,
            source_digest=source_digest,
            cancel_signal=cancel_signal,
            deadline=deadline,
            stage="进入 ngspice",
        )
        if budget_error is not None:
            return budget_error

        if self._ngspice.has_fatal_error:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.CRITICAL,
                    message=self._ngspice.fatal_error_message,
                    file_path=file_path,
                    recovery_suggestion=(
                        "ngspice 共享库已进入不可信状态，请重启应用"
                    ),
                ),
                source_digest=source_digest,
                analysis_command=analysis_command,
            )

        try:
            destroyed = self._ngspice.destroy(deadline=deadline)
        except NgSpiceTimeoutError as exc:
            return self._timeout_result(
                file_path,
                analysis_type,
                str(exc),
                source_digest=source_digest,
                analysis_command=analysis_command,
                raw_output=self._collect_native_output(),
            )
        if not destroyed:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.CRITICAL,
                    message="ngspice 无法清理上一个电路会话",
                    file_path=file_path,
                    recovery_suggestion="请重启应用后重试",
                ),
                source_digest=source_digest,
                analysis_command=analysis_command,
            )

        budget_error = self._native_budget_error(
            file_path=file_path,
            analysis_type=analysis_type,
            analysis_command=analysis_command,
            source_digest=source_digest,
            cancel_signal=cancel_signal,
            deadline=deadline,
            stage="清理上一原生会话",
        )
        if budget_error is not None:
            return budget_error

        self._ngspice.set_input_path(Path(runtime_input_path))
        modified_netlist = source_text

        budget_error = self._native_budget_error(
            file_path=file_path,
            analysis_type=analysis_type,
            analysis_command=analysis_command,
            source_digest=source_digest,
            cancel_signal=cancel_signal,
            deadline=deadline,
            stage="加载网表前",
        )
        if budget_error is not None:
            return budget_error

        # 加载网表
        netlist_lines = modified_netlist.splitlines()
        if not any(is_spice_end_directive(line) for line in netlist_lines):
            return self._netlist_syntax_error(
                file_path,
                analysis_type,
                "网表缺少必需的 .end 结束指令",
                analysis_command,
                source_digest,
            )
        if any("\x00" in line for line in netlist_lines):
            return self._netlist_syntax_error(
                file_path,
                analysis_type,
                "网表包含不允许的 NUL 字符",
                analysis_command,
                source_digest,
            )
        loaded = self._ngspice.load_netlist(netlist_lines)
        load_output = self._collect_native_output()
        if not loaded or self._has_native_failure_output(load_output):
            return self._native_error_result(
                file_path,
                analysis_type,
                load_output or "ngspice 网表加载失败",
                analysis_command,
                source_digest,
            )

        budget_error = self._native_budget_error(
            file_path=file_path,
            analysis_type=analysis_type,
            analysis_command=analysis_command,
            source_digest=source_digest,
            cancel_signal=cancel_signal,
            deadline=deadline,
            stage="加载网表",
        )
        if budget_error is not None:
            return budget_error

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._timeout_result(
                    file_path,
                    analysis_type,
                    "仿真在开始 native run 前超过总超时预算",
                    source_digest=source_digest,
                    analysis_command=analysis_command,
                    raw_output=load_output,
                )
            self._ngspice.run(
                timeout_seconds=remaining,
                cancel_signal=cancel_signal,
            )
        except NgSpiceCancelledError:
            return self._cancelled_result(
                file_path,
                analysis_type,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        except NgSpiceTimeoutError as exc:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.TIMEOUT,
                    severity=ErrorSeverity.HIGH,
                    message=str(exc),
                    file_path=file_path,
                    recovery_suggestion=(
                        "请缩短仿真规模，或增加执行器的总超时预算"
                    ),
                ),
                raw_output=self._collect_native_output(),
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        except NgSpiceCommandError as exc:
            output = (self._collect_native_output() + "\n" + str(exc)).strip()
            return self._native_error_result(
                file_path,
                analysis_type,
                output,
                analysis_command,
                source_digest,
                measure_requests=measure_requests,
            )

        budget_error = self._native_budget_error(
            file_path=file_path,
            analysis_type=analysis_type,
            analysis_command=analysis_command,
            source_digest=source_digest,
            cancel_signal=cancel_signal,
            deadline=deadline,
            stage="native run",
        )
        if budget_error is not None:
            return budget_error

        raw_output = self._collect_native_output()
        if self._has_native_failure_output(
            raw_output,
            analysis_type=analysis_type,
            measure_requests=measure_requests,
        ):
            return self._native_error_result(
                file_path,
                analysis_type,
                raw_output,
                analysis_command,
                source_digest,
                measure_requests=measure_requests,
            )

        # A source closure has exactly one physical analysis card. Native
        # output must therefore expose exactly one matching analysis plot;
        # noise is the sole structured exception (spectrum + totals pair).
        (
            target_plot,
            noise_totals_plot,
            discovered_types,
            conflicting_plots,
        ) = self._find_source_analysis_plot()
        if conflicting_plots or discovered_types != (analysis_type,):
            rendered_plots = ", ".join(conflicting_plots) or "none"
            rendered_types = ", ".join(discovered_types) or "none"
            malformed_noise_output = (
                analysis_type == "noise"
                and discovered_types == ("noise",)
            )
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=(
                        SimulationErrorType.OUTPUT_PARSE_ERROR
                        if malformed_noise_output
                        else SimulationErrorType.PARAMETER_INVALID
                    ),
                    severity=ErrorSeverity.HIGH,
                    message=(
                        (
                            "ngspice NOISE spectrum/totals plot 结构无效"
                            if malformed_noise_output
                            else (
                                f"唯一 .{analysis_type} 分析卡与实际 "
                                "ngspice plots 不一致"
                            )
                        )
                        + f"（types={rendered_types}, plots={rendered_plots}）"
                    ),
                    file_path=file_path,
                    recovery_suggestion=(
                        "请检查 ngspice 原始输出及 NOISE 结果向量"
                        if malformed_noise_output
                        else (
                            "删除产生额外 plot 的控制结构，"
                            "确保主网表只执行该分析"
                        )
                    ),
                ),
                raw_output=raw_output,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        if target_plot is None:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"ngspice 未生成唯一 {analysis_type} 分析 plot",
                    file_path=file_path,
                    recovery_suggestion="请检查分析指令及 ngspice 原始输出",
                ),
                raw_output=raw_output,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        actual_type = self._detect_analysis_from_plot(target_plot)
        if actual_type != analysis_type:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=(
                        f"ngspice plot {target_plot} 类型 {actual_type or 'unknown'} "
                        f"与 .{analysis_type} 分析卡不一致"
                    ),
                    file_path=file_path,
                ),
                raw_output=raw_output,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )

        try:
            sim_data = self._extract_simulation_data(
                analysis_type,
                analysis_command,
                target_plot,
                noise_totals_plot=noise_totals_plot,
                cancel_signal=cancel_signal,
                deadline=deadline,
            )
            sim_data.validate_for_analysis(
                analysis_type,
                analysis_command=analysis_command,
                success=True,
            )
        except NgSpiceCancelledError:
            return self._cancelled_result(
                file_path,
                analysis_type,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        except NgSpiceTimeoutError as exc:
            return self._timeout_result(
                file_path,
                analysis_type,
                str(exc),
                source_digest=source_digest,
                analysis_command=analysis_command,
                raw_output=raw_output,
            )
        except ValueError as exc:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"ngspice 结果结构无效: {exc}",
                    file_path=file_path,
                    recovery_suggestion="请检查 ngspice 原始输出与分析结果向量",
                ),
                raw_output=raw_output,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )
        if not self._simulation_data_has_payload(sim_data):
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"ngspice plot {target_plot} 不包含可用仿真向量",
                    file_path=file_path,
                    recovery_suggestion="请检查 .save 指令和分析参数",
                ),
                raw_output=raw_output,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )

        try:
            # Parse only closure-authorized measurements, then prove that the
            # complete success object satisfies the same public schema used by
            # persistence and readers.  Shape-only SimulationData validation
            # is insufficient: command-grid rules (for example AC LIN point
            # count and TRAN endpoints) live at the SimulationResult boundary.
            measurements = self._parse_measure_results(
                raw_output,
                analysis_type,
                measure_requests,
            )
            success_result = create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                data=sim_data,
                source_digest=source_digest,
                measurements=measurements,
                raw_output=raw_output,
                analysis_command=analysis_command,
            )
            # ``to_dict`` is the complete in-memory scientific contract: it
            # validates command-grid, signal, noise and measurement semantics.
            # The executor intentionally keeps an absolute request identity;
            # project-relative conversion and the subsequent strict from_dict
            # roundtrip belong exclusively to persistence.
            success_result.to_dict()
        except ValueError as exc:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    type=SimulationErrorType.OUTPUT_PARSE_ERROR,
                    severity=ErrorSeverity.HIGH,
                    message=f"ngspice 完整结果契约无效: {exc}",
                    file_path=file_path,
                    recovery_suggestion=(
                        "请检查 ngspice 实际坐标网格、信号和测量输出"
                    ),
                ),
                raw_output=raw_output,
                source_digest=source_digest,
                analysis_command=analysis_command,
            )

        budget_error = self._native_budget_error(
            file_path=file_path,
            analysis_type=analysis_type,
            analysis_command=analysis_command,
            source_digest=source_digest,
            cancel_signal=cancel_signal,
            deadline=deadline,
            stage="读取并组装结果",
        )
        if budget_error is not None:
            return budget_error

        return success_result

    def _find_source_analysis_plot(
        self,
    ) -> Tuple[
        Optional[str],
        Optional[str],
        Tuple[str, ...],
        Tuple[str, ...],
    ]:
        """Select one analysis type from the plots ngspice actually created.

        Static closure validation has already admitted one analysis card. Any
        additional runtime plot is an authority violation, except ngspice's
        documented noise spectrum/totals pair.
        """
        grouped: Dict[str, List[str]] = {}
        unknown_plots: List[str] = []
        for plot_name in self._ngspice.get_all_plots():
            if str(plot_name).strip().casefold() == "const":
                continue
            detected = self._detect_analysis_from_plot(plot_name)
            if detected:
                grouped.setdefault(detected, []).append(plot_name)
            else:
                unknown_plots.append(plot_name)
        analysis_types = tuple(sorted(grouped))
        if unknown_plots:
            conflicts = tuple(
                [
                    plot_name
                    for grouped_type in analysis_types
                    for plot_name in grouped[grouped_type]
                ]
                + unknown_plots
            )
            return None, None, analysis_types, conflicts
        if len(analysis_types) != 1:
            conflicts = tuple(
                plot_name
                for analysis_type in analysis_types
                for plot_name in grouped[analysis_type]
            )
            return None, None, analysis_types, conflicts
        analysis_type = analysis_types[0]
        matches = grouped[analysis_type]
        target = self._select_unique_plot(analysis_type, matches)
        totals_plot = None
        if analysis_type == "noise" and target is not None:
            totals = [
                name
                for name in matches
                if self._noise_plot_role(name) == "total"
            ]
            totals_plot = totals[0] if len(totals) == 1 else None
        return (
            target,
            totals_plot,
            analysis_types,
            () if target is not None else tuple(matches),
        )

    def _select_unique_plot(
        self,
        analysis_type: str,
        plot_names: List[str],
    ) -> Optional[str]:
        if analysis_type != "noise":
            return plot_names[0] if len(plot_names) == 1 else None
        roles = {
            plot_name: self._noise_plot_role(plot_name)
            for plot_name in plot_names
        }
        spectrum = [name for name, role in roles.items() if role == "spectrum"]
        totals = [name for name, role in roles.items() if role == "total"]
        if (
            len(spectrum) == 1
            and len(totals) in {0, 1}
            and len(spectrum) + len(totals) == len(plot_names)
        ):
            return spectrum[0]
        return None

    @staticmethod
    def _analysis_preflight_error(
        analysis_type: str,
        analysis_command: str,
    ) -> Optional[str]:
        """Apply the single shared directive contract before native entry."""

        try:
            validate_analysis_command(
                analysis_type=analysis_type,
                analysis_command=analysis_command,
                required=True,
            )
        except ValueError as exc:
            return str(exc)
        return None

    @staticmethod
    def _unsupported_analysis_preflight_error(
        source_views: Sequence[SpiceSourceView],
    ) -> Optional[str]:
        locations = SpiceExecutor._top_level_directive_locations(
            source_views,
            _UNSUPPORTED_ANALYSIS_DIRECTIVES,
        )
        if not locations:
            return None
        return (
            "当前结果模型不支持这些顶层 ngspice 分析/后处理卡，"
            "不能执行后静默丢弃: "
            + "; ".join(locations)
        )

    @staticmethod
    def _runtime_options_preflight_error(
        source_views: Sequence[SpiceSourceView],
    ) -> Optional[str]:
        locations = SpiceExecutor._top_level_directive_locations(
            source_views,
            _UNSUPPORTED_RUNTIME_DIRECTIVES,
        )
        if not locations:
            return None
        return (
            "不支持顶层 .option/.options：ngspice 会静默忽略或替换"
            "部分运行参数，无法证明执行语义与源网表一致: "
            + "; ".join(locations)
        )

    @staticmethod
    def _top_level_directive_locations(
        source_views: Sequence[SpiceSourceView],
        directives: Sequence[str],
    ) -> Tuple[str, ...]:
        wanted = {str(directive).casefold() for directive in directives}
        locations: List[str] = []
        for source_view in source_views:
            subcircuit_depth = 0
            for source_line in source_view.lines:
                if source_view.is_main_deck and source_line.line_number == 1:
                    continue
                tokens = tokenize_spice_directive(source_line.text)
                if not tokens:
                    continue
                command = tokens[0].casefold()
                if command == ".subckt":
                    subcircuit_depth += 1
                    continue
                if command == ".ends":
                    subcircuit_depth = max(0, subcircuit_depth - 1)
                    continue
                if (
                    subcircuit_depth == 0
                    and command in wanted
                ):
                    locations.append(
                        f"{source_view.source_id}:{source_line.line_number}: "
                        f"{source_line.text.strip()}"
                    )
        return tuple(locations)

    @staticmethod
    def _temperature_preflight_error(
        source_views: Sequence[SpiceSourceView],
    ) -> Optional[str]:
        """Admit at most one unambiguous top-level temperature expression.

        ngspice 42 accepts ``.temp 25 50`` syntactically but warns that it
        could not set that value and silently runs at the default 27 C.  This
        product has no multi-temperature result dimension, so source policy
        must reject empty, repeated, multi-valued or non-finite literal cards.
        A one-token expression such as ``{t}`` remains source-owned and is
        evaluated by ngspice; the exact fallback diagnostic gate catches a
        failed evaluation instead of duplicating ngspice's parameter engine.
        """

        cards: List[Tuple[str, int, str, Tuple[str, ...]]] = []
        for source_view in source_views:
            subcircuit_depth = 0
            index = 0
            lines = source_view.lines
            while index < len(lines):
                source_line = lines[index]
                index += 1
                if source_view.is_main_deck and source_line.line_number == 1:
                    continue
                tokens = tokenize_spice_directive(source_line.text)
                if not tokens:
                    continue
                command = tokens[0].casefold()
                if command == ".subckt":
                    subcircuit_depth += 1
                    continue
                if command == ".ends":
                    subcircuit_depth = max(0, subcircuit_depth - 1)
                    continue
                if subcircuit_depth != 0 or command != ".temp":
                    continue

                statement = source_line.text.strip()
                while (
                    index < len(lines)
                    and lines[index].text.lstrip().startswith("+")
                ):
                    continuation = lines[index].text.lstrip()[1:].strip()
                    statement = f"{statement} {continuation}".strip()
                    index += 1
                cards.append(
                    (
                        source_view.source_id,
                        source_line.line_number,
                        statement,
                        tokenize_spice_directive(statement),
                    )
                )

        if not cards:
            return None
        if len(cards) != 1:
            locations = "; ".join(
                f"{source_id}:{line_number}: {statement}"
                for source_id, line_number, statement, _tokens in cards
            )
            return (
                "每次仿真最多允许一张顶层 .temp 卡，"
                f"当前检测到 {len(cards)} 张: {locations}"
            )

        source_id, line_number, statement, tokens = cards[0]
        if len(tokens) != 2:
            return (
                "顶层 .temp 必须且只能包含一个温度值或参数表达式: "
                f"{source_id}:{line_number}: {statement}"
            )
        value = parse_spice_number(tokens[1])
        if value is not None and not math.isfinite(value):
            return (
                "顶层 .temp 的字面温度值必须是有限数: "
                f"{source_id}:{line_number}: {statement}"
            )
        return None

    @classmethod
    def _reserved_node_preflight_error(
        cls,
        source_views: Sequence[SpiceSourceView],
        analysis_type: str,
        analysis_command: str,
    ) -> Optional[str]:
        """Reject node names that ngspice replaces with native result vectors.

        A plain node named ``time`` is legal in an OP/DC/AC deck and must stay
        a voltage signal.  It is not recoverable in a transient deck, however,
        because ngspice uses that exact vector name for the independent scale.
        The same rule applies to ``frequency`` in AC/noise and to ngspice's
        source-specific DC scale names.  Detect the collision from the already
        collected active source views before native execution, rather than
        silently returning a result with the user's node missing.
        """

        reserved = cls._reserved_axis_node_names(
            analysis_type,
            analysis_command,
        )
        nodes = cls._collect_top_level_node_locations(source_views)
        conflicts = sorted(reserved.intersection(nodes))
        branch_conflicts = sorted(
            node for node in nodes if node.endswith("#branch")
        )
        if not conflicts and not branch_conflicts:
            return None

        details = []
        for node in (*conflicts, *branch_conflicts):
            locations = ", ".join(nodes[node])
            details.append(f"{node} ({locations})")
        return (
            "顶层节点名与 ngspice 保留的结果向量冲突，原节点数据会被覆盖: "
            + "; ".join(details)
            + "；请重命名这些节点"
        )

    @staticmethod
    def _reserved_axis_node_names(
        analysis_type: str,
        analysis_command: str,
    ) -> set[str]:
        normalized_type = str(analysis_type or "").strip().casefold()
        if normalized_type == "tran":
            return {"time"}
        if normalized_type in {"ac", "noise"}:
            return {"frequency"}
        if normalized_type != "dc":
            return set()

        tokens = tokenize_spice_directive(analysis_command)
        if len(tokens) < 2 or tokens[0].casefold() != ".dc":
            return set()
        source = tokens[1].strip().casefold()
        if source == "temp":
            return {"temp-sweep"}
        if source.startswith("v"):
            return {"v-sweep"}
        if source.startswith("i"):
            return {"i-sweep"}
        if source.startswith("r"):
            return {"res-sweep"}
        return set()

    @classmethod
    def _collect_top_level_node_locations(
        cls,
        source_views: Sequence[SpiceSourceView],
    ) -> Dict[str, List[str]]:
        """Collect electrical nodes outside every ``.subckt`` definition.

        This is deliberately a small execution-safety scanner, not another
        schematic parser.  It only identifies the fixed node positions of
        native SPICE instance cards and the variable port list of X cards.
        Unknown cards are left to ngspice and cannot create a false reserved-
        name rejection.
        """

        locations: Dict[str, List[str]] = {}
        for source_view in source_views:
            subcircuit_depth = 0
            for source_line in source_view.lines:
                if source_view.is_main_deck and source_line.line_number == 1:
                    continue
                tokens = tokenize_spice_directive(source_line.text)
                if not tokens:
                    continue
                command = tokens[0].casefold()
                if command == ".subckt":
                    subcircuit_depth += 1
                    continue
                if command == ".ends":
                    subcircuit_depth = max(0, subcircuit_depth - 1)
                    continue
                if (
                    subcircuit_depth
                    or command.startswith(".")
                    or command.startswith("+")
                    or command.startswith("*")
                ):
                    continue

                for node in cls._component_node_tokens(tokens):
                    normalized = str(node or "").strip().casefold()
                    if not normalized or normalized in {"0", "gnd"}:
                        continue
                    locations.setdefault(normalized, []).append(
                        f"{source_view.source_id}:{source_line.line_number}"
                    )
        return locations

    @staticmethod
    def _component_node_tokens(tokens: Tuple[str, ...]) -> Tuple[str, ...]:
        """Return only structurally unambiguous node operands of one card."""

        if len(tokens) < 2:
            return ()
        prefix = tokens[0][:1].upper()
        fixed_counts = {
            "R": 2,
            "C": 2,
            "L": 2,
            "D": 2,
            "V": 2,
            "I": 2,
            "J": 3,
            "Z": 3,
            "M": 4,
            "U": 3,
            "B": 2,
            "F": 2,
            "H": 2,
            "S": 4,
            "W": 2,
            "T": 4,
            "O": 4,
            "Y": 4,
        }
        if prefix in fixed_counts:
            count = fixed_counts[prefix]
            return tuple(tokens[1 : 1 + count])
        if prefix == "K":
            return ()
        if prefix == "Q":
            if len(tokens) <= 5:
                return tuple(tokens[1:4])
            following = tokens[5].strip().casefold()
            three_terminal = (
                "=" in following
                or parse_spice_number(following) is not None
                or following in {"area", "off", "ic", "temp", "dtemp", "m"}
            )
            return tuple(tokens[1 : 4 if three_terminal else 5])
        if prefix in {"E", "G"}:
            control_form = (
                tokens[3].strip().casefold().split("=", 1)[0]
                if len(tokens) > 3
                else ""
            )
            behavioral = control_form in {
                "value",
                "vol",
                "cur",
                "table",
                "laplace",
            } or control_form.startswith("poly(")
            return tuple(tokens[1 : 3 if behavioral else 5])
        if prefix == "X" and len(tokens) >= 3:
            model_index = len(tokens) - 1
            for index in range(2, len(tokens)):
                candidate = tokens[index].strip().casefold()
                if (
                    candidate == "params:"
                    or candidate.startswith("params:")
                    or "=" in candidate
                ):
                    model_index = index - 1
                    break
            return tuple(tokens[1:model_index])
        return ()

    def _noise_plot_role(self, plot_name: str) -> str:
        vector_names = {
            name.rsplit(".", 1)[-1].lower()
            for name in self._ngspice.get_all_vectors(plot_name)
        }
        if (
            "frequency" in vector_names
            and {"inoise_spectrum", "onoise_spectrum"} <= vector_names
        ):
            return "spectrum"
        if (
            "frequency" not in vector_names
            and {"inoise_total", "onoise_total"} <= vector_names
        ):
            return "total"
        return ""

    def _collect_native_output(self) -> str:
        output = self._ngspice.get_stdout().strip()
        if self._ngspice.fatal_error_message:
            output = (
                output + "\n" + self._ngspice.fatal_error_message
            ).strip()
        return output

    @staticmethod
    def _has_native_failure_output(
        output: str,
        *,
        analysis_type: str = "",
        measure_requests: Sequence[MeasureRequest] = (),
    ) -> bool:
        """Recognize terminal diagnostics, not ordinary stderr warnings.

        ``ngSpice_Circ`` and ``ngSpice_Command('run')`` return zero even for
        many parser/simulation failures. The textual callback is therefore a
        required part of the success contract.
        """

        diagnostic_output = SpiceExecutor._native_diagnostic_output(
            output,
            analysis_type=analysis_type,
            measure_requests=measure_requests,
        )
        patterns = (
            r"(?im)^\s*stderr\s+error(?:\s|:)",
            r"(?im)^\s*stderr\s+doanalyses:\s*(?:tran|dc):\s*"
            r"timestep too small\b",
            r"(?im)^\s*stderr\s+run simulation\(s\) aborted\b",
            r"(?im)^\s*(?:stderr|stdout)\s+"
            r"(?:dc|transient) solution failed(?:\s|:|-|$)",
            r"(?im)^\s*stderr\s+simulation interrupted(?:\s|:|-|$)",
            r"(?im)^\s*(?:stderr|stdout)\s+circuit not parsed(?:\s|[.:]|$)",
            r"(?im)^\s*stderr\s+fatal error(?:\s|:)",
            r"(?im)^\s*stderr\s+segmentation fault(?:\s|:|$)",
            r"(?im)^\s*stderr\s+access violation(?:\s|:|$)",
            r"(?im)^\s*stderr\s+cannot recover(?:\s|:|$)",
            r"(?im)^\s*stderr\s+.*\bawaits to be detached\b",
        )
        terminal_failure = any(
            re.search(pattern, diagnostic_output, re.IGNORECASE)
            for pattern in patterns
        )
        return terminal_failure or SpiceExecutor._has_silent_native_fallback(
            diagnostic_output
        )

    @staticmethod
    def _has_silent_native_fallback(diagnostic_output: str) -> bool:
        return any(
            re.search(pattern, diagnostic_output)
            for pattern in _NATIVE_SILENT_FALLBACK_PATTERNS
        )

    @staticmethod
    def _native_diagnostic_output(
        output: str,
        *,
        analysis_type: str = "",
        measure_requests: Sequence[MeasureRequest] = (),
    ) -> str:
        """Remove callback records that are source content, not diagnostics.

        ngspice echoes the first deck line as ``stdout Circuit: <title>``.
        Circuit titles are arbitrary user text and must never influence either
        the terminal-failure gate or subsequent error classification.
        Keeping the callback channel prefix on every remaining line lets both
        consumers use the same channel-aware diagnostic stream.
        """

        return "\n".join(
            rendered
            for _channel, _payload, rendered in (
                SpiceExecutor._native_diagnostic_records(
                    output,
                    analysis_type=analysis_type,
                    measure_requests=measure_requests,
                )
            )
        )

    @staticmethod
    def _native_diagnostic_records(
        output: str,
        *,
        analysis_type: str = "",
        measure_requests: Sequence[MeasureRequest] = (),
    ) -> Tuple[Tuple[str, str, str], ...]:
        """Parse callback lines and remove only paired measure-local errors.

        ngspice reports a failed ``.measure`` lookup as ``stderr Error:`` even
        after the requested circuit analysis and plot completed successfully.
        Such an error is local to the measurement only when it occurs inside
        the authoritative measurement section and is immediately paired with
        an authorized ``.measure ... failed!`` record.  Every unpaired,
        cross-analysis or unknown-name ``stderr Error`` remains terminal.
        """

        records = []
        for raw_line in str(output or "").splitlines():
            stripped = raw_line.strip()
            match = re.match(r"(?i)^(stdout|stderr)\s*(.*)$", stripped)
            if match is None:
                channel = "internal"
                payload = stripped
                rendered = raw_line
            else:
                channel = match.group(1).casefold()
                payload = match.group(2).strip()
                rendered = raw_line
            if channel == "stdout" and re.match(
                r"(?i)^circuit\s*:",
                payload,
            ):
                continue
            records.append((channel, payload, rendered))
        normalized_analysis = str(analysis_type or "").strip().lstrip(".").casefold()
        aliases = {"transient": "tran", "operating point": "op"}
        normalized_analysis = aliases.get(
            normalized_analysis,
            normalized_analysis,
        )
        authorized_names = {
            request.name.casefold()
            for request in measure_requests
            if request.analysis_type.casefold() == normalized_analysis
        }
        if not normalized_analysis or not authorized_names:
            return tuple(records)

        section_header = re.compile(
            r"^Measurements for (?P<analysis>.+?) Analysis$",
            re.IGNORECASE,
        )
        failed_measure = re.compile(
            r"^\.meas(?:ure)?\s+(?P<analysis>\S+)\s+"
            r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b.*\bfailed!\s*$",
            re.IGNORECASE,
        )
        in_authoritative_section = False
        pending_error_indexes: List[int] = []
        suppressed_indexes = set()
        for index, (channel, payload, _rendered) in enumerate(records):
            header = section_header.fullmatch(payload)
            if header is not None:
                section_analysis = header.group("analysis").strip().casefold()
                section_analysis = aliases.get(section_analysis, section_analysis)
                in_authoritative_section = section_analysis == normalized_analysis
                pending_error_indexes.clear()
                continue
            if not in_authoritative_section:
                pending_error_indexes.clear()
                continue
            if channel == "stderr" and re.match(
                r"^error(?:\s|:)",
                payload,
                re.IGNORECASE,
            ):
                pending_error_indexes.append(index)
                continue
            failed = failed_measure.fullmatch(payload)
            if failed is not None:
                failed_analysis = failed.group("analysis").lstrip(".").casefold()
                failed_analysis = aliases.get(failed_analysis, failed_analysis)
                if (
                    failed_analysis == normalized_analysis
                    and failed.group("name").casefold() in authorized_names
                ):
                    suppressed_indexes.update(pending_error_indexes)
                pending_error_indexes.clear()
                continue
            if payload:
                pending_error_indexes.clear()

        return tuple(
            record
            for index, record in enumerate(records)
            if index not in suppressed_indexes
        )

    def _native_error_result(
        self,
        file_path: str,
        analysis_type: str,
        output: str,
        analysis_command: str,
        source_digest: str,
        *,
        measure_requests: Sequence[MeasureRequest] = (),
    ) -> SimulationResult:
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            error=self._parse_ngspice_output(
                output,
                file_path,
                analysis_type=analysis_type,
                measure_requests=measure_requests,
            ),
            raw_output=output,
            source_digest=source_digest,
            analysis_command=analysis_command,
        )

    def _netlist_syntax_error(
        self,
        file_path: str,
        analysis_type: str,
        message: str,
        analysis_command: str,
        source_digest: str,
    ) -> SimulationResult:
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            error=SimulationError(
                type=SimulationErrorType.SYNTAX_ERROR,
                severity=ErrorSeverity.HIGH,
                message=message,
                file_path=file_path,
                recovery_suggestion="请修正网表结构后重试",
            ),
            source_digest=source_digest,
            analysis_command=analysis_command,
        )

    def _parameter_error(
        self,
        file_path: str,
        analysis_type: str,
        message: str,
        *,
        analysis_command: str = "",
        source_digest: Optional[str] = None,
    ) -> SimulationResult:
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            error=SimulationError(
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=message,
                file_path=file_path,
                recovery_suggestion="请修正主网表的唯一分析契约后重试",
            ),
            source_digest=source_digest,
            analysis_command=analysis_command,
        )

    def _cancelled_result(
        self,
        file_path: str,
        analysis_type: str,
        *,
        raw_output: Optional[str] = None,
        source_digest: Optional[str] = None,
        analysis_command: str = "",
    ) -> SimulationResult:
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            error=SimulationError(
                type=SimulationErrorType.CANCELLED,
                severity=ErrorSeverity.LOW,
                message="仿真已取消",
                file_path=file_path,
            ),
            raw_output=(
                self._collect_native_output()
                if raw_output is None
                else raw_output
            ),
            source_digest=source_digest,
            analysis_command=analysis_command,
        )

    def _timeout_result(
        self,
        file_path: str,
        analysis_type: str,
        message: str,
        *,
        source_digest: Optional[str] = None,
        analysis_command: str = "",
        raw_output: str = "",
    ) -> SimulationResult:
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            error=SimulationError(
                type=SimulationErrorType.TIMEOUT,
                severity=ErrorSeverity.HIGH,
                message=message,
                file_path=file_path,
                recovery_suggestion=(
                    "请缩短仿真规模，或在构造执行器时增加总超时预算"
                ),
            ),
            source_digest=source_digest,
            analysis_command=analysis_command,
            raw_output=raw_output,
        )

    @staticmethod
    def _simulation_data_has_payload(data: SimulationData) -> bool:
        return any(
            value is not None and np.asarray(value).size > 0
            for value in (data.frequency, data.time, data.sweep)
        ) or any(np.asarray(value).size > 0 for value in data.signals.values())

    @staticmethod
    def _ensure_execution_budget(
        cancel_signal: Optional[object],
        deadline: float,
    ) -> None:
        if cancel_signal is not None and cancel_signal.is_set():
            raise NgSpiceCancelledError("仿真已取消")
        if time.monotonic() >= deadline:
            raise NgSpiceTimeoutError("读取 ngspice 结果时超过总超时预算")

    def _extract_simulation_data(
        self,
        analysis_type: str,
        analysis_command: str,
        plot_name: str,
        *,
        noise_totals_plot: Optional[str],
        cancel_signal: Optional[object],
        deadline: float,
    ) -> SimulationData:
        """
        从 ngspice 提取仿真数据

        根据 analysis_type 与 ngspice 声明的 scale 决定独立变量：
        - ac/noise: 仅提取 frequency scale
        - tran: 仅提取 time scale
        - dc:   提取 ngspice callback 标记的独立 scale 向量
        - op:   没有独立轴

        ngspice 会把名为 ``time``/``frequency`` 的普通节点标成对应的
        特殊 vector type，即使当前分析根本不用该轴。只有分析角色与
        callback identity 同时允许的向量才是轴，其余特殊类型仍是节点
        电压，避免静默丢失合法信号。
        """
        frequency = None
        time_data = None
        sweep_data = None
        signals = {}
        signal_types = {}
        normalized_analysis = str(analysis_type or "").strip().casefold()
        self._ensure_execution_budget(cancel_signal, deadline)
        callback_scale_name = (
            self._ngspice.get_plot_scale_name(plot_name)
            if normalized_analysis in {"ac", "dc", "tran", "noise"}
            else None
        )

        # 获取所有向量
        vectors = self._ngspice.get_all_vectors(plot_name)
        self._logger.debug(
            "可用向量: %s (analysis_type=%s)",
            vectors,
            analysis_type,
        )

        for vec_name in vectors:
            self._ensure_execution_budget(cancel_signal, deadline)
            vec_info = self._ngspice.get_vector_info(
                vec_name,
                plot_name=plot_name,
            )
            if not vec_info:
                continue

            axis_role = self._analysis_axis_role(
                normalized_analysis,
                vec_name,
                callback_scale_name=callback_scale_name,
            )
            if axis_role:
                axis_data = None
                if vec_info.data is not None and len(vec_info.data) > 0:
                    axis_data = vec_info.data
                elif vec_info.cdata is not None and len(vec_info.cdata) > 0:
                    axis_data = np.real(vec_info.cdata)
                if axis_role == "frequency":
                    frequency = axis_data
                elif axis_role == "time":
                    time_data = axis_data
                else:
                    sweep_data = axis_data
                continue

            signal_vector_type = vec_info.type
            if signal_vector_type in {
                VectorType.SV_TIME,
                VectorType.SV_FREQUENCY,
            }:
                signal_vector_type = (
                    VectorType.SV_CURRENT
                    if "#branch" in vec_name.casefold()
                    else VectorType.SV_VOLTAGE
                )

            # 标准化信号名称（ngspice 返回小写，统一转为大写 V/I 开头）
            normalized_name = normalize_simulation_signal_name(
                vec_name,
                signal_vector_type,
            )
            
            # 确定信号类型标签
            type_label = resolve_vector_signal_type(
                vec_name,
                signal_vector_type,
                analysis_type=analysis_type,
                analysis_command=analysis_command,
            )

            if vec_info.cdata is not None and len(vec_info.cdata) > 0:
                signals[normalized_name] = vec_info.cdata
                signal_types[normalized_name] = type_label
            elif vec_info.data is not None and len(vec_info.data) > 0:
                signals[normalized_name] = vec_info.data
                signal_types[normalized_name] = type_label

        self._ensure_execution_budget(cancel_signal, deadline)
        noise_totals = None
        if normalized_analysis == "noise":
            if noise_totals_plot is not None:
                noise_totals = self._extract_noise_totals(
                    noise_totals_plot,
                    cancel_signal=cancel_signal,
                    deadline=deadline,
                )
            else:
                frequency_count = (
                    int(np.asarray(frequency).size)
                    if frequency is not None
                    else 0
                )
                if frequency_count != 1:
                    raise ValueError(
                        "NOISE 分析缺少唯一 totals plot；只有单频点分析允许无积分总量"
                    )
        return SimulationData(
            frequency=frequency,
            time=time_data,
            sweep=sweep_data,
            signals=signals,
            signal_types=signal_types,
            noise_totals=noise_totals,
        )

    def _extract_noise_totals(
        self,
        plot_name: str,
        *,
        cancel_signal: Optional[object],
        deadline: float,
    ) -> NoiseTotals:
        """Read ngspice's two integrated RMS totals as strict scalars."""

        self._ensure_execution_budget(cancel_signal, deadline)
        names_by_identity: Dict[str, List[str]] = {}
        for vector_name in self._ngspice.get_all_vectors(plot_name):
            identity = vector_name.rsplit(".", 1)[-1].casefold()
            if identity in {"onoise_total", "inoise_total"}:
                names_by_identity.setdefault(identity, []).append(vector_name)
        for identity in ("onoise_total", "inoise_total"):
            matches = names_by_identity.get(identity, [])
            if len(matches) != 1:
                raise ValueError(
                    f"NOISE totals plot 必须恰有一个 {identity}，实际 {len(matches)} 个"
                )

        def read_scalar(identity: str) -> float:
            self._ensure_execution_budget(cancel_signal, deadline)
            vector_name = names_by_identity[identity][0]
            info = self._ngspice.get_vector_info(
                vector_name,
                plot_name=plot_name,
            )
            if info is None:
                raise ValueError(f"无法读取 NOISE total 向量 {identity}")
            if info.data is not None and np.asarray(info.data).size:
                values = np.asarray(info.data)
            elif info.cdata is not None and np.asarray(info.cdata).size:
                complex_values = np.asarray(info.cdata)
                if np.any(np.imag(complex_values) != 0):
                    raise ValueError(f"NOISE total {identity} 不能是复数")
                values = np.real(complex_values)
            else:
                raise ValueError(f"NOISE total {identity} 没有数值")
            if values.ndim != 1 or values.size != 1:
                raise ValueError(
                    f"NOISE total {identity} 必须是单标量，实际 shape={values.shape}"
                )
            value = float(values[0])
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"NOISE total {identity} 必须是有限非负数"
                )
            return value

        return NoiseTotals(
            output_rms=read_scalar("onoise_total"),
            input_referred_rms=read_scalar("inoise_total"),
        )

    @classmethod
    def _analysis_axis_role(
        cls,
        analysis_type: str,
        vector_name: str,
        *,
        callback_scale_name: Optional[str],
    ) -> str:
        """Return the one axis role authorized by the active analysis."""

        normalized_analysis = str(analysis_type or "").strip().casefold()
        if normalized_analysis == "op":
            return ""
        # ngspice returns hierarchical node vectors such as ``x1.time`` and
        # ``x1.frequency`` alongside the unqualified native scales ``time``
        # and ``frequency``.  Axis identity is therefore an exact native
        # vector-name match, never a basename/suffix match: collapsing the
        # hierarchy would silently discard a legitimate subcircuit voltage.
        vector_identity = str(vector_name or "").strip().casefold()
        declared = str(callback_scale_name or "").strip().casefold()
        if normalized_analysis == "dc":
            return (
                "sweep"
                if cls._is_dc_scale_vector(
                    vector_name,
                    callback_scale_name=callback_scale_name,
                )
                else ""
            )
        if normalized_analysis == "tran":
            is_scale = (
                vector_identity == declared
                if declared
                else vector_identity == "time"
            )
            return "time" if is_scale else ""
        if normalized_analysis in {"ac", "noise"}:
            is_scale = (
                vector_identity == declared
                if declared
                else vector_identity == "frequency"
            )
            return "frequency" if is_scale else ""
        return ""

    @staticmethod
    def _is_dc_scale_vector(
        vector_name: str,
        *,
        callback_scale_name: Optional[str],
    ) -> bool:
        vector_identity = str(vector_name or "").strip().casefold()
        if callback_scale_name:
            declared = str(callback_scale_name).strip().casefold()
            return vector_identity == declared
        # ngspice's shared callback is authoritative. This exact-name fallback
        # covers official DC scales in libraries that omit callback metadata;
        # it deliberately does not use substring matching, so ordinary nodes
        # named ``sweep`` or ``sweepout`` remain signals.
        return vector_identity in {
            "v-sweep",
            "i-sweep",
            "temp-sweep",
            "res-sweep",
        }

    def _parse_measure_results(
        self,
        raw_output: str,
        analysis_type: str,
        requests: Tuple[MeasureRequest, ...],
    ) -> list:
        """Parse exactly the closure-authorized measurement result set."""

        from domain.simulation.measure.measure_parser import measure_parser

        request_by_name = {
            request.name.casefold(): request for request in requests
        }
        results = measure_parser.parse_measure_output(
            raw_output,
            analysis_type=analysis_type,
            expected_names=[request.name for request in requests],
        )
        for result in results:
            request = request_by_name[result.name.casefold()]
            result.statement = request.statement

        if results:
            self._logger.info("解析到 %d 个 .measure 结果", len(results))
        return results
    
    def _parse_ngspice_output(
        self,
        output: str,
        file_path: str,
        *,
        analysis_type: str = "",
        measure_requests: Sequence[MeasureRequest] = (),
    ) -> SimulationError:
        """解析 ngspice 输出，提取错误信息"""
        records = self._native_diagnostic_records(
            output,
            analysis_type=analysis_type,
            measure_requests=measure_requests,
        )
        output = "\n".join(rendered for _, _, rendered in records)
        error_output = "\n".join(
            rendered
            for channel, _payload, rendered in records
            if channel in {"stderr", "internal"}
        )
        diagnostic_lines = tuple(
            payload.casefold()
            for _channel, payload, _rendered in records
            if payload
        )
        terminal_error_lines = tuple(
            payload.casefold()
            for channel, payload, _rendered in records
            if channel in {"stderr", "internal"}
            and payload
            and not re.match(r"^warning(?:\s|:)", payload, re.IGNORECASE)
        )

        if self._has_silent_native_fallback(error_output):
            return SimulationError(
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=(
                    "ngspice 拒绝或替换了源网表参数，已阻止静默降级: "
                    f"{self._extract_error_message(error_output)}"
                ),
                file_path=file_path,
                recovery_suggestion=(
                    "请删除不受支持的模型/选项参数，或改用当前 ngspice "
                    "明确支持的温度、积分方法和模型级别"
                ),
            )

        if any(
            re.search(
                r"(?:^|[:\s])(?:access violation|segmentation fault)"
                r"(?:\s|:|$)",
                line,
            )
            for line in terminal_error_lines
        ):
            return SimulationError(
                type=SimulationErrorType.NGSPICE_CRASH,
                severity=ErrorSeverity.CRITICAL,
                message=f"ngspice 原生命令崩溃: {self._extract_error_message(output)}",
                file_path=file_path,
                recovery_suggestion=(
                    "当前 DLL 单例已不可再用，请重启应用，并优先检查"
                    "触发崩溃的网表与原始日志"
                ),
            )

        if any(
            "library file" in line and "not found" in line
            for line in terminal_error_lines
        ):
            missing_files = self._extract_missing_library_files(output)
            return SimulationError(
                type=SimulationErrorType.FILE_ACCESS,
                severity=ErrorSeverity.HIGH,
                message=f"模型库文件不存在: {', '.join(missing_files) if missing_files else '未知路径'}",
                file_path=file_path,
                recovery_suggestion=(
                    "请检查 .lib/.include 路径，并在网表中显式引用真实模型库"
                ),
            )

        if any(
            "unknown subckt" in line
            or ("subckt" in line and "not found" in line)
            for line in terminal_error_lines
        ):
            missing_subckts = self._extract_missing_subckts(output)
            return SimulationError(
                type=SimulationErrorType.MODEL_MISSING,
                severity=ErrorSeverity.HIGH,
                message=f"缺少子电路定义: {', '.join(missing_subckts) if missing_subckts else '未知'}",
                file_path=file_path,
                recovery_suggestion="请添加缺失的 .SUBCKT 定义或 .include/.lib 子电路文件",
            )

        if any(
            "undefined parameter" in line or "cannot compute substitute" in line
            for line in terminal_error_lines
        ):
            line_num = self._extract_line_number(output)
            return SimulationError(
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=f"模型或参数表达式不兼容: {self._extract_error_message(output)}",
                file_path=file_path,
                line_number=line_num,
                recovery_suggestion="请检查模型参数是否被当前 ngspice 版本支持，或移除不兼容的厂商/额定值元数据",
            )

        # 模型缺失
        if any(
            "model" in line and ("not found" in line or "unknown" in line)
            for line in terminal_error_lines
        ):
            missing_models = self._extract_missing_models(output)
            return SimulationError(
                type=SimulationErrorType.MODEL_MISSING,
                severity=ErrorSeverity.HIGH,
                message=f"缺少模型定义: {', '.join(missing_models) if missing_models else '未知'}",
                file_path=file_path,
                recovery_suggestion="请添加缺失的 .model 语句或 .include 模型文件",
            )

        # 语法错误
        if any(
            "syntax" in line
            or "parse error" in line
            or "unimplemented dot command" in line
            or re.search(r"error\s+on\s+line\s+\d+", line)
            for line in terminal_error_lines
        ):
            line_num = self._extract_line_number(output)
            return SimulationError(
                type=SimulationErrorType.SYNTAX_ERROR,
                severity=ErrorSeverity.HIGH,
                message=f"网表语法错误: {self._extract_error_message(output)}",
                file_path=file_path,
                line_number=line_num,
                recovery_suggestion="请检查网表语法，确保所有元件和节点名称正确",
            )

        if any("awaits to be detached" in line for line in terminal_error_lines):
            return SimulationError(
                type=SimulationErrorType.NGSPICE_CRASH,
                severity=ErrorSeverity.CRITICAL,
                message=f"ngspice 进入不可恢复状态: {self._extract_error_message(output)}",
                file_path=file_path,
                recovery_suggestion="请重启应用，并优先检查前序原始错误日志",
            )

        if any("cannot recover" in line for line in terminal_error_lines):
            return SimulationError(
                type=SimulationErrorType.SYNTAX_ERROR,
                severity=ErrorSeverity.HIGH,
                message=(
                    "ngspice 无法从前序输入错误恢复: "
                    f"{self._extract_error_message(output)}"
                ),
                file_path=file_path,
                recovery_suggestion="请修正最先出现的网表错误后重新提交仿真",
            )
        
        # 节点浮空
        if any(
            "floating" in line or "no dc path" in line
            for line in terminal_error_lines
        ):
            floating_nodes = self._extract_floating_nodes(output)
            return SimulationError(
                type=SimulationErrorType.NODE_FLOATING,
                severity=ErrorSeverity.MEDIUM,
                message=f"存在浮空节点: {', '.join(floating_nodes) if floating_nodes else '未知'}",
                file_path=file_path,
                recovery_suggestion="请确保所有节点都有到地的直流通路，可添加大电阻连接到地",
            )
        
        # 终止性收敛失败。单独的 singular warning 可被 ngspice 的
        # gmin/source stepping 恢复，不能仅凭该 warning 否定最终成功。
        if any(
            "timestep too small" in line
            or re.match(r"^transient solution failed(?:\s|:|-|$)", line)
            for line in diagnostic_lines
        ):
            return SimulationError(
                type=SimulationErrorType.CONVERGENCE_TRAN,
                severity=ErrorSeverity.HIGH,
                message=(
                    "瞬态仿真未收敛并已中止: "
                    f"{self._extract_error_message(output)}"
                ),
                file_path=file_path,
                recovery_suggestion=(
                    "请检查不连续源、正反馈和初始条件，"
                    "必要时放缓源边沿或调整物理模型"
                ),
            )

        if any(
            re.match(r"^dc solution failed(?:\s|:|-|$)", line)
            for line in diagnostic_lines
        ):
            return SimulationError(
                type=SimulationErrorType.CONVERGENCE_DC,
                severity=ErrorSeverity.HIGH,
                message=(
                    "DC 仿真未收敛并已中止: "
                    f"{self._extract_error_message(output)}"
                ),
                file_path=file_path,
                recovery_suggestion=(
                    "请检查缺失的直流通路、理想源冲突和模型工作区"
                ),
            )

        if any(
            "convergence" in line or "no convergence" in line
            for line in terminal_error_lines
        ):
            return SimulationError(
                type=SimulationErrorType.CONVERGENCE_DC,
                severity=ErrorSeverity.MEDIUM,
                message="仿真收敛失败",
                file_path=file_path,
                recovery_suggestion="尝试调整收敛参数（gmin、reltol、itl1）或检查电路拓扑",
            )
        
        # ngspice uses ``stderr Fatal error:`` for deck-level semantic
        # failures as well (for example a .dc source name that is not an
        # independent source).  The callback severity word does not mean the
        # shared library or process is corrupted; wrapper-owned fatal state,
        # access violations and segmentation faults are handled separately.
        if re.search(r"(?im)^\s*stderr\s+fatal error(?:\s|:)", error_output):
            return SimulationError(
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=(
                    "ngspice 拒绝了分析参数: "
                    f"{self._extract_error_message(output)}"
                ),
                file_path=file_path,
                recovery_suggestion="请检查分析卡引用的源、器件和扫描参数",
            )
        
        # Unknown native deck errors are user-input failures, not evidence that
        # the process-wide DLL state is corrupt.  Crash is reserved above for
        # explicit process-integrity diagnostics or wrapper-owned fatal state.
        return SimulationError(
            type=SimulationErrorType.PARAMETER_INVALID,
            severity=ErrorSeverity.HIGH,
            message=f"ngspice 拒绝了网表或分析参数: {self._extract_error_message(output)}",
            file_path=file_path,
            recovery_suggestion="请检查首条 stderr/Fatal error 并修正网表后重试",
        )
    
    def _extract_error_message(self, output: str) -> str:
        """从输出中提取错误消息"""
        lines = output.splitlines()
        for line in lines:
            if "error" in line.lower():
                return line.strip()
        # 返回最后几行
        return '\n'.join(lines[-3:]) if lines else "未知错误"
    
    def _extract_line_number(self, output: str) -> Optional[int]:
        """从输出中提取行号"""
        # 匹配类似 "line 42" 或 "at line 42" 的模式
        match = re.search(r'(?:at\s+)?line\s+(\d+)', output, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_missing_models(self, output: str) -> List[str]:
        """从输出中提取缺失的模型名称"""
        models = []
        # 匹配类似 "model 'xxx' not found" 的模式
        matches = re.findall(r"model\s+['\"]?(\w+)['\"]?\s+(?:not found|unknown)", output, re.IGNORECASE)
        models.extend(matches)
        return models

    def _extract_missing_library_files(self, output: str) -> List[str]:
        """从输出中提取缺失的模型库文件路径。"""
        files = []
        files.extend(re.findall(r'library file\s+(.+?)\s+not found', output, re.IGNORECASE))
        files.extend(re.findall(r'could not find library file\s+(.+)', output, re.IGNORECASE))
        return list(dict.fromkeys(file_path.strip() for file_path in files if file_path.strip()))

    def _extract_missing_subckts(self, output: str) -> List[str]:
        """从输出中提取缺失的子电路名称。"""
        subckts = []
        subckts.extend(re.findall(r'unknown subckt:?\s*([^\s]+)', output, re.IGNORECASE))
        subckts.extend(re.findall(r'subckt\s+([^\s]+)\s+not found', output, re.IGNORECASE))
        return list(dict.fromkeys(name.strip() for name in subckts if name.strip()))
    
    def _extract_floating_nodes(self, output: str) -> List[str]:
        """从输出中提取浮空节点名称"""
        nodes = []
        # 匹配类似 "node 'xxx' is floating" 的模式
        matches = re.findall(r"node\s+['\"]?(\w+)['\"]?\s+(?:is\s+)?floating", output, re.IGNORECASE)
        nodes.extend(matches)
        return nodes


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SpiceExecutor",
    "SUPPORTED_EXTENSIONS",
]
