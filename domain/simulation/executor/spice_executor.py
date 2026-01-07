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
        max_step: Optional[float] = None
    ) -> SimulationResult:
        """执行瞬态分析"""
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
        """执行噪声分析"""
        config = {
            "analysis_type": "noise",
            "output_node": output_node,
            "input_source": input_source,
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
        """从配置中提取分析类型"""
        if analysis_config is None:
            return "ac"
        return analysis_config.get("analysis_type", "ac")
    
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
        
        # 生成分析命令
        analysis_command = self._generate_analysis_command(analysis_type, analysis_config)
        
        # 注入分析命令到网表
        modified_netlist = self._inject_analysis_command(netlist_content, analysis_command)
        
        # 加载网表
        netlist_lines = modified_netlist.splitlines()
        if not self._ngspice.load_netlist(netlist_lines):
            stdout = self._ngspice.get_stdout()
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=self._parse_ngspice_output(stdout, file_path),
                raw_output=stdout,
            )
        
        # 执行仿真
        if not self._ngspice.run():
            stdout = self._ngspice.get_stdout()
            return create_error_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                error=self._parse_ngspice_output(stdout, file_path),
                raw_output=stdout,
            )
        
        # 提取仿真数据
        sim_data = self._extract_simulation_data(analysis_type)
        raw_output = self._ngspice.get_stdout()
        
        return create_success_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=analysis_type,
            data=sim_data,
            raw_output=raw_output,
        )
    
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
                )
            cmd = f".tran {config.step_time} {config.end_time}"
            if config.start_time > 0:
                cmd += f" {config.start_time}"
            if config.max_step:
                cmd += f" {config.max_step}"
            return cmd
        
        elif analysis_type == "noise":
            config = NoiseConfig()
            if analysis_config:
                config = NoiseConfig(
                    output_node=analysis_config.get("output_node", config.output_node),
                    input_source=analysis_config.get("input_source", config.input_source),
                    start_freq=analysis_config.get("start_freq", config.start_freq),
                    stop_freq=analysis_config.get("stop_freq", config.stop_freq),
                )
            if not config.output_node or not config.input_source:
                return ""
            return f".noise v({config.output_node}) {config.input_source} dec 10 {config.start_freq} {config.stop_freq}"
        
        elif analysis_type == "op":
            return ".op"
        
        return ""
    
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
            if stripped.startswith(analysis_type):
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

    def _extract_simulation_data(self, analysis_type: str) -> SimulationData:
        """从 ngspice 提取仿真数据"""
        frequency = None
        time_data = None
        signals = {}
        
        # 获取所有向量
        vectors = self._ngspice.get_all_vectors()
        self._logger.debug(f"可用向量: {vectors}")
        
        for vec_name in vectors:
            vec_info = self._ngspice.get_vector_info(vec_name)
            if not vec_info:
                continue
            
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
                    signals[f"{vec_name}_mag"] = np.abs(vec_info.cdata)
                    signals[f"{vec_name}_phase"] = np.angle(vec_info.cdata, deg=True)
                    signals[f"{vec_name}_real"] = np.real(vec_info.cdata)
                    signals[f"{vec_name}_imag"] = np.imag(vec_info.cdata)
                elif vec_info.data is not None and len(vec_info.data) > 0:
                    # 实数数据
                    signals[vec_name] = vec_info.data
        
        return SimulationData(
            frequency=frequency,
            time=time_data,
            signals=signals,
        )
    
    def _parse_ngspice_output(
        self,
        output: str,
        file_path: str
    ) -> SimulationError:
        """解析 ngspice 输出，提取错误信息"""
        output_lower = output.lower()
        
        # 语法错误
        if "syntax" in output_lower or "parse" in output_lower or "error:" in output_lower:
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
