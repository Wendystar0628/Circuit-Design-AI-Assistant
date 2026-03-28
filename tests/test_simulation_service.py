# Test Simulation Service
"""
仿真服务测试

测试内容：
- SimulationService 类的核心功能
- 文件扫描和主电路检测
- 仿真结果的保存和加载
- 事件发布
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from domain.services.simulation_service import (
    SimulationService,
    SIM_RESULTS_DIR,
)
from domain.simulation.executor.executor_registry import ExecutorRegistry
from domain.simulation.executor.circuit_analyzer import CircuitAnalyzer, ScanResult
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
    create_success_result,
    create_error_result,
)
from domain.simulation.models.simulation_error import (
    SimulationError,
    SimulationErrorType,
    ErrorSeverity,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def temp_project():
    """创建临时项目目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # 创建 .circuit_ai 目录
        (project_root / ".circuit_ai").mkdir()
        (project_root / ".circuit_ai" / "sim_results").mkdir()
        
        # 创建测试电路文件
        circuit_content = """* Test Circuit
Vin in 0 DC 1V AC 1V
R1 in out 1k
C1 out 0 1u
.ac dec 10 1 1Meg
.end
"""
        (project_root / "test_circuit.cir").write_text(circuit_content)
        
        # 创建子电路文件
        subcircuit_content = """* Subcircuit
.subckt opamp in+ in- out vcc vee
* ...
.ends opamp
"""
        (project_root / "subcircuits").mkdir()
        (project_root / "subcircuits" / "opamp.cir").write_text(subcircuit_content)
        
        yield project_root


@pytest.fixture
def mock_registry():
    """创建模拟的执行器注册表"""
    registry = MagicMock(spec=ExecutorRegistry)
    registry.get_all_supported_extensions.return_value = [".cir", ".sp", ".spice"]
    return registry


@pytest.fixture
def mock_executor():
    """创建模拟的执行器"""
    executor = MagicMock()
    executor.get_name.return_value = "spice"
    executor.execute.return_value = create_success_result(
        executor="spice",
        file_path="test.cir",
        analysis_type="ac",
        data=SimulationData(signals={"V(out)": [1.0, 2.0, 3.0]}),
    )
    return executor


# ============================================================
# SimulationService 测试
# ============================================================

class TestSimulationService:
    """SimulationService 类测试"""
    
    def test_init_default(self):
        """测试默认初始化"""
        service = SimulationService()
        assert service._registry is not None
        assert service._analyzer is not None
        assert not service._is_running
    
    def test_init_with_registry(self, mock_registry):
        """测试带注册表初始化"""
        service = SimulationService(registry=mock_registry)
        assert service._registry is mock_registry
    
    def test_is_running(self):
        """测试运行状态检查"""
        service = SimulationService()
        assert not service.is_running()
    
    def test_get_last_simulation_file(self):
        """测试获取上次仿真文件"""
        service = SimulationService()
        assert service.get_last_simulation_file() is None


class TestSimulationServiceScan:
    """文件扫描测试"""
    
    def test_get_simulatable_files(self, temp_project, mock_registry):
        """测试获取可仿真文件列表"""
        service = SimulationService(registry=mock_registry)
        files = service.get_simulatable_files(str(temp_project))
        
        # 应该找到至少一个文件
        assert len(files) >= 1
    
    def test_get_main_circuit_candidates(self, temp_project, mock_registry):
        """测试获取主电路候选"""
        service = SimulationService(registry=mock_registry)
        candidates = service.get_main_circuit_candidates(str(temp_project))
        
        # test_circuit.cir 包含 .ac 语句，应该是主电路候选
        assert len(candidates) >= 1
    
    def test_scan_project(self, temp_project, mock_registry):
        """测试扫描项目"""
        service = SimulationService(registry=mock_registry)
        result = service.scan_project(str(temp_project))
        
        assert isinstance(result, ScanResult)
        assert len(result.files) >= 1


class TestSimulationServiceRun:
    """仿真执行测试"""
    
    def test_run_simulation_no_executor(self, temp_project):
        """测试没有执行器时的错误处理"""
        # 创建空的注册表
        registry = ExecutorRegistry()
        service = SimulationService(registry=registry)
        
        result = service.run_simulation(
            file_path=str(temp_project / "test_circuit.cir"),
            analysis_config={"analysis_type": "ac"},
        )
        
        assert not result.success
        assert result.error is not None
    
    def test_run_simulation_with_mock_executor(self, temp_project, mock_registry, mock_executor):
        """测试使用模拟执行器"""
        mock_registry.get_executor_for_file.return_value = mock_executor
        
        service = SimulationService(registry=mock_registry)
        result = service.run_simulation(
            file_path=str(temp_project / "test_circuit.cir"),
            analysis_config={"analysis_type": "ac"},
            project_root=str(temp_project),
        )
        
        assert result.success
        mock_executor.execute.assert_called_once()


class TestSimulationServiceResults:
    """仿真结果管理测试"""
    
    def test_save_and_load_result(self, temp_project):
        """测试保存和加载仿真结果"""
        service = SimulationService()
        
        # 创建测试结果
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(signals={"V(out)": [1.0, 2.0, 3.0]}),
        )
        
        # 保存
        result_path = service.save_sim_result(str(temp_project), result)
        assert result_path.startswith(SIM_RESULTS_DIR)
        
        # 加载
        load_result = service.load_sim_result(str(temp_project), result_path)
        assert load_result.success
        assert load_result.data is not None
        assert load_result.data.executor == "spice"
    
    def test_list_sim_results(self, temp_project):
        """测试列出仿真结果"""
        service = SimulationService()
        
        # 保存几个结果
        for i in range(3):
            result = create_success_result(
                executor="spice",
                file_path=f"test_{i}.cir",
                analysis_type="ac",
                data=SimulationData(),
            )
            service.save_sim_result(str(temp_project), result)
        
        # 列出
        results = service.list_sim_results(str(temp_project), limit=10)
        assert len(results) == 3
    
    def test_delete_sim_result(self, temp_project):
        """测试删除仿真结果"""
        service = SimulationService()
        
        # 保存
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
        )
        result_path = service.save_sim_result(str(temp_project), result)
        
        # 删除
        success = service.delete_sim_result(str(temp_project), result_path)
        assert success
        
        # 验证已删除
        load_result = service.load_sim_result(str(temp_project), result_path)
        assert not load_result.success
    
    def test_get_latest_sim_result(self, temp_project):
        """测试获取最新仿真结果"""
        service = SimulationService()
        
        # 保存
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="ac",
            data=SimulationData(),
        )
        service.save_sim_result(str(temp_project), result)
        
        # 获取最新
        load_result = service.get_latest_sim_result(str(temp_project))
        assert load_result.success


# ============================================================
# ScanResult 测试
# ============================================================

class TestScanResult:
    """ScanResult 数据类测试"""
    
    def test_has_single_main_circuit(self):
        """测试单一主电路判断"""
        result = ScanResult(
            files=[Path("a.cir"), Path("b.cir")],
            main_circuit_candidates=[Path("a.cir")],
        )
        assert result.has_single_main_circuit()
        assert not result.has_multiple_candidates()
        assert not result.has_no_candidates()
    
    def test_has_multiple_candidates(self):
        """测试多候选判断"""
        result = ScanResult(
            files=[Path("a.cir"), Path("b.cir")],
            main_circuit_candidates=[Path("a.cir"), Path("b.cir")],
        )
        assert not result.has_single_main_circuit()
        assert result.has_multiple_candidates()
        assert not result.has_no_candidates()
    
    def test_has_no_candidates(self):
        """测试无候选判断"""
        result = ScanResult(
            files=[Path("a.cir")],
            main_circuit_candidates=[],
        )
        assert not result.has_single_main_circuit()
        assert not result.has_multiple_candidates()
        assert result.has_no_candidates()


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
