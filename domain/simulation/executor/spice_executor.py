# SPICE Executor - PySpice Wrapper for Simulation Execution
"""
SPICE 仿真执行器

职责：
- 封装 PySpice 调用
- 执行各类 SPICE 分析
- 解析仿真结果
- 处理错误和超时

设计原则：
- 无状态：每次调用独立执行
- 错误隔离：PySpice 异常转换为自定义异常
- 资源安全：确保 ngspice 资源正确释放
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from infrastructure.utils.ngspice_config import (
    is_ngspice_available,
    get_ngspice_path,
    get_ngspice_models_path,
)
from ..models import AnalysisType, SimulationConfig

logger = logging.getLogger(__name__)


class SpiceExecutorError(Exception):
    """SPICE 执行器异常"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


class SpiceExecutor:
    """
    SPICE 仿真执行器
    
    封装 PySpice 调用，提供统一的仿真执行接口。
    
    使用示例：
        executor = SpiceExecutor()
        data = executor.run_analysis(
            circuit_path="/path/to/circuit.cir",
            config=SimulationConfig(analysis_type=AnalysisType.AC)
        )
    """
    
    def __init__(self):
        """初始化执行器"""
        self._ngspice_shared = None
        self._check_availability()
    
    def _check_availability(self) -> None:
        """检查 ngspice 是否可用"""
        if not is_ngspice_available():
            logger.warning("ngspice 不可用，仿真功能将受限")
    
    def run_analysis(
        self,
        circuit_path: str,
        config: SimulationConfig,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Dict[str, Any]:
        """
        执行仿真分析
        
        Args:
            circuit_path: 电路文件完整路径
            config: 仿真配置
            progress_callback: 进度回调 (progress: 0-1, message: str)
            
        Returns:
            Dict: 仿真数据
            {
                "vectors": {"frequency": [...], "v(out)": [...], ...},
                "analysis_type": "ac",
                "node_names": ["out", "in", ...],
            }
            
        Raises:
            SpiceExecutorError: 仿真执行失败
        """
        if not is_ngspice_available():
            raise SpiceExecutorError(
                "ngspice 不可用",
                {"reason": "ngspice 共享库未找到或配置失败"}
            )
        
        circuit_file = Path(circuit_path)
        if not circuit_file.exists():
            raise SpiceExecutorError(
                f"电路文件不存在: {circuit_path}",
                {"path": circuit_path}
            )
        
        if progress_callback:
            progress_callback(0.1, "加载电路文件...")
        
        try:
            # 延迟导入 PySpice
            from PySpice.Spice.NgSpice.Shared import NgSpiceShared
            from PySpice.Spice.Parser import SpiceParser
            import tempfile
            import shutil
            
            if progress_callback:
                progress_callback(0.2, "解析电路...")
            
            # 读取电路文件内容（使用 UTF-8 编码）
            circuit_content = circuit_file.read_text(encoding="utf-8")
            
            # 创建临时文件（PySpice 的 SpiceParser 使用 path 参数更可靠）
            # 使用 ASCII 兼容的内容（移除非 ASCII 注释）
            ascii_content = self._convert_to_ascii(circuit_content)
            
            temp_dir = tempfile.mkdtemp(prefix="pyspice_")
            temp_file = Path(temp_dir) / "circuit.cir"
            temp_file.write_text(ascii_content, encoding="ascii", errors="replace")
            
            try:
                parser = SpiceParser(path=str(temp_file))
                circuit = parser.build_circuit()
            finally:
                # 清理临时文件
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            # 设置温度
            circuit.parameter('temp', config.temperature)
            
            # 包含子电路/模型文件
            models_path = get_ngspice_models_path()
            for include_file in config.include_files:
                include_path = Path(include_file)
                if not include_path.is_absolute() and models_path:
                    include_path = models_path / include_file
                if include_path.exists():
                    circuit.include(str(include_path))
            
            if progress_callback:
                progress_callback(0.3, "创建仿真器...")
            
            # 创建仿真器
            simulator = circuit.simulator(
                temperature=config.temperature,
                nominal_temperature=27
            )
            
            # 设置 SPICE 选项
            for opt_name, opt_value in config.options.items():
                simulator.options(**{opt_name: opt_value})
            
            if progress_callback:
                progress_callback(0.4, "执行仿真...")
            
            # 执行分析
            analysis = self._execute_analysis(simulator, config)
            
            if progress_callback:
                progress_callback(0.8, "提取结果...")
            
            # 提取结果
            result = self._extract_results(analysis, config)
            
            if progress_callback:
                progress_callback(1.0, "完成")
            
            return result
            
        except ImportError as e:
            raise SpiceExecutorError(
                "PySpice 未安装",
                {"error": str(e)}
            )
        except Exception as e:
            logger.exception("仿真执行失败")
            raise SpiceExecutorError(
                f"仿真执行失败: {e}",
                {"error": str(e), "circuit": circuit_path}
            )
    
    def _execute_analysis(
        self,
        simulator: Any,
        config: SimulationConfig
    ) -> Any:
        """执行具体的分析类型"""
        params = config.get_merged_parameters()
        analysis_type = config.analysis_type
        
        if analysis_type == AnalysisType.OP:
            return simulator.operating_point()
        
        elif analysis_type == AnalysisType.DC:
            return simulator.dc(**{
                params.get("source", "Vin"): slice(
                    params.get("start", 0),
                    params.get("stop", 5),
                    params.get("step", 0.1)
                )
            })
        
        elif analysis_type == AnalysisType.AC:
            return simulator.ac(
                variation=params.get("variation", "dec"),
                number_of_points=params.get("points", 10),
                start_frequency=params.get("start_frequency", 1),
                stop_frequency=params.get("stop_frequency", 1e9),
            )
        
        elif analysis_type == AnalysisType.TRAN:
            return simulator.transient(
                step_time=params.get("step_time", 1e-6),
                end_time=params.get("end_time", 1e-3),
                start_time=params.get("start_time", 0),
                max_time=params.get("max_step"),
            )
        
        elif analysis_type == AnalysisType.NOISE:
            return simulator.noise(
                output=params.get("output", "out"),
                input_source=params.get("input_source", "Vin"),
                variation=params.get("variation", "dec"),
                number_of_points=params.get("points", 10),
                start_frequency=params.get("start_frequency", 1),
                stop_frequency=params.get("stop_frequency", 1e9),
            )
        
        elif analysis_type == AnalysisType.TF:
            return simulator.tf(
                params.get("output", "V(out)"),
                params.get("input_source", "Vin"),
            )
        
        elif analysis_type == AnalysisType.SENS:
            return simulator.sensitivity(
                params.get("output", "V(out)"),
            )
        
        else:
            raise SpiceExecutorError(f"不支持的分析类型: {analysis_type}")
    
    def _extract_results(
        self,
        analysis: Any,
        config: SimulationConfig
    ) -> Dict[str, Any]:
        """从分析结果中提取数据"""
        vectors: Dict[str, List[float]] = {}
        node_names: List[str] = []
        
        analysis_type = config.analysis_type
        
        # 提取自变量（频率/时间/电压）
        if analysis_type == AnalysisType.AC:
            if hasattr(analysis, 'frequency'):
                vectors["frequency"] = self._to_list(analysis.frequency)
        elif analysis_type == AnalysisType.TRAN:
            if hasattr(analysis, 'time'):
                vectors["time"] = self._to_list(analysis.time)
        elif analysis_type == AnalysisType.DC:
            # DC 扫描的自变量名称取决于扫描源
            pass
        
        # 提取节点电压
        if hasattr(analysis, 'nodes'):
            for node_name in analysis.nodes:
                node_names.append(str(node_name))
                node_data = analysis[node_name]
                
                # 转换为 numpy 数组（去除 PySpice 单位）
                node_array = np.array(node_data)
                
                # 处理复数数据（AC 分析）
                if np.iscomplexobj(node_array):
                    vectors[f"v({node_name})_mag"] = self._to_list(np.abs(node_array))
                    vectors[f"v({node_name})_phase"] = self._to_list(np.angle(node_array, deg=True))
                    vectors[f"v({node_name})_db"] = self._to_list(20 * np.log10(np.abs(node_array) + 1e-20))
                else:
                    vectors[f"v({node_name})"] = self._to_list(node_array)
        
        # 提取支路电流
        if hasattr(analysis, 'branches'):
            for branch_name in analysis.branches:
                branch_data = analysis[branch_name]
                branch_array = np.array(branch_data)
                if np.iscomplexobj(branch_array):
                    vectors[f"i({branch_name})_mag"] = self._to_list(np.abs(branch_array))
                else:
                    vectors[f"i({branch_name})"] = self._to_list(branch_array)
        
        return {
            "vectors": vectors,
            "analysis_type": analysis_type.value,
            "node_names": node_names,
        }
    
    def _to_list(self, data: Any) -> List[float]:
        """将 numpy 数组转换为 Python 列表"""
        if hasattr(data, 'tolist'):
            return data.tolist()
        elif hasattr(data, '__iter__'):
            return list(data)
        else:
            return [float(data)]
    
    def _convert_to_ascii(self, content: str) -> str:
        """
        将电路文件内容转换为 ASCII 兼容格式
        
        - 移除或替换非 ASCII 字符（主要是中文注释）
        - 移除 .CONTROL/.ENDC 块（PySpice 不支持）
        """
        lines = content.split('\n')
        ascii_lines = []
        in_control_block = False
        
        for line in lines:
            stripped = line.strip().upper()
            
            # 检测 .CONTROL 块开始
            if stripped.startswith('.CONTROL'):
                in_control_block = True
                continue
            
            # 检测 .CONTROL 块结束
            if stripped.startswith('.ENDC'):
                in_control_block = False
                continue
            
            # 跳过 .CONTROL 块内的内容
            if in_control_block:
                continue
            
            # 检查是否为注释行（以 * 开头）
            if line.strip().startswith('*'):
                # 尝试转换为 ASCII，非 ASCII 字符替换为 ?
                try:
                    line.encode('ascii')
                    ascii_lines.append(line)
                except UnicodeEncodeError:
                    # 包含非 ASCII 字符的注释行，替换为简单注释
                    ascii_lines.append('* [comment]')
            else:
                # 非注释行，保持原样（SPICE 语法应该是 ASCII）
                ascii_lines.append(line)
        
        return '\n'.join(ascii_lines)
    
    def get_circuit_info(self, circuit_path: str) -> Dict[str, Any]:
        """
        获取电路文件信息（不执行仿真）
        
        Args:
            circuit_path: 电路文件路径
            
        Returns:
            Dict: 电路信息
            {
                "title": "Circuit Title",
                "elements": [...],
                "subcircuits": [...],
                "analyses": [...]
            }
        """
        try:
            from PySpice.Spice.Parser import SpiceParser
            
            # 读取电路文件内容（使用 UTF-8 编码）
            circuit_content = Path(circuit_path).read_text(encoding="utf-8")
            
            parser = SpiceParser(source=circuit_content)
            circuit = parser.build_circuit()
            
            return {
                "title": circuit.title or "",
                "elements": [str(e) for e in circuit.elements],
                "subcircuits": list(circuit.subcircuits.keys()) if hasattr(circuit, 'subcircuits') else [],
                "node_count": len(circuit.nodes) if hasattr(circuit, 'nodes') else 0,
            }
            
        except Exception as e:
            logger.warning(f"获取电路信息失败: {e}")
            return {
                "title": "",
                "elements": [],
                "subcircuits": [],
                "node_count": 0,
                "error": str(e),
            }


__all__ = [
    "SpiceExecutor",
    "SpiceExecutorError",
]
