# SpiceExecutor - SPICE Simulation Executor
"""
SPICE 仿真执行器

职责：
- 实现 SimulationExecutor 接口
- 通过 NgSpiceWrapper 执行 SPICE 电路仿真
- 支持 AC、DC、瞬态、噪声分析
- 动态注入分析命令到网表

执行模式说明：
- 通过 ctypes 直接调用 ngspice 共享库
- ngspice 在同一进程内执行，不需要启动独立子进程
- 这种模式性能更高，且完全控制与 ngspice 的交互

路径解析策略：
- 采用工作目录切换方案，利用 ngspice 原生的相对路径解析能力
- 仿真执行前切换到电路文件所在目录，ngspice 自动基于该目录解析 .include/.lib 引用
- 无需生成临时文件或修改网表内容

使用示例：
    from domain.simulation.executor.spice_executor import SpiceExecutor
    
    executor = SpiceExecutor()
    
    # 检查是否可用
    if not executor.is_available():
        print("ngspice 未正确配置")
    
    # 执行仿真
    result = executor.execute(
        "amplifier.cir",
        {"analysis_type": "ac", "start_freq": 1.0, "stop_freq": 1e9}
    )
    
    if result.success:
        print(f"仿真成功，耗时 {result.duration_seconds:.2f}s")
"""

import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import numpy as np

from domain.simulation.executor.simulation_executor import SimulationExecutor
from domain.simulation.executor.ngspice_shared import (
    NgSpiceWrapper,
    NgSpiceError,
    NgSpiceLoadError,
    VectorInfo,
    VectorType,
)
from domain.simulation.models.simulation_result import (
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
from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    DCAnalysisConfig,
    TransientConfig,
    NoiseConfig,
)
from domain.simulation.service.bundled_spice_library_injector import BundledSpiceLibraryInjector
from infrastructure.utils.ngspice_config import (
    is_ngspice_available,
    get_configuration_error,
    get_ngspice_info,
    get_ngspice_dll_path,
)


# ============================================================
# 常量定义
# ============================================================

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = [".cir", ".sp", ".spice", ".net", ".ckt"]

# 支持的分析类型
SUPPORTED_ANALYSES = ["ac", "dc", "tran", "noise", "op"]

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 300

# 泛型类型变量
T = TypeVar('T')


# ============================================================
# SpiceExecutor - SPICE 仿真执行器
# ============================================================

class SpiceExecutor(SimulationExecutor):
    """
    SPICE 仿真执行器
    
    通过 NgSpiceWrapper 直接调用 ngspice 共享库执行 SPICE 电路仿真。
    支持 AC、DC、瞬态、噪声分析。
    
    特性：
    - 直接调用 ngspice：不依赖 PySpice，避免版本兼容性问题
    - 标准化结果：返回统一的 SimulationResult 数据结构
    - 错误处理：解析 ngspice 输出，提供恢复建议
    - 工作目录切换：自动切换到电路文件所在目录，确保相对路径正确解析
    
    注意：
    - 工作目录是进程级状态，不支持同一进程内并发仿真
    - 如需并发，应使用 subprocess 在独立进程中执行
    """
    
    def __init__(self):
        """初始化 SPICE 执行器"""
        self._logger = logging.getLogger(__name__)
        self._ngspice: Optional[NgSpiceWrapper] = None
        self._init_error: Optional[str] = None
        self._bundled_model_injector = BundledSpiceLibraryInjector(self._logger)
        
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
                self._logger.info("SpiceExecutor 初始化成功")
            else:
                self._init_error = "无法获取 ngspice DLL 路径"
        except NgSpiceError as e:
            self._init_error = str(e)
            self._logger.warning(f"SpiceExecutor 初始化失败: {e}")
        except Exception as e:
            self._init_error = str(e)
            self._logger.exception(f"SpiceExecutor 初始化异常: {e}")

    def _recreate_ngspice(self) -> bool:
        """在 ngspice 进入不可恢复状态后重建 wrapper 实例。"""
        try:
            dll_path = get_ngspice_dll_path()
            if not dll_path:
                self._init_error = "无法获取 ngspice DLL 路径"
                self._ngspice = None
                return False

            self._ngspice = NgSpiceWrapper(dll_path)
            self._init_error = None
            self._logger.info("SpiceExecutor 已重建 ngspice 实例")
            return True
        except Exception as e:
            self._init_error = str(e)
            self._ngspice = None
            self._logger.exception(f"重建 ngspice 实例失败: {e}")
            return False
    
    # ============================================================
    # SimulationExecutor 接口实现
    # ============================================================
    
    def get_name(self) -> str:
        """返回执行器名称"""
        return "spice"
    
    def get_supported_extensions(self) -> List[str]:
        """返回支持的文件扩展名列表"""
        return SUPPORTED_EXTENSIONS.copy()
    
    def get_available_analyses(self) -> List[str]:
        """返回支持的分析类型列表"""
        return SUPPORTED_ANALYSES.copy()
    
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        """
        执行仿真并返回标准化结果
        
        Args:
            file_path: 电路文件路径
            analysis_config: 仿真配置字典
                - analysis_type: 分析类型（"ac", "dc", "tran", "noise", "op"）
                - 其他参数根据分析类型而定
        
        Returns:
            SimulationResult: 标准化的仿真结果对象
        """
        start_time = time.time()
        analysis_type = self._get_analysis_type(analysis_config)
        
        # 若配置未指定分析类型，从网表内容检测
        if not analysis_type:
            try:
                content = Path(file_path).read_text(encoding='utf-8', errors='ignore')
                analysis_type = self._detect_analysis_from_netlist(content)
            except Exception:
                pass
        
        # 1. 校验文件
        valid, error_msg = self.validate_file(file_path)
        if not valid:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E009",
                    type=SimulationErrorType.FILE_ACCESS,
                    severity=ErrorSeverity.HIGH,
                    message=error_msg or "文件校验失败",
                    file_path=file_path,
                ),
                duration_seconds=time.time() - start_time,
            )
        
        # 2. 检查 ngspice 是否可用
        if not self._ngspice:
            error_msg = self._init_error or "ngspice 未初始化"
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E008",
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.CRITICAL,
                    message=error_msg,
                    recovery_suggestion="请检查 ngspice 安装和配置",
                ),
                duration_seconds=time.time() - start_time,
            )
        
        # 3. 切换工作目录到电路文件所在目录，执行仿真
        circuit_path = Path(file_path).resolve()
        circuit_dir = circuit_path.parent
        
        def run_simulation_in_context() -> SimulationResult:
            try:
                result = self._run_simulation(
                    file_path=str(circuit_path),
                    analysis_type=analysis_type,
                    analysis_config=analysis_config,
                )
                result.duration_seconds = time.time() - start_time
                return result
                
            except Exception as e:
                self._logger.exception(f"仿真执行异常: {e}")
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=self._parse_ngspice_output(str(e), file_path),
                    duration_seconds=time.time() - start_time,
                )
        
        return self._execute_with_working_directory(circuit_dir, run_simulation_in_context)

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
    
    def get_ngspice_info(self) -> Dict[str, Any]:
        """
        获取 ngspice 配置信息
        
        Returns:
            Dict: ngspice 配置详情
        """
        return get_ngspice_info()
    
    # ============================================================
    # 分析方法
    # ============================================================
    
    def run_ac_analysis(
        self,
        file_path: str,
        start_freq: float = 1.0,
        stop_freq: float = 1e9,
        points_per_decade: int = 20,
        sweep_type: str = "dec"
    ) -> SimulationResult:
        """执行 AC 小信号分析"""
        config = {
            "analysis_type": "ac",
            "start_freq": start_freq,
            "stop_freq": stop_freq,
            "points_per_decade": points_per_decade,
            "sweep_type": sweep_type,
        }
        return self.execute(file_path, config)
    
    def run_dc_analysis(
        self,
        file_path: str,
        source_name: str,
        start_value: float,
        stop_value: float,
        step: float
    ) -> SimulationResult:
        """执行 DC 扫描分析"""
        config = {
            "analysis_type": "dc",
            "source_name": source_name,
            "start_value": start_value,
            "stop_value": stop_value,
            "step": step,
        }
        return self.execute(file_path, config)
    
    def run_transient_analysis(
        self,
        file_path: str,
        step_time: float,
        end_time: float,
        start_time: float = 0.0,
        max_step: Optional[float] = None,
        use_initial_conditions: bool = False,
    ) -> SimulationResult:
        """执行瞬态分析"""
        config = {
            "analysis_type": "tran",
            "step_time": step_time,
            "end_time": end_time,
            "start_time": start_time,
            "max_step": max_step,
            "use_initial_conditions": use_initial_conditions,
        }
        return self.execute(file_path, config)
    
    def run_noise_analysis(
        self,
        file_path: str,
        output_node: str,
        input_source: str,
        sweep_type: str = "dec",
        points_per_decade: int = 10,
        start_freq: float = 1.0,
        stop_freq: float = 1e6
    ) -> SimulationResult:
        """执行噪声分析"""
        config = {
            "analysis_type": "noise",
            "output_node": output_node,
            "input_source": input_source,
            "sweep_type": sweep_type,
            "points_per_decade": points_per_decade,
            "start_freq": start_freq,
            "stop_freq": stop_freq,
        }
        return self.execute(file_path, config)
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _execute_with_working_directory(
        self,
        target_dir: Path,
        callback: Callable[[], T]
    ) -> T:
        """在指定工作目录下执行回调函数"""
        original_dir = os.getcwd()
        try:
            os.chdir(target_dir)
            self._logger.debug(f"工作目录切换: {original_dir} -> {target_dir}")
            return callback()
        finally:
            os.chdir(original_dir)
            self._logger.debug(f"工作目录恢复: {target_dir} -> {original_dir}")
    
    def _get_analysis_type(self, analysis_config: Optional[Dict[str, Any]]) -> str:
        """从配置中提取分析类型，若配置中未指定则返回空字符串"""
        if analysis_config is None:
            return ""
        return analysis_config.get("analysis_type", "")

    @staticmethod
    def _detect_analysis_from_netlist(netlist_content: str) -> str:
        """
        从网表内容检测分析类型
        
        扫描网表中的分析命令（.ac / .dc / .tran / .noise / .op），
        返回最后一条分析命令对应的类型。
        """
        analysis_type = ""
        for line in netlist_content.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith('*'):
                continue
            for cmd in ('.ac', '.dc', '.tran', '.noise', '.op'):
                if stripped == cmd or (
                    stripped.startswith(cmd)
                    and len(stripped) > len(cmd)
                    and stripped[len(cmd)] in (' ', '\t')
                ):
                    analysis_type = cmd[1:]  # 去掉前缀点
                    break
        return analysis_type

    @staticmethod
    def _detect_analysis_from_plot(plot_name: str) -> str:
        """
        从 ngspice plot 名称推断分析类型
        
        ngspice plot 命名规则：dc1, ac1, tran1, noise1, op1 等
        """
        if not plot_name:
            return ""
        name = plot_name.lower().strip()
        for prefix in ('dc', 'ac', 'tran', 'noise', 'op'):
            if name.startswith(prefix):
                return prefix
        return ""
    
    def _run_simulation(
        self,
        file_path: str,
        analysis_type: str,
        analysis_config: Optional[Dict[str, Any]]
    ) -> SimulationResult:
        """执行仿真核心逻辑"""
        # 重置 ngspice 状态
        self._ngspice.destroy()
        
        # 读取网表内容
        circuit_path = Path(file_path)
        netlist_content = circuit_path.read_text(encoding='utf-8', errors='ignore')
        
        # 注入内置器件模型库（自动为 Q/M/D/J 元件插入对应 .lib 引用）
        netlist_content = self._inject_model_libraries(netlist_content, circuit_path.parent)
        
        # 仅在 analysis_config 显式指定了 analysis_type 时才注入分析命令
        modified_netlist = netlist_content
        analysis_command = ""
        config_has_analysis = analysis_config and analysis_config.get("analysis_type")
        if config_has_analysis:
            analysis_command = self._generate_analysis_command(analysis_type, analysis_config)
            if not analysis_command:
                if analysis_type == "dc":
                    error_message = "DC 分析缺少扫描源名称 source_name"
                    recovery_suggestion = "请在 DC 分析配置中指定源名称，例如 Vin 或 Vdd"
                elif analysis_type == "noise":
                    error_message = "噪声分析缺少输出节点或输入源"
                    recovery_suggestion = "请在噪声分析配置中同时指定 output_node 和 input_source"
                else:
                    error_message = f"分析配置不完整，无法生成 {analysis_type} 分析命令"
                    recovery_suggestion = "请检查当前分析配置中的必填项"

                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E010",
                        type=SimulationErrorType.PARAMETER_INVALID,
                        severity=ErrorSeverity.HIGH,
                        message=error_message,
                        file_path=file_path,
                        recovery_suggestion=recovery_suggestion,
                    ),
                    analysis_command=analysis_command,
                )
            modified_netlist = self._inject_analysis_command(modified_netlist, analysis_command)
        else:
            analysis_command = self._extract_analysis_command_from_netlist(
                modified_netlist,
                analysis_type,
            )
        
        # 注入仿真选项（收敛参数和温度）
        modified_netlist = self._inject_simulation_options(modified_netlist, analysis_config)
        
        # 注入 .MEASURE 语句
        modified_netlist, measure_errors = self._inject_measures(modified_netlist, analysis_config)
        if measure_errors:
            self._logger.warning(
                f"部分 .MEASURE 语句注入失败 ({len(measure_errors)} 个错误)，仿真继续执行"
            )
        
        # 加载网表
        netlist_lines = modified_netlist.splitlines()
        if not self._ngspice.load_netlist(netlist_lines):
            stdout = self._ngspice.get_stdout()
            stderr = self._ngspice.get_stderr()
            combined_output = stdout + "\n" + stderr
            parsed_error = self._parse_ngspice_output(combined_output, file_path)
            
            # 检查是否是严重错误，需要重新初始化
            if self._is_critical_error(combined_output):
                self._logger.warning("检测到 ngspice 严重错误，尝试重建 ngspice 实例...")
                recovery_ok = self._recreate_ngspice()
                parsed_error.recovery_attempted = True
                parsed_error.recovery_result = "success" if recovery_ok else "failed"
            
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=parsed_error,
                raw_output=combined_output,
                analysis_command=analysis_command,
            )
        
        # 执行仿真
        if not self._ngspice.run():
            stdout = self._ngspice.get_stdout()
            stderr = self._ngspice.get_stderr()
            combined_output = stdout + "\n" + stderr
            parsed_error = self._parse_ngspice_output(combined_output, file_path)
            
            if self._is_critical_error(combined_output):
                self._logger.warning("检测到 ngspice 严重错误，尝试重建 ngspice 实例...")
                recovery_ok = self._recreate_ngspice()
                parsed_error.recovery_attempted = True
                parsed_error.recovery_result = "success" if recovery_ok else "failed"
            
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=parsed_error,
                raw_output=combined_output,
                analysis_command=analysis_command,
            )
        
        # 找到最匹配 analysis_type 的 plot 并激活，确保 ngGet_Vec_Info 在正确上下文中工作
        # （多分析命令如 .op + .ac 场景下，run() 后 current plot 可能是 OP 的 "const"，
        #  而非 AC 的 "ac1"，导致 get_vector_info 从错误 plot 读取数据）
        target_plot = self._find_best_analysis_plot(analysis_type)
        if target_plot:
            self._ngspice.execute_command(f"setplot {target_plot}")
            actual_type = self._detect_analysis_from_plot(target_plot)
            if actual_type:
                analysis_type = actual_type
        else:
            actual_type = self._detect_analysis_from_plot(
                self._ngspice.get_current_plot() or ""
            )
            if actual_type:
                analysis_type = actual_type
        
        # 提取仿真数据
        sim_data = self._extract_simulation_data(analysis_type)
        raw_output = self._ngspice.get_stdout()
        
        # 解析 .MEASURE 结果
        measurements = self._parse_measure_results(raw_output, modified_netlist)
        
        return create_success_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            data=sim_data,
            measurements=measurements,
            raw_output=raw_output,
            axis_metadata=self._build_axis_metadata(analysis_type, analysis_config, analysis_command),
            analysis_command=analysis_command,
        )
    
    def _find_best_analysis_plot(self, preferred_type: str) -> Optional[str]:
        """
        从当前所有 ngspice plot 中选取最匹配 preferred_type 的 plot 名称。

        用于多分析命令（如 .op + .ac）场景：run() 结束后，ngspice 的
        current plot 不一定指向目标分析的 plot。此方法通过枚举所有 plot
        并按前缀匹配，确保后续数据提取从正确的 plot 上下文进行。

        Rules:
        - 精确前缀匹配（ac/dc/tran/noise/op）→ 取编号最大（最后一次）的
        - 无精确匹配 → 取第一个非 'const' 的 plot
        - 完全无 plot → 返回 None
        """
        all_plots = self._ngspice.get_all_plots()
        if not all_plots:
            return None

        matches = [
            p for p in all_plots
            if self._detect_analysis_from_plot(p) == preferred_type
        ]
        if matches:
            scored_matches = []
            for plot_name in matches:
                axis_length = self._get_plot_axis_length(plot_name, preferred_type)
                scored_matches.append((axis_length, plot_name))
            scored_matches.sort(key=lambda item: (item[0], item[1]))
            return scored_matches[-1][1]

        non_const = [p for p in all_plots if p.lower() != 'const']
        if non_const:
            return sorted(non_const)[-1]

        return all_plots[0] if all_plots else None

    def _get_plot_axis_length(self, plot_name: str, analysis_type: str) -> int:
        """
        返回指定 plot 的主坐标轴长度。

        对 AC/NOISE 优先识别 frequency 轴，对 TRAN 识别 time 轴，对 DC 识别 sweep 轴。
        若无法识别坐标轴，则返回该 plot 中最长向量长度作为回退。
        """
        current_plot = self._ngspice.get_current_plot()
        try:
            self._ngspice.execute_command(f"setplot {plot_name}")
            vectors = self._ngspice.get_all_vectors()
            axis_length = 0
            fallback_length = 0

            for vec_name in vectors:
                vec_info = self._ngspice.get_vector_info(vec_name)
                if not vec_info:
                    continue

                fallback_length = max(fallback_length, vec_info.length)
                vec_name_lower = vec_name.lower()

                if analysis_type in {"ac", "noise"} and vec_info.type == VectorType.SV_FREQUENCY:
                    axis_length = max(axis_length, vec_info.length)
                    continue

                if analysis_type == "tran" and vec_info.type == VectorType.SV_TIME:
                    axis_length = max(axis_length, vec_info.length)
                    continue

                if analysis_type == "dc" and "sweep" in vec_name_lower:
                    axis_length = max(axis_length, vec_info.length)

            return axis_length if axis_length > 0 else fallback_length
        finally:
            if current_plot:
                self._ngspice.execute_command(f"setplot {current_plot}")

    def _is_critical_error(self, output: str) -> bool:
        """
        检查是否是需要重新初始化的严重错误
        
        Args:
            output: ngspice 输出
            
        Returns:
            bool: 是否是严重错误
        """
        critical_patterns = [
            "cannot recover",
            "awaits to be detached",
            "fatal error",
            "segmentation fault",
            "access violation",
            "internal error",
        ]
        output_lower = output.lower()
        return any(pattern in output_lower for pattern in critical_patterns)
    
    def _generate_analysis_command(
        self,
        analysis_type: str,
        analysis_config: Optional[Dict[str, Any]]
    ) -> str:
        """生成分析命令"""
        if analysis_type == "ac":
            config = ACAnalysisConfig()
            if analysis_config:
                config = ACAnalysisConfig(
                    start_freq=analysis_config.get("start_freq", config.start_freq),
                    stop_freq=analysis_config.get("stop_freq", config.stop_freq),
                    points_per_decade=analysis_config.get("points_per_decade", config.points_per_decade),
                    sweep_type=analysis_config.get("sweep_type", config.sweep_type),
                )
            return f".ac {config.sweep_type} {config.points_per_decade} {config.start_freq} {config.stop_freq}"
        
        elif analysis_type == "dc":
            config = DCAnalysisConfig()
            if analysis_config:
                config = DCAnalysisConfig(
                    source_name=analysis_config.get("source_name", config.source_name),
                    start_value=analysis_config.get("start_value", config.start_value),
                    stop_value=analysis_config.get("stop_value", config.stop_value),
                    step=analysis_config.get("step", config.step),
                )
            if not config.source_name:
                return ""  # DC 分析需要指定源
            return f".dc {config.source_name} {config.start_value} {config.stop_value} {config.step}"
        
        elif analysis_type == "tran":
            config = TransientConfig()
            if analysis_config:
                config = TransientConfig(
                    step_time=analysis_config.get("step_time", config.step_time),
                    end_time=analysis_config.get("end_time", config.end_time),
                    start_time=analysis_config.get("start_time", config.start_time),
                    max_step=analysis_config.get("max_step", config.max_step),
                    use_initial_conditions=analysis_config.get("use_initial_conditions", config.use_initial_conditions),
                )
            cmd = f".tran {config.step_time} {config.end_time}"
            if config.start_time > 0 or config.max_step:
                cmd += f" {config.start_time}"
            if config.max_step:
                cmd += f" {config.max_step}"
            if config.use_initial_conditions:
                cmd += " uic"
            return cmd
        
        elif analysis_type == "noise":
            config = NoiseConfig()
            if analysis_config:
                config = NoiseConfig(
                    output_node=analysis_config.get("output_node", config.output_node),
                    input_source=analysis_config.get("input_source", config.input_source),
                    sweep_type=analysis_config.get("sweep_type", config.sweep_type),
                    points_per_decade=analysis_config.get("points_per_decade", config.points_per_decade),
                    start_freq=analysis_config.get("start_freq", config.start_freq),
                    stop_freq=analysis_config.get("stop_freq", config.stop_freq),
                )
            if not config.output_node or not config.input_source:
                return ""
            return f".noise v({config.output_node}) {config.input_source} {config.sweep_type} {config.points_per_decade} {config.start_freq} {config.stop_freq}"
        
        elif analysis_type == "op":
            return ".op"
        
        return ""

    def _build_axis_metadata(
        self,
        analysis_type: str,
        analysis_config: Optional[Dict[str, Any]],
        analysis_command: str,
    ) -> Dict[str, Any]:
        command_tokens = analysis_command.split()

        if analysis_type == "ac":
            sweep_type = self._resolve_frequency_sweep_type(analysis_config, command_tokens, sweep_type_index=1)
            return {
                "x_axis_kind": "frequency",
                "x_axis_label": "Frequency (Hz)",
                "x_axis_scale": self._resolve_frequency_axis_scale(sweep_type),
                "requested_x_range": self._build_requested_range(
                    analysis_config.get("start_freq") if analysis_config else self._get_command_token(command_tokens, 3),
                    analysis_config.get("stop_freq") if analysis_config else self._get_command_token(command_tokens, 4),
                ),
            }

        if analysis_type == "dc":
            source_name = (analysis_config.get("source_name") if analysis_config else None) or self._get_command_token(command_tokens, 1) or "Sweep"
            return {
                "x_axis_kind": "sweep",
                "x_axis_label": source_name,
                "requested_x_range": self._build_requested_range(
                    analysis_config.get("start_value") if analysis_config else self._get_command_token(command_tokens, 2),
                    analysis_config.get("stop_value") if analysis_config else self._get_command_token(command_tokens, 3),
                ),
            }

        if analysis_type == "tran":
            return {
                "x_axis_kind": "time",
                "x_axis_label": "Time (s)",
                "requested_x_range": self._build_requested_range(
                    analysis_config.get("start_time", 0.0) if analysis_config else (self._get_command_token(command_tokens, 3) or 0.0),
                    analysis_config.get("end_time") if analysis_config else self._get_command_token(command_tokens, 2),
                ),
            }

        if analysis_type == "noise":
            sweep_type = self._resolve_frequency_sweep_type(analysis_config, command_tokens, sweep_type_index=3)
            return {
                "x_axis_kind": "frequency",
                "x_axis_label": "Frequency (Hz)",
                "x_axis_scale": self._resolve_frequency_axis_scale(sweep_type),
                "requested_x_range": self._build_requested_range(
                    analysis_config.get("start_freq") if analysis_config else self._get_command_token(command_tokens, 5),
                    analysis_config.get("stop_freq") if analysis_config else self._get_command_token(command_tokens, 6),
                ),
            }

        return {}

    def _resolve_frequency_sweep_type(
        self,
        analysis_config: Optional[Dict[str, Any]],
        command_tokens: List[str],
        *,
        sweep_type_index: int,
    ) -> str:
        sweep_type = (analysis_config.get("sweep_type") if analysis_config else None) or self._get_command_token(command_tokens, sweep_type_index) or "dec"
        sweep_type = str(sweep_type).lower()
        return sweep_type if sweep_type in {"dec", "oct", "lin"} else "dec"

    def _resolve_frequency_axis_scale(self, sweep_type: str) -> str:
        return "linear" if sweep_type == "lin" else "log"

    def _get_command_token(self, command_tokens: List[str], index: int) -> Optional[str]:
        if 0 <= index < len(command_tokens):
            return command_tokens[index]
        return None

    def _build_requested_range(
        self,
        start_value: Any,
        stop_value: Any,
    ) -> Optional[Tuple[float, float]]:
        try:
            start = float(start_value)
            stop = float(stop_value)
        except (TypeError, ValueError):
            return None

        if not np.isfinite(start) or not np.isfinite(stop):
            return None

        return (start, stop)
    
    def _inject_analysis_command(self, netlist: str, analysis_command: str) -> str:
        """将分析命令注入到网表中"""
        if not analysis_command:
            return netlist
        
        lines = netlist.splitlines()
        result_lines = []
        
        # 检查网表中是否已有相同类型的分析命令
        analysis_type = analysis_command.split()[0].lower()  # 如 ".ac", ".dc", ".tran"
        has_analysis = False
        has_end = False
        
        for line in lines:
            stripped = line.strip().lower()
            if stripped == analysis_type or (stripped.startswith(analysis_type) and len(stripped) > len(analysis_type) and stripped[len(analysis_type)] in (' ', '\t')):
                # 替换现有的分析命令
                result_lines.append(analysis_command)
                has_analysis = True
            elif stripped == ".end":
                has_end = True
                # 在 .end 之前插入分析命令（如果还没有）
                if not has_analysis:
                    result_lines.append(analysis_command)
                result_lines.append(line)
            else:
                result_lines.append(line)
        
        # 如果网表没有 .end 语句，在末尾添加分析命令和 .end
        if not has_end:
            if not has_analysis:
                result_lines.append(analysis_command)
            result_lines.append(".end")
        
        return '\n'.join(result_lines)

    def _extract_analysis_command_from_netlist(
        self,
        netlist: str,
        analysis_type: str,
    ) -> str:
        command_prefix = f".{(analysis_type or '').lower()}"
        if command_prefix == ".":
            return ""

        resolved_command = ""
        for line in netlist.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if not stripped or lowered.startswith("*"):
                continue
            if lowered == command_prefix or (
                lowered.startswith(command_prefix)
                and len(lowered) > len(command_prefix)
                and lowered[len(command_prefix)] in (" ", "\t")
            ):
                resolved_command = stripped
        return resolved_command

    def _inject_simulation_options(
        self,
        netlist: str,
        analysis_config: Optional[Dict[str, Any]]
    ) -> str:
        """
        注入仿真选项（收敛参数、温度）到网表
        
        在 .end 之前插入 .options 和 .temp 语句，覆盖网表中已有的同名选项。
        """
        if not analysis_config:
            return netlist
        
        inject_lines = []
        
        # 收敛参数
        convergence = analysis_config.get("convergence")
        if convergence and isinstance(convergence, dict):
            param_map = {
                "gmin": "GMIN",
                "abstol": "ABSTOL",
                "reltol": "RELTOL",
                "vntol": "VNTOL",
                "itl1": "ITL1",
                "itl4": "ITL4",
            }
            options_parts = []
            for key, spice_key in param_map.items():
                value = convergence.get(key)
                if value is not None:
                    options_parts.append(f"{spice_key}={value}")
            if options_parts:
                inject_lines.append(f".options {' '.join(options_parts)}")
        
        # 温度
        temperature = analysis_config.get("temperature")
        if temperature is not None:
            inject_lines.append(f".temp {temperature}")
        
        if not inject_lines:
            return netlist
        
        # 在 .end 之前注入（使注入的选项覆盖网表中已有的同名选项）
        lines = netlist.splitlines()
        result_lines = []
        injected = False
        for line in lines:
            if line.strip().lower() == ".end" and not injected:
                for inject_line in inject_lines:
                    result_lines.append(inject_line)
                injected = True
            result_lines.append(line)
        if not injected:
            for inject_line in inject_lines:
                result_lines.append(inject_line)
        
        return '\n'.join(result_lines)
    
    def _inject_measures(
        self,
        netlist: str,
        analysis_config: Optional[Dict[str, Any]]
    ) -> Tuple[str, list]:
        """
        从 analysis_config["measures"] 提取 .MEASURE 语句并注入到网表
        
        Args:
            netlist: 原始网表内容
            analysis_config: 仿真配置字典，"measures" 键为 .MEASURE 语句列表
        
        Returns:
            Tuple[str, list]: (修改后的网表, 验证错误列表)
        """
        if not analysis_config:
            return netlist, []
        
        measures = analysis_config.get("measures")
        if not measures:
            return netlist, []
        
        try:
            from domain.simulation.measure.measure_injector import measure_injector
            modified, errors = measure_injector.inject_measures(netlist, measures)
            if errors:
                for err in errors:
                    self._logger.warning(
                        f".MEASURE 验证失败 [{err.error_type}]: {err.message} | 语句: {err.statement}"
                    )
            return modified, errors
        except Exception as e:
            self._logger.warning(f"注入 .MEASURE 语句异常: {e}")
            return netlist, []
    
    def _inject_model_libraries(self, netlist: str, circuit_dir: Path) -> str:
        return self._bundled_model_injector.inject(netlist, circuit_dir)

    # ============================================================

    def _extract_simulation_data(self, analysis_type: str) -> SimulationData:
        """
        从 ngspice 提取仿真数据
        
        根据 analysis_type 决定如何提取独立变量：
        - ac:   提取 SV_FREQUENCY 作为 frequency 轴
        - tran: 提取 SV_TIME 作为 time 轴
        - dc:   提取名称含 "sweep" 的向量作为 sweep 轴
        - 其他: 按向量类型自动判断
        """
        frequency = None
        time_data = None
        sweep_data = None
        sweep_name = None
        signals = {}
        signal_types = {}
        is_dc = (analysis_type == "dc")
        
        # 获取所有向量
        vectors = self._ngspice.get_all_vectors()
        self._logger.debug(f"可用向量: {vectors} (analysis_type={analysis_type})")
        
        for vec_name in vectors:
            vec_info = self._ngspice.get_vector_info(vec_name)
            if not vec_info:
                continue
            
            # DC 分析：检测扫描变量（ngspice 命名为 "v-sweep" / "i-sweep" 等）
            if is_dc and 'sweep' in vec_name.lower():
                if vec_info.data is not None and len(vec_info.data) > 0:
                    sweep_data = vec_info.data
                    sweep_name = vec_name
                elif vec_info.cdata is not None and len(vec_info.cdata) > 0:
                    sweep_data = np.real(vec_info.cdata)
                    sweep_name = vec_name
                continue
            
            # 标准化信号名称（ngspice 返回小写，统一转为大写 V/I 开头）
            normalized_name = self._normalize_signal_name(vec_name, vec_info.type)
            
            # 确定信号类型标签
            type_label = self._get_signal_type_label(vec_info.type)
            
            # 根据向量类型处理
            if vec_info.type == VectorType.SV_FREQUENCY:
                # 频率数据：优先使用实数数据，如果没有则从复数数据提取实部
                if vec_info.data is not None and len(vec_info.data) > 0:
                    frequency = vec_info.data
                elif vec_info.cdata is not None and len(vec_info.cdata) > 0:
                    frequency = np.real(vec_info.cdata)
            elif vec_info.type == VectorType.SV_TIME:
                # 时间数据：优先使用实数数据
                if vec_info.data is not None and len(vec_info.data) > 0:
                    time_data = vec_info.data
                elif vec_info.cdata is not None and len(vec_info.cdata) > 0:
                    time_data = np.real(vec_info.cdata)
            else:
                # 其他向量作为信号
                if vec_info.cdata is not None and len(vec_info.cdata) > 0:
                    # 复数数据（AC 分析）
                    # 保存原始复数数据，供指标提取器使用
                    signals[normalized_name] = vec_info.cdata
                    signal_types[normalized_name] = type_label
                    # 同时保存分解后的数据，供 UI 显示使用，继承父信号类型
                    signals[f"{normalized_name}_mag"] = np.abs(vec_info.cdata)
                    signal_types[f"{normalized_name}_mag"] = type_label
                    signals[f"{normalized_name}_phase"] = np.angle(vec_info.cdata, deg=True)
                    signal_types[f"{normalized_name}_phase"] = type_label
                    signals[f"{normalized_name}_real"] = np.real(vec_info.cdata)
                    signal_types[f"{normalized_name}_real"] = type_label
                    signals[f"{normalized_name}_imag"] = np.imag(vec_info.cdata)
                    signal_types[f"{normalized_name}_imag"] = type_label
                elif vec_info.data is not None and len(vec_info.data) > 0:
                    # 实数数据
                    signals[normalized_name] = vec_info.data
                    signal_types[normalized_name] = type_label
        
        return SimulationData(
            frequency=frequency,
            time=time_data,
            sweep=sweep_data,
            sweep_name=sweep_name,
            signals=signals,
            signal_types=signal_types,
        )
    
    def _normalize_signal_name(self, name: str, vec_type: int = 0) -> str:
        """
        标准化信号名称
        
        ngspice 返回的向量名称是小写的（如 v(out)），
        将其转换为标准格式（如 V(out)）以便与指标提取器匹配。
        
        Args:
            name: 原始信号名称
            vec_type: ngspice 向量类型（VectorType 常量）
            
        Returns:
            str: 标准化后的信号名称
        """
        # 处理电压信号 v(...) -> V(...)
        if name.startswith('v(') and name.endswith(')'):
            return 'V(' + name[2:-1] + ')'
        
        # 处理电流信号 i(...) -> I(...)
        if name.startswith('i(') and name.endswith(')'):
            return 'I(' + name[2:-1] + ')'
        
        # 处理带 #branch 的电流信号
        if '#branch' in name.lower():
            # 如 v1#branch -> I(V1)
            parts = name.lower().split('#branch')
            if parts[0]:
                return f'I({parts[0].upper()})'
        
        # 处理裸节点名：根据 ngspice 向量类型添加 V()/I() 前缀
        if vec_type == VectorType.SV_VOLTAGE and not name.upper().startswith(('V(', 'I(')):
            return f'V({name})'
        if vec_type == VectorType.SV_CURRENT and not name.upper().startswith(('V(', 'I(')):
            return f'I({name})'
        
        return name
    
    def _get_signal_type_label(self, vec_type: int) -> str:
        """将 ngspice 向量类型映射为可读分类标签"""
        if vec_type == VectorType.SV_VOLTAGE:
            return "voltage"
        elif vec_type == VectorType.SV_CURRENT:
            return "current"
        else:
            return "other"
    
    def _parse_measure_results(self, raw_output: str, netlist: str = "") -> list:
        """
        从 ngspice 输出中解析 .MEASURE 结果
        
        Args:
            raw_output: ngspice 原始输出
            
        Returns:
            list: MeasureResult 对象列表
        """
        try:
            from domain.simulation.measure.measure_parser import measure_parser
            from domain.simulation.measure.measure_metadata import measure_metadata_resolver
            
            results = measure_parser.parse_measure_output(raw_output)
            definitions = measure_metadata_resolver.extract_definitions(netlist) if netlist else {}

            for result in results:
                definition = definitions.get(result.name)
                metadata = measure_metadata_resolver.resolve(
                    result.name,
                    statement=definition.statement if definition else result.statement,
                    description=definition.description if definition else result.description,
                    fallback_unit=result.unit,
                )
                if definition:
                    result.statement = definition.statement
                    result.description = definition.description
                result.unit = metadata.unit
                result.display_name = metadata.display_name
                result.category = metadata.category
                result.quantity_kind = metadata.quantity_kind
            
            if results:
                self._logger.info(f"解析到 {len(results)} 个 .MEASURE 结果")
                for r in results:
                    self._logger.debug(f"  {r.name} = {r.value} {r.unit}")
            
            return results
            
        except Exception as e:
            self._logger.warning(f"解析 .MEASURE 结果失败: {e}")
            return []
    
    def _parse_ngspice_output(
        self,
        output: str,
        file_path: str
    ) -> SimulationError:
        """解析 ngspice 输出，提取错误信息"""
        output_lower = output.lower()

        if "library file" in output_lower and "not found" in output_lower:
            missing_files = self._extract_missing_library_files(output)
            return SimulationError(
                code="E009",
                type=SimulationErrorType.FILE_ACCESS,
                severity=ErrorSeverity.HIGH,
                message=f"模型库文件不存在: {', '.join(missing_files) if missing_files else '未知路径'}",
                file_path=file_path,
                recovery_suggestion="请检查 .lib/.include 路径是否有效，或确认内置模型库已正确注入",
            )

        if "unknown subckt" in output_lower or ("subckt" in output_lower and "not found" in output_lower):
            missing_subckts = self._extract_missing_subckts(output)
            return SimulationError(
                code="E002",
                type=SimulationErrorType.MODEL_MISSING,
                severity=ErrorSeverity.HIGH,
                message=f"缺少子电路定义: {', '.join(missing_subckts) if missing_subckts else '未知'}",
                file_path=file_path,
                recovery_suggestion="请添加缺失的 .SUBCKT 定义或 .include/.lib 子电路文件",
            )

        if "undefined parameter" in output_lower or "cannot compute substitute" in output_lower:
            line_num = self._extract_line_number(output)
            return SimulationError(
                code="E010",
                type=SimulationErrorType.PARAMETER_INVALID,
                severity=ErrorSeverity.HIGH,
                message=f"模型或参数表达式不兼容: {self._extract_error_message(output)}",
                file_path=file_path,
                line_number=line_num,
                recovery_suggestion="请检查模型参数是否被当前 ngspice 版本支持，或移除不兼容的厂商/额定值元数据",
            )

        # 模型缺失
        if "model" in output_lower and ("not found" in output_lower or "unknown" in output_lower):
            missing_models = self._extract_missing_models(output)
            return SimulationError(
                code="E002",
                type=SimulationErrorType.MODEL_MISSING,
                severity=ErrorSeverity.HIGH,
                message=f"缺少模型定义: {', '.join(missing_models) if missing_models else '未知'}",
                file_path=file_path,
                recovery_suggestion="请添加缺失的 .model 语句或 .include 模型文件",
            )

        # 语法错误
        if (
            "syntax" in output_lower
            or "parse error" in output_lower
            or "unimplemented dot command" in output_lower
            or re.search(r'error\s+on\s+line\s+\d+', output_lower)
        ):
            line_num = self._extract_line_number(output)
            return SimulationError(
                code="E001",
                type=SimulationErrorType.SYNTAX_ERROR,
                severity=ErrorSeverity.HIGH,
                message=f"网表语法错误: {self._extract_error_message(output)}",
                file_path=file_path,
                line_number=line_num,
                recovery_suggestion="请检查网表语法，确保所有元件和节点名称正确",
            )

        if "cannot recover" in output_lower or "awaits to be detached" in output_lower:
            return SimulationError(
                code="E008",
                type=SimulationErrorType.NGSPICE_CRASH,
                severity=ErrorSeverity.CRITICAL,
                message=f"ngspice 进入不可恢复状态: {self._extract_error_message(output)}",
                file_path=file_path,
                recovery_suggestion="请重建 ngspice 实例后重试，并优先检查前序原始错误日志",
            )
        
        # 节点浮空
        if "floating" in output_lower or "no dc path" in output_lower:
            floating_nodes = self._extract_floating_nodes(output)
            return SimulationError(
                code="E003",
                type=SimulationErrorType.NODE_FLOATING,
                severity=ErrorSeverity.MEDIUM,
                message=f"存在浮空节点: {', '.join(floating_nodes) if floating_nodes else '未知'}",
                file_path=file_path,
                recovery_suggestion="请确保所有节点都有到地的直流通路，可添加大电阻连接到地",
            )
        
        # 收敛失败
        if "convergence" in output_lower or "no convergence" in output_lower or "singular matrix" in output_lower:
            return SimulationError(
                code="E004",
                type=SimulationErrorType.CONVERGENCE_DC,
                severity=ErrorSeverity.MEDIUM,
                message="仿真收敛失败",
                file_path=file_path,
                recovery_suggestion="尝试调整收敛参数（gmin、reltol、itl1）或检查电路拓扑",
            )
        
        # 超时
        if "timeout" in output_lower:
            return SimulationError(
                code="E006",
                type=SimulationErrorType.TIMEOUT,
                severity=ErrorSeverity.MEDIUM,
                message="仿真超时",
                file_path=file_path,
                recovery_suggestion="尝试减少仿真时间范围或增加步长",
            )
        
        # 默认错误（使用 NGSPICE_CRASH 作为通用错误类型）
        return SimulationError(
            code="E008",
            type=SimulationErrorType.NGSPICE_CRASH,
            severity=ErrorSeverity.HIGH,
            message=f"仿真失败: {self._extract_error_message(output)}",
            file_path=file_path,
            recovery_suggestion="请检查 ngspice 输出日志获取详细信息",
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
    "SUPPORTED_ANALYSES",
]
