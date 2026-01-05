# SpiceExecutor - SPICE Simulation Executor
"""
SPICE 仿真执行器

职责：
- 实现 SimulationExecutor 接口
- 封装 PySpice 库执行 SPICE 电路仿真
- 支持 AC、DC、瞬态、噪声分析
- 通过 NgSpiceShared 共享库模式调用 ngspice

执行模式说明：
- PySpice 通过 NgSpiceShared 共享库模式调用 ngspice
- ngspice 在同一进程内执行，不需要启动独立子进程
- 这种模式性能更高，但需要确保 ngspice 共享库路径正确配置

路径解析策略：
- 采用工作目录切换方案，利用 ngspice 原生的相对路径解析能力
- 仿真执行前切换到电路文件所在目录，ngspice 自动基于该目录解析 .include/.lib 引用
- 无需生成临时文件或修改网表内容

职责说明：
- ngspice 路径配置委托给 ngspice_config
- 错误解析作为执行器内部职责（_parse_exception 方法）
- 本模块专注于仿真执行核心逻辑

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
        # 获取输出信号
        vout = result.get_signal("V(out)")
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import numpy as np

from domain.simulation.executor.simulation_executor import SimulationExecutor
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
    create_syntax_error,
    create_convergence_error,
    create_timeout_error,
)
from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    DCAnalysisConfig,
    TransientConfig,
    NoiseConfig,
    GlobalSimulationConfig,
)
from infrastructure.utils.ngspice_config import (
    is_ngspice_available,
    get_configuration_error,
    get_ngspice_info,
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

# 泛型类型变量（用于 _execute_with_working_directory）
T = TypeVar('T')


# ============================================================
# SpiceExecutor - SPICE 仿真执行器
# ============================================================

class SpiceExecutor(SimulationExecutor):
    """
    SPICE 仿真执行器
    
    使用 PySpice 的 NgSpiceShared 共享库模式执行 SPICE 电路仿真。
    支持 AC、DC、瞬态、噪声分析。
    
    特性：
    - 共享库模式：ngspice 在同一进程内执行，性能更高
    - 标准化结果：返回统一的 SimulationResult 数据结构
    - 错误处理：捕获并解析 ngspice 错误，提供恢复建议
    - 工作目录切换：自动切换到电路文件所在目录，确保相对路径正确解析
    
    注意：
    - 工作目录是进程级状态，不支持同一进程内并发仿真
    - 如需并发，应使用 subprocess 在独立进程中执行
    """
    
    def __init__(self):
        """初始化 SPICE 执行器"""
        self._logger = logging.getLogger(__name__)
        self._circuit = None
        self._simulator = None
        
        # 检查 ngspice 是否可用
        if not is_ngspice_available():
            error_msg = get_configuration_error() or "ngspice 未正确配置"
            self._logger.warning(f"SpiceExecutor 初始化警告: {error_msg}")
    
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
        
        # 1. 校验文件（优先于 ngspice 检查，确保文件错误优先报告）
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
        if not is_ngspice_available():
            error_msg = get_configuration_error() or "ngspice 未正确配置"
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
        # ngspice 会基于当前工作目录解析 .include/.lib 中的相对路径
        circuit_path = Path(file_path).resolve()
        circuit_dir = circuit_path.parent
        circuit_filename = circuit_path.name
        
        def run_simulation_in_context() -> SimulationResult:
            # 加载电路文件（使用文件名，因为已在正确的工作目录）
            try:
                circuit_content = self._load_circuit_file(circuit_filename)
            except Exception as e:
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E009",
                        type=SimulationErrorType.FILE_ACCESS,
                        severity=ErrorSeverity.HIGH,
                        message=f"加载电路文件失败: {e}",
                        file_path=file_path,
                    ),
                    duration_seconds=time.time() - start_time,
                )
            
            # 执行仿真
            try:
                result = self._run_simulation(
                    file_path=file_path,
                    circuit_content=circuit_content,
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
                    error=self._parse_exception(e, file_path),
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
        return is_ngspice_available()
    
    def get_ngspice_info(self) -> Dict[str, Any]:
        """
        获取 ngspice 配置信息
        
        Returns:
            Dict: ngspice 配置详情
        """
        return get_ngspice_info()
    
    def load_circuit(self, spice_file_path: str) -> bool:
        """
        加载 SPICE 网表文件
        
        Args:
            spice_file_path: 网表文件路径
            
        Returns:
            bool: 是否加载成功
        """
        try:
            self._circuit = self._load_circuit_file(spice_file_path)
            return True
        except Exception as e:
            self._logger.error(f"加载电路失败: {e}")
            return False
    
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
        """
        执行 AC 小信号分析
        
        Args:
            file_path: 电路文件路径
            start_freq: 起始频率（Hz）
            stop_freq: 终止频率（Hz）
            points_per_decade: 每十倍频程点数
            sweep_type: 扫描类型（dec/oct/lin）
            
        Returns:
            SimulationResult: 仿真结果
        """
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
        """
        执行 DC 扫描分析
        
        Args:
            file_path: 电路文件路径
            source_name: 扫描源名称
            start_value: 起始值
            stop_value: 终止值
            step: 步进值
            
        Returns:
            SimulationResult: 仿真结果
        """
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
        max_step: Optional[float] = None
    ) -> SimulationResult:
        """
        执行瞬态分析
        
        Args:
            file_path: 电路文件路径
            step_time: 时间步长（秒）
            end_time: 终止时间（秒）
            start_time: 起始时间（秒）
            max_step: 最大步长（秒）
            
        Returns:
            SimulationResult: 仿真结果
        """
        config = {
            "analysis_type": "tran",
            "step_time": step_time,
            "end_time": end_time,
            "start_time": start_time,
            "max_step": max_step,
        }
        return self.execute(file_path, config)
    
    def run_noise_analysis(
        self,
        file_path: str,
        output_node: str,
        input_source: str,
        start_freq: float = 1.0,
        stop_freq: float = 1e6
    ) -> SimulationResult:
        """
        执行噪声分析
        
        Args:
            file_path: 电路文件路径
            output_node: 输出节点
            input_source: 输入源
            start_freq: 起始频率（Hz）
            stop_freq: 终止频率（Hz）
            
        Returns:
            SimulationResult: 仿真结果
        """
        config = {
            "analysis_type": "noise",
            "output_node": output_node,
            "input_source": input_source,
            "start_freq": start_freq,
            "stop_freq": stop_freq,
        }
        return self.execute(file_path, config)
    
    # ============================================================
    # 数据提取方法
    # ============================================================
    
    def get_node_voltage(self, node_name: str) -> Optional[np.ndarray]:
        """
        获取节点电压
        
        Args:
            node_name: 节点名称
            
        Returns:
            Optional[np.ndarray]: 电压数据，若不存在则返回 None
        """
        # 此方法需要在仿真执行后调用
        # 实际实现需要访问 PySpice 的仿真结果
        self._logger.warning("get_node_voltage: 需要先执行仿真")
        return None
    
    def get_branch_current(self, element_name: str) -> Optional[np.ndarray]:
        """
        获取支路电流
        
        Args:
            element_name: 元件名称
            
        Returns:
            Optional[np.ndarray]: 电流数据，若不存在则返回 None
        """
        # 此方法需要在仿真执行后调用
        self._logger.warning("get_branch_current: 需要先执行仿真")
        return None
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _execute_with_working_directory(
        self,
        target_dir: Path,
        callback: Callable[[], T]
    ) -> T:
        """
        在指定工作目录下执行回调函数
        
        ngspice 在解析 .include 和 .lib 语句时，会基于当前工作目录解析相对路径。
        通过切换到电路文件所在目录，可以让 ngspice 自动正确解析所有相对路径引用。
        
        Args:
            target_dir: 目标工作目录
            callback: 要执行的回调函数
            
        Returns:
            回调函数的返回值
            
        Note:
            - 使用 try-finally 确保无论成功或失败都恢复原工作目录
            - 工作目录是进程级状态，不支持同一进程内并发仿真
        """
        original_dir = os.getcwd()
        try:
            os.chdir(target_dir)
            self._logger.debug(f"工作目录切换: {original_dir} -> {target_dir}")
            return callback()
        finally:
            os.chdir(original_dir)
            self._logger.debug(f"工作目录恢复: {target_dir} -> {original_dir}")
    
    def _get_analysis_type(self, analysis_config: Optional[Dict[str, Any]]) -> str:
        """从配置中提取分析类型"""
        if analysis_config is None:
            return "ac"
        return analysis_config.get("analysis_type", "ac")
    
    def _load_circuit_file(self, file_path: str) -> str:
        """
        加载电路文件内容
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 文件内容
        """
        path = Path(file_path)
        return path.read_text(encoding='utf-8', errors='ignore')

    def _run_simulation(
        self,
        file_path: str,
        circuit_content: str,
        analysis_type: str,
        analysis_config: Optional[Dict[str, Any]]
    ) -> SimulationResult:
        """
        执行仿真核心逻辑
        
        Args:
            file_path: 电路文件路径
            circuit_content: 电路文件内容
            analysis_type: 分析类型
            analysis_config: 分析配置
            
        Returns:
            SimulationResult: 仿真结果
        """
        try:
            # 延迟导入 PySpice，确保 ngspice_config 已执行
            from PySpice.Spice.NgSpice.Shared import NgSpiceShared
            from PySpice.Spice.Parser import SpiceParser
            from PySpice.Probe.Plot import plot
            
        except ImportError as e:
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=SimulationError(
                    code="E008",
                    type=SimulationErrorType.NGSPICE_CRASH,
                    severity=ErrorSeverity.CRITICAL,
                    message=f"PySpice 导入失败: {e}",
                    recovery_suggestion="请确保 PySpice 已正确安装",
                ),
            )
        
        raw_output = ""
        
        try:
            # 解析电路
            parser = SpiceParser(source=circuit_content)
            circuit = parser.build_circuit()
            
            # 创建仿真器
            simulator = circuit.simulator(
                temperature=27,
                nominal_temperature=27
            )
            
            # 根据分析类型执行仿真
            if analysis_type == "ac":
                analysis_result = self._run_ac(simulator, analysis_config)
            elif analysis_type == "dc":
                analysis_result = self._run_dc(simulator, analysis_config)
            elif analysis_type == "tran":
                analysis_result = self._run_tran(simulator, analysis_config)
            elif analysis_type == "noise":
                analysis_result = self._run_noise(simulator, analysis_config)
            elif analysis_type == "op":
                analysis_result = self._run_op(simulator, analysis_config)
            else:
                return create_error_result(
                    executor=self.get_name(),
                    file_path=file_path,
                    analysis_type=analysis_type,
                    error=SimulationError(
                        code="E010",
                        type=SimulationErrorType.PARAMETER_INVALID,
                        severity=ErrorSeverity.HIGH,
                        message=f"不支持的分析类型: {analysis_type}",
                        recovery_suggestion=f"支持的分析类型: {', '.join(SUPPORTED_ANALYSES)}",
                    ),
                )
            
            # 提取仿真数据
            sim_data = self._extract_simulation_data(analysis_result, analysis_type)
            
            return create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                data=sim_data,
                raw_output=raw_output,
            )
            
        except Exception as e:
            # 解析异常并返回错误结果
            error = self._parse_exception(e, file_path)
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=error,
                raw_output=raw_output,
            )
    
    def _run_ac(
        self,
        simulator,
        analysis_config: Optional[Dict[str, Any]]
    ):
        """
        执行 AC 分析
        
        Args:
            simulator: PySpice 仿真器
            analysis_config: 分析配置
            
        Returns:
            分析结果对象
        """
        config = ACAnalysisConfig()
        if analysis_config:
            config = ACAnalysisConfig(
                start_freq=analysis_config.get("start_freq", config.start_freq),
                stop_freq=analysis_config.get("stop_freq", config.stop_freq),
                points_per_decade=analysis_config.get("points_per_decade", config.points_per_decade),
                sweep_type=analysis_config.get("sweep_type", config.sweep_type),
            )
        
        # 执行 AC 分析
        analysis = simulator.ac(
            start_frequency=config.start_freq,
            stop_frequency=config.stop_freq,
            number_of_points=config.points_per_decade,
            variation=config.sweep_type,
        )
        
        return analysis
    
    def _run_dc(
        self,
        simulator,
        analysis_config: Optional[Dict[str, Any]]
    ):
        """
        执行 DC 分析
        
        Args:
            simulator: PySpice 仿真器
            analysis_config: 分析配置
            
        Returns:
            分析结果对象
        """
        config = DCAnalysisConfig()
        if analysis_config:
            config = DCAnalysisConfig(
                source_name=analysis_config.get("source_name", config.source_name),
                start_value=analysis_config.get("start_value", config.start_value),
                stop_value=analysis_config.get("stop_value", config.stop_value),
                step=analysis_config.get("step", config.step),
            )
        
        if not config.source_name:
            raise ValueError("DC 分析需要指定 source_name")
        
        # 执行 DC 分析
        analysis = simulator.dc(**{
            config.source_name: slice(config.start_value, config.stop_value, config.step)
        })
        
        return analysis
    
    def _run_tran(
        self,
        simulator,
        analysis_config: Optional[Dict[str, Any]]
    ):
        """
        执行瞬态分析
        
        Args:
            simulator: PySpice 仿真器
            analysis_config: 分析配置
            
        Returns:
            分析结果对象
        """
        config = TransientConfig()
        if analysis_config:
            config = TransientConfig(
                step_time=analysis_config.get("step_time", config.step_time),
                end_time=analysis_config.get("end_time", config.end_time),
                start_time=analysis_config.get("start_time", config.start_time),
                max_step=analysis_config.get("max_step", config.max_step),
                use_initial_conditions=analysis_config.get("use_initial_conditions", config.use_initial_conditions),
            )
        
        # 构建参数
        kwargs = {
            "step_time": config.step_time,
            "end_time": config.end_time,
        }
        
        if config.start_time > 0:
            kwargs["start_time"] = config.start_time
        
        if config.max_step is not None:
            kwargs["max_time"] = config.max_step
        
        if config.use_initial_conditions:
            kwargs["use_initial_condition"] = True
        
        # 执行瞬态分析
        analysis = simulator.transient(**kwargs)
        
        return analysis
    
    def _run_noise(
        self,
        simulator,
        analysis_config: Optional[Dict[str, Any]]
    ):
        """
        执行噪声分析
        
        Args:
            simulator: PySpice 仿真器
            analysis_config: 分析配置
            
        Returns:
            分析结果对象
        """
        config = NoiseConfig()
        if analysis_config:
            config = NoiseConfig(
                output_node=analysis_config.get("output_node", config.output_node),
                input_source=analysis_config.get("input_source", config.input_source),
                start_freq=analysis_config.get("start_freq", config.start_freq),
                stop_freq=analysis_config.get("stop_freq", config.stop_freq),
            )
        
        if not config.output_node or not config.input_source:
            raise ValueError("噪声分析需要指定 output_node 和 input_source")
        
        # 执行噪声分析
        analysis = simulator.noise(
            output=config.output_node,
            input_source=config.input_source,
            start_frequency=config.start_freq,
            stop_frequency=config.stop_freq,
            variation='dec',
            number_of_points=10,
        )
        
        return analysis
    
    def _run_op(
        self,
        simulator,
        analysis_config: Optional[Dict[str, Any]]
    ):
        """
        执行工作点分析
        
        Args:
            simulator: PySpice 仿真器
            analysis_config: 分析配置（OP 分析不需要额外配置）
            
        Returns:
            分析结果对象
        """
        # 执行工作点分析
        analysis = simulator.operating_point()
        return analysis
    
    def _extract_simulation_data(
        self,
        analysis_result,
        analysis_type: str
    ) -> SimulationData:
        """
        从 PySpice 分析结果中提取数据
        
        Args:
            analysis_result: PySpice 分析结果对象
            analysis_type: 分析类型
            
        Returns:
            SimulationData: 标准化的仿真数据
        """
        frequency = None
        time_data = None
        signals = {}
        
        try:
            if analysis_type == "ac":
                # AC 分析：提取频率和复数信号
                frequency = np.array(analysis_result.frequency)
                for node in analysis_result.nodes.values():
                    name = str(node)
                    # 存储幅度（dB）和相位
                    signals[f"{name}_mag"] = np.abs(np.array(node))
                    signals[f"{name}_phase"] = np.angle(np.array(node), deg=True)
                    signals[name] = np.array(node)  # 复数值
                    
            elif analysis_type == "dc":
                # DC 分析：提取扫描值和节点电压
                # DC 分析的 x 轴是扫描源的值
                for node in analysis_result.nodes.values():
                    name = str(node)
                    signals[name] = np.array(node)
                    
            elif analysis_type == "tran":
                # 瞬态分析：提取时间和信号
                time_data = np.array(analysis_result.time)
                for node in analysis_result.nodes.values():
                    name = str(node)
                    signals[name] = np.array(node)
                    
            elif analysis_type == "noise":
                # 噪声分析：提取频率和噪声谱密度
                frequency = np.array(analysis_result.frequency)
                for node in analysis_result.nodes.values():
                    name = str(node)
                    signals[name] = np.array(node)
                    
            elif analysis_type == "op":
                # 工作点分析：提取节点电压
                for node in analysis_result.nodes.values():
                    name = str(node)
                    signals[name] = np.array([float(node)])
                    
        except Exception as e:
            self._logger.warning(f"提取仿真数据时出现警告: {e}")
        
        return SimulationData(
            frequency=frequency,
            time=time_data,
            signals=signals,
        )
    
    def _parse_exception(
        self,
        exception: Exception,
        file_path: str
    ) -> SimulationError:
        """
        解析异常并转换为 SimulationError
        
        基于关键词匹配将 Python 异常分类为结构化的错误类型。
        在 PySpice 共享库模式下，错误信息来自 Python 异常而非原始 ngspice 输出。
        
        Args:
            exception: 捕获的异常
            file_path: 电路文件路径
            
        Returns:
            SimulationError: 结构化的错误信息，包含错误码、类型、严重级别、恢复建议
            
        错误分类规则：
            - 语法错误：匹配 "syntax"、"parse" 关键词
            - 模型缺失：匹配 "model"、"not found"、"unknown" 关键词
            - 节点浮空：匹配 "floating"、"no dc path" 关键词
            - 收敛失败：匹配 "convergence"、"no convergence" 关键词
            - 超时：匹配 "timeout" 关键词
            - 默认：NGSPICE_CRASH 类型
        """
        error_msg = str(exception)
        error_lower = error_msg.lower()
        
        # 提取行号（如果包含）
        line_number = self._extract_line_number(error_msg)
        
        # 根据错误消息判断错误类型
        if "syntax" in error_lower or "parse" in error_lower:
            return create_syntax_error(
                message=error_msg,
                file_path=file_path,
                line_number=line_number,
                recovery_suggestion="请检查网表文件语法是否正确",
            )
        
        if "convergence" in error_lower or "no convergence" in error_lower:
            is_dc = "dc" in error_lower or "operating point" in error_lower
            return create_convergence_error(
                message=error_msg,
                is_dc=is_dc,
                file_path=file_path,
            )
        
        if "timeout" in error_lower:
            return create_timeout_error(
                message=error_msg,
                file_path=file_path,
            )
        
        if "model" in error_lower and ("not found" in error_lower or "unknown" in error_lower):
            # 提取缺失的模型名称
            missing_models = self._extract_missing_models(error_msg)
            details = {"missing_models": missing_models} if missing_models else {}
            return SimulationError(
                code="E002",
                type=SimulationErrorType.MODEL_MISSING,
                severity=ErrorSeverity.HIGH,
                message=error_msg,
                file_path=file_path,
                details=details,
                recovery_suggestion="请检查模型文件路径或安装缺失的模型库",
            )
        
        if "floating" in error_lower or "no dc path" in error_lower:
            # 提取浮空节点名称
            floating_nodes = self._extract_floating_nodes(error_msg)
            details = {"floating_nodes": floating_nodes} if floating_nodes else {}
            return SimulationError(
                code="E003",
                type=SimulationErrorType.NODE_FLOATING,
                severity=ErrorSeverity.MEDIUM,
                message=error_msg,
                file_path=file_path,
                details=details,
                recovery_suggestion="请检查电路连接，确保所有节点都有到地的直流路径",
            )
        
        # 默认错误类型
        return SimulationError(
            code="E008",
            type=SimulationErrorType.NGSPICE_CRASH,
            severity=ErrorSeverity.HIGH,
            message=error_msg,
            file_path=file_path,
            recovery_suggestion="请检查电路文件和仿真配置",
        )
    
    def _extract_line_number(self, error_msg: str) -> Optional[int]:
        """
        从异常消息中提取行号
        
        支持的格式：
        - "line 15"
        - "Line: 15"
        - ":15:"
        - "at line 15"
        
        Args:
            error_msg: 错误消息
            
        Returns:
            Optional[int]: 行号，未找到返回 None
        """
        import re
        
        # 尝试多种行号格式
        patterns = [
            r'line\s*[:=]?\s*(\d+)',  # line 15, line: 15, line=15
            r'at\s+line\s+(\d+)',      # at line 15
            r':(\d+):',                 # :15:
            r'行\s*[:：]?\s*(\d+)',     # 行 15, 行: 15
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_msg, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        
        return None
    
    def _extract_missing_models(self, error_msg: str) -> List[str]:
        """
        从异常消息中提取缺失的模型名称
        
        支持的格式：
        - "model 'xxx' not found"
        - "unknown model xxx"
        - "model xxx is not defined"
        
        Args:
            error_msg: 错误消息
            
        Returns:
            List[str]: 缺失的模型名称列表
        """
        import re
        
        models = []
        
        # 尝试多种模型名称格式
        patterns = [
            r"model\s+['\"]?(\w+)['\"]?\s+(?:not found|is not defined|unknown)",
            r"unknown\s+model\s+['\"]?(\w+)['\"]?",
            r"model\s+['\"](\w+)['\"]",
            r"模型\s+['\"]?(\w+)['\"]?\s*(?:未找到|不存在)",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, error_msg, re.IGNORECASE)
            models.extend(matches)
        
        # 去重并保持顺序
        seen = set()
        unique_models = []
        for model in models:
            if model.lower() not in seen:
                seen.add(model.lower())
                unique_models.append(model)
        
        return unique_models
    
    def _extract_floating_nodes(self, error_msg: str) -> List[str]:
        """
        从异常消息中提取浮空节点名称
        
        支持的格式：
        - "node xxx is floating"
        - "floating node: xxx"
        - "no dc path to ground at node xxx"
        
        Args:
            error_msg: 错误消息
            
        Returns:
            List[str]: 浮空节点名称列表
        """
        import re
        
        nodes = []
        
        # 尝试多种节点名称格式
        patterns = [
            r"node\s+['\"]?(\w+)['\"]?\s+(?:is\s+)?floating",
            r"floating\s+node\s*[:=]?\s*['\"]?(\w+)['\"]?",
            r"no\s+dc\s+path\s+(?:to\s+ground\s+)?(?:at\s+)?node\s+['\"]?(\w+)['\"]?",
            r"节点\s+['\"]?(\w+)['\"]?\s*(?:浮空|悬空)",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, error_msg, re.IGNORECASE)
            nodes.extend(matches)
        
        # 去重并保持顺序
        seen = set()
        unique_nodes = []
        for node in nodes:
            if node.lower() not in seen:
                seen.add(node.lower())
                unique_nodes.append(node)
        
        return unique_nodes
    
    # ============================================================
    # 元器件模型集成（阶段十实现，此处预留接口）
    # ============================================================
    
    def check_required_models(self, circuit_file: str) -> List[str]:
        """
        检查电路所需的 SPICE 模型
        
        Args:
            circuit_file: 电路文件路径
            
        Returns:
            List[str]: 缺失的模型名称列表
            
        Note:
            此方法为阶段十预留接口，当前返回空列表
        """
        # TODO: 阶段十实现
        return []
    
    def _resolve_model_path(self, model_name: str) -> Optional[str]:
        """
        解析模型文件路径
        
        Args:
            model_name: 模型名称
            
        Returns:
            Optional[str]: 模型文件路径，未找到返回 None
            
        Note:
            此方法为阶段十预留接口，当前返回 None
        """
        # TODO: 阶段十实现
        return None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SpiceExecutor",
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_ANALYSES",
]
