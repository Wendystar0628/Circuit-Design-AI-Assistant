# test_spice_executor.py - SPICE 执行器单元测试
"""
SpiceExecutor 单元测试

测试内容：
- 执行器基本属性
- 文件校验
- 仿真执行（需要 ngspice 可用）
- 错误处理
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# 在导入 SpiceExecutor 之前配置 ngspice
from infrastructure.utils.ngspice_config import configure_ngspice
configure_ngspice()

from domain.simulation.executor.spice_executor import (
    SpiceExecutor,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_ANALYSES,
)
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.models.simulation_error import SimulationErrorType


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def executor():
    """创建 SpiceExecutor 实例"""
    return SpiceExecutor()


@pytest.fixture
def temp_circuit_file():
    """创建临时电路文件"""
    content = """* 简单 RC 电路
R1 in out 1k
C1 out 0 1u
Vin in 0 AC 1
.ac dec 10 1 1meg
.end
"""
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.cir',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write(content)
        temp_path = f.name
    
    yield temp_path
    
    # 清理
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def invalid_circuit_file():
    """创建无效的电路文件"""
    content = """* 无效电路
这不是有效的 SPICE 语法
.end
"""
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.cir',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write(content)
        temp_path = f.name
    
    yield temp_path
    
    # 清理
    Path(temp_path).unlink(missing_ok=True)


# ============================================================
# 基本属性测试
# ============================================================

class TestSpiceExecutorBasic:
    """SpiceExecutor 基本属性测试"""
    
    def test_get_name(self, executor):
        """测试执行器名称"""
        assert executor.get_name() == "spice"
    
    def test_get_supported_extensions(self, executor):
        """测试支持的扩展名"""
        extensions = executor.get_supported_extensions()
        assert isinstance(extensions, list)
        assert ".cir" in extensions
        assert ".sp" in extensions
        assert ".spice" in extensions
        assert ".net" in extensions
        assert ".ckt" in extensions
    
    def test_get_available_analyses(self, executor):
        """测试支持的分析类型"""
        analyses = executor.get_available_analyses()
        assert isinstance(analyses, list)
        assert "ac" in analyses
        assert "dc" in analyses
        assert "tran" in analyses
        assert "noise" in analyses
        assert "op" in analyses
    
    def test_can_handle_cir_file(self, executor):
        """测试 .cir 文件处理能力"""
        assert executor.can_handle("test.cir") is True
        assert executor.can_handle("path/to/circuit.cir") is True
    
    def test_can_handle_sp_file(self, executor):
        """测试 .sp 文件处理能力"""
        assert executor.can_handle("test.sp") is True
    
    def test_cannot_handle_py_file(self, executor):
        """测试不支持 .py 文件"""
        assert executor.can_handle("test.py") is False
    
    def test_cannot_handle_txt_file(self, executor):
        """测试不支持 .txt 文件"""
        assert executor.can_handle("test.txt") is False
    
    def test_executor_info(self, executor):
        """测试执行器信息"""
        info = executor.get_executor_info()
        assert info["name"] == "spice"
        assert ".cir" in info["supported_extensions"]
        assert "ac" in info["available_analyses"]


# ============================================================
# 文件校验测试
# ============================================================

class TestSpiceExecutorValidation:
    """SpiceExecutor 文件校验测试"""
    
    def test_validate_existing_file(self, executor, temp_circuit_file):
        """测试校验存在的文件"""
        valid, error = executor.validate_file(temp_circuit_file)
        assert valid is True
        assert error is None
    
    def test_validate_nonexistent_file(self, executor):
        """测试校验不存在的文件"""
        valid, error = executor.validate_file("nonexistent.cir")
        assert valid is False
        assert "不存在" in error
    
    def test_validate_wrong_extension(self, executor):
        """测试校验错误扩展名的文件"""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            temp_path = f.name
        
        try:
            valid, error = executor.validate_file(temp_path)
            assert valid is False
            assert "不支持" in error
        finally:
            Path(temp_path).unlink(missing_ok=True)


# ============================================================
# ngspice 可用性测试
# ============================================================

class TestSpiceExecutorAvailability:
    """SpiceExecutor ngspice 可用性测试"""
    
    def test_is_available_returns_bool(self, executor):
        """测试 is_available 返回布尔值"""
        result = executor.is_available()
        assert isinstance(result, bool)
    
    def test_get_ngspice_info_returns_dict(self, executor):
        """测试 get_ngspice_info 返回字典"""
        info = executor.get_ngspice_info()
        assert isinstance(info, dict)
        assert "configured" in info
        assert "available" in info
        assert "platform" in info


# ============================================================
# 仿真执行测试（模拟模式）
# ============================================================

class TestSpiceExecutorExecution:
    """SpiceExecutor 仿真执行测试"""
    
    def test_execute_returns_simulation_result(self, executor, temp_circuit_file):
        """测试执行返回 SimulationResult"""
        result = executor.execute(temp_circuit_file)
        assert isinstance(result, SimulationResult)
        assert result.executor == "spice"
        assert result.file_path == temp_circuit_file
    
    def test_execute_with_nonexistent_file(self, executor):
        """测试执行不存在的文件"""
        result = executor.execute("nonexistent.cir")
        assert result.success is False
        assert result.error is not None
        assert result.error.type == SimulationErrorType.FILE_ACCESS
    
    @patch('domain.simulation.executor.spice_executor.is_ngspice_available')
    def test_execute_when_ngspice_unavailable(self, mock_available, executor, temp_circuit_file):
        """测试 ngspice 不可用时的执行"""
        mock_available.return_value = False
        
        result = executor.execute(temp_circuit_file)
        assert result.success is False
        assert result.error is not None
        assert result.error.type == SimulationErrorType.NGSPICE_CRASH
    
    def test_execute_with_analysis_config(self, executor, temp_circuit_file):
        """测试带配置的执行"""
        config = {
            "analysis_type": "ac",
            "start_freq": 1.0,
            "stop_freq": 1e6,
            "points_per_decade": 10,
        }
        result = executor.execute(temp_circuit_file, config)
        assert isinstance(result, SimulationResult)
        assert result.analysis_type == "ac"


# ============================================================
# 分析方法测试
# ============================================================

class TestSpiceExecutorAnalysisMethods:
    """SpiceExecutor 分析方法测试"""
    
    def test_run_ac_analysis(self, executor, temp_circuit_file):
        """测试 AC 分析方法"""
        result = executor.run_ac_analysis(
            temp_circuit_file,
            start_freq=1.0,
            stop_freq=1e6,
            points_per_decade=10,
        )
        assert isinstance(result, SimulationResult)
        assert result.analysis_type == "ac"
    
    def test_run_dc_analysis(self, executor, temp_circuit_file):
        """测试 DC 分析方法"""
        result = executor.run_dc_analysis(
            temp_circuit_file,
            source_name="Vin",
            start_value=0.0,
            stop_value=5.0,
            step=0.1,
        )
        assert isinstance(result, SimulationResult)
        assert result.analysis_type == "dc"
    
    def test_run_transient_analysis(self, executor, temp_circuit_file):
        """测试瞬态分析方法"""
        result = executor.run_transient_analysis(
            temp_circuit_file,
            step_time=1e-6,
            end_time=1e-3,
        )
        assert isinstance(result, SimulationResult)
        assert result.analysis_type == "tran"
    
    def test_run_noise_analysis(self, executor, temp_circuit_file):
        """测试噪声分析方法"""
        result = executor.run_noise_analysis(
            temp_circuit_file,
            output_node="out",
            input_source="Vin",
            start_freq=1.0,
            stop_freq=1e6,
        )
        assert isinstance(result, SimulationResult)
        assert result.analysis_type == "noise"


# ============================================================
# 错误处理测试
# ============================================================

class TestSpiceExecutorErrorHandling:
    """SpiceExecutor 错误处理测试"""
    
    def test_parse_syntax_error(self, executor):
        """测试语法错误解析"""
        error = executor._parse_exception(
            Exception("Syntax error on line 5"),
            "test.cir"
        )
        assert error.type == SimulationErrorType.SYNTAX_ERROR
    
    def test_parse_convergence_error(self, executor):
        """测试收敛错误解析"""
        error = executor._parse_exception(
            Exception("No convergence in DC analysis"),
            "test.cir"
        )
        assert error.type == SimulationErrorType.CONVERGENCE_DC
    
    def test_parse_model_missing_error(self, executor):
        """测试模型缺失错误解析"""
        error = executor._parse_exception(
            Exception("Model 'NPN2222' not found"),
            "test.cir"
        )
        assert error.type == SimulationErrorType.MODEL_MISSING
    
    def test_parse_floating_node_error(self, executor):
        """测试浮空节点错误解析"""
        error = executor._parse_exception(
            Exception("Node 'out' is floating"),
            "test.cir"
        )
        assert error.type == SimulationErrorType.NODE_FLOATING
    
    def test_parse_unknown_error(self, executor):
        """测试未知错误解析"""
        error = executor._parse_exception(
            Exception("Some unknown error"),
            "test.cir"
        )
        assert error.type == SimulationErrorType.NGSPICE_CRASH

    def test_parse_ngspice_output_detached_state_as_crash(self, executor):
        """测试仅有 detached 错误时识别为 ngspice 崩溃"""
        error = executor._parse_ngspice_output(
            "stderr Error: ngspice.dll cannot recover and awaits to be detached",
            "test.cir"
        )
        assert error.type == SimulationErrorType.NGSPICE_CRASH

    def test_parse_ngspice_output_preserves_specific_root_cause_over_detached(self, executor):
        """测试更具体的根因不会被 detached 错误覆盖"""
        error = executor._parse_ngspice_output(
            "Error: unknown subckt: ideal_opamp\n"
            "stderr Error: ngspice.dll cannot recover and awaits to be detached",
            "test.cir"
        )
        assert error.type == SimulationErrorType.MODEL_MISSING
        assert "ideal_opamp" in error.message


# ============================================================
# 预留接口测试
# ============================================================

class TestSpiceExecutorReservedInterfaces:
    """SpiceExecutor 预留接口测试"""
    
    def test_check_required_models(self, executor, temp_circuit_file):
        """测试检查所需模型（预留接口）"""
        missing = executor.check_required_models(temp_circuit_file)
        assert isinstance(missing, list)
        # 当前实现返回空列表
        assert len(missing) == 0
    
    def test_resolve_model_path(self, executor):
        """测试解析模型路径（预留接口）"""
        path = executor._resolve_model_path("NPN2222")
        # 当前实现返回 None
        assert path is None


# ============================================================
# 工作目录切换测试
# ============================================================

class TestSpiceExecutorWorkingDirectory:
    """SpiceExecutor 工作目录切换测试"""
    
    def test_execute_with_working_directory_switch(self, executor):
        """测试执行时工作目录切换"""
        import os
        
        # 创建临时目录和文件
        with tempfile.TemporaryDirectory() as temp_dir:
            circuit_path = Path(temp_dir) / "test.cir"
            circuit_path.write_text("""* 简单电路
R1 in out 1k
Vin in 0 DC 1
.op
.end
""", encoding='utf-8')
            
            original_dir = os.getcwd()
            
            # 执行仿真
            result = executor.execute(str(circuit_path))
            
            # 验证工作目录已恢复
            assert os.getcwd() == original_dir
            
            # 验证返回了结果（无论成功与否）
            assert isinstance(result, SimulationResult)
    
    def test_working_directory_restored_on_error(self, executor):
        """测试错误时工作目录也能恢复"""
        import os
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建一个会导致解析错误的文件
            circuit_path = Path(temp_dir) / "invalid.cir"
            circuit_path.write_text("这不是有效的SPICE语法", encoding='utf-8')
            
            original_dir = os.getcwd()
            
            # 执行仿真（预期会失败）
            result = executor.execute(str(circuit_path))
            
            # 验证工作目录已恢复
            assert os.getcwd() == original_dir
            
            # 验证返回了错误结果
            assert isinstance(result, SimulationResult)
    
    def test_execute_with_include_relative_path(self, executor):
        """测试包含相对路径引用的电路文件"""
        import os
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建子目录和子电路文件
            subcircuits_dir = Path(temp_dir) / "subcircuits"
            subcircuits_dir.mkdir()
            
            subcircuit_path = subcircuits_dir / "resistor.sub"
            subcircuit_path.write_text("""* 电阻子电路
.subckt myres in out
R1 in out 1k
.ends myres
""", encoding='utf-8')
            
            # 创建主电路文件，使用相对路径引用子电路
            main_circuit_path = Path(temp_dir) / "main.cir"
            main_circuit_path.write_text("""* 主电路
.include subcircuits/resistor.sub
X1 in out myres
Vin in 0 DC 1
.op
.end
""", encoding='utf-8')
            
            original_dir = os.getcwd()
            
            # 执行仿真
            result = executor.execute(str(main_circuit_path))
            
            # 验证工作目录已恢复
            assert os.getcwd() == original_dir
            
            # 验证返回了结果
            assert isinstance(result, SimulationResult)


# ============================================================
# 集成测试（需要 ngspice 可用）
# ============================================================

@pytest.mark.skipif(
    not SpiceExecutor().is_available(),
    reason="ngspice 不可用，跳过集成测试"
)
class TestSpiceExecutorIntegration:
    """SpiceExecutor 集成测试（需要 ngspice）"""
    
    def test_execute_simple_rc_circuit(self, executor, temp_circuit_file):
        """测试执行简单 RC 电路"""
        result = executor.execute(temp_circuit_file)
        
        # 如果 ngspice 可用，应该能成功执行
        if result.success:
            assert result.data is not None
            assert result.duration_seconds > 0
        else:
            # 即使失败，也应该有错误信息
            assert result.error is not None
