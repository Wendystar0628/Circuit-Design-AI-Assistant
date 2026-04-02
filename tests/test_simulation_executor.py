# Test Simulation Executor
"""
仿真执行器测试

测试内容：
- 抽象基类接口定义
- 文件类型判断
- 配置校验
- 执行器信息获取
"""

import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.simulation.executor.simulation_executor import (
    SimulationExecutor,
)
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
    create_success_result,
)


# ============================================================
# 测试用具体执行器实现
# ============================================================

class MockExecutor(SimulationExecutor):
    """测试用的模拟执行器"""
    
    def get_name(self) -> str:
        return "mock"
    
    def get_supported_extensions(self) -> List[str]:
        return [".cir", ".sp", ".spice"]
    
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        # 返回模拟的成功结果
        return create_success_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type=(analysis_config or {}).get("analysis_type", "ac"),
            data=SimulationData(),
            duration_seconds=1.0,
        )
    
    def get_available_analyses(self) -> List[str]:
        return ["ac", "dc", "tran"]


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def mock_executor():
    """创建模拟执行器实例"""
    return MockExecutor()


@pytest.fixture
def temp_circuit_file(tmp_path):
    """创建临时电路文件"""
    file_path = tmp_path / "test.cir"
    file_path.write_text("* Test circuit\nR1 1 0 1k\n.end\n")
    return str(file_path)


# ============================================================
# 测试执行器基本功能
# ============================================================

def test_executor_get_name(mock_executor):
    """测试获取执行器名称"""
    assert mock_executor.get_name() == "mock"


def test_executor_get_supported_extensions(mock_executor):
    """测试获取支持的扩展名"""
    extensions = mock_executor.get_supported_extensions()
    assert ".cir" in extensions
    assert ".sp" in extensions
    assert ".spice" in extensions


def test_executor_get_available_analyses(mock_executor):
    """测试获取支持的分析类型"""
    analyses = mock_executor.get_available_analyses()
    assert "ac" in analyses
    assert "dc" in analyses
    assert "tran" in analyses


# ============================================================
# 测试文件类型判断
# ============================================================

def test_can_handle_supported_file(mock_executor):
    """测试能处理支持的文件类型"""
    assert mock_executor.can_handle("test.cir") is True
    assert mock_executor.can_handle("test.sp") is True
    assert mock_executor.can_handle("test.spice") is True


def test_can_handle_unsupported_file(mock_executor):
    """测试不能处理不支持的文件类型"""
    assert mock_executor.can_handle("test.py") is False
    assert mock_executor.can_handle("test.txt") is False
    assert mock_executor.can_handle("test.json") is False


def test_can_handle_case_insensitive(mock_executor):
    """测试文件扩展名大小写不敏感"""
    assert mock_executor.can_handle("test.CIR") is True
    assert mock_executor.can_handle("test.Sp") is True
    assert mock_executor.can_handle("test.SPICE") is True


# ============================================================
# 测试文件校验
# ============================================================

def test_validate_existing_file(mock_executor, temp_circuit_file):
    """测试校验存在的文件"""
    valid, error = mock_executor.validate_file(temp_circuit_file)
    assert valid is True
    assert error is None


def test_validate_nonexistent_file(mock_executor):
    """测试校验不存在的文件"""
    valid, error = mock_executor.validate_file("nonexistent.cir")
    assert valid is False
    assert "文件不存在" in error


def test_validate_unsupported_extension(mock_executor, tmp_path):
    """测试校验不支持的文件扩展名"""
    file_path = tmp_path / "test.py"
    file_path.write_text("print('hello')")
    
    valid, error = mock_executor.validate_file(str(file_path))
    assert valid is False
    assert "不支持的文件类型" in error


def test_validate_directory(mock_executor, tmp_path):
    """测试校验目录（应失败）"""
    valid, error = mock_executor.validate_file(str(tmp_path))
    assert valid is False
    assert "路径不是文件" in error


# ============================================================
# 测试执行仿真
# ============================================================

def test_execute_with_default_config(mock_executor, temp_circuit_file):
    """测试使用默认配置执行仿真"""
    result = mock_executor.execute(temp_circuit_file)
    
    assert result.success is True
    assert result.executor == "mock"
    assert result.file_path == temp_circuit_file
    assert result.analysis_type == "ac"  # 默认分析类型


def test_execute_with_custom_config(mock_executor, temp_circuit_file):
    """测试使用自定义配置执行仿真"""
    config = {
        "analysis_type": "dc",
        "start_value": 0.0,
        "stop_value": 5.0,
    }
    
    result = mock_executor.execute(temp_circuit_file, config)
    
    assert result.success is True
    assert result.analysis_type == "dc"


# ============================================================
# 测试执行器信息
# ============================================================

def test_get_executor_info(mock_executor):
    """测试获取执行器信息"""
    info = mock_executor.get_executor_info()
    
    assert info["name"] == "mock"
    assert ".cir" in info["supported_extensions"]
    assert "ac" in info["available_analyses"]


def test_executor_str_representation(mock_executor):
    """测试执行器字符串表示"""
    str_repr = str(mock_executor)
    assert "MockExecutor" in str_repr
    assert "mock" in str_repr


def test_executor_repr(mock_executor):
    """测试执行器详细表示"""
    repr_str = repr(mock_executor)
    assert "MockExecutor" in repr_str
    assert "mock" in repr_str
    assert ".cir" in repr_str
    assert "ac" in repr_str


# ============================================================
# 测试抽象基类约束
# ============================================================

def test_cannot_instantiate_abstract_class():
    """测试不能直接实例化抽象基类"""
    with pytest.raises(TypeError):
        SimulationExecutor()


def test_subclass_must_implement_abstract_methods():
    """测试子类必须实现所有抽象方法"""
    
    class IncompleteExecutor(SimulationExecutor):
        def get_name(self) -> str:
            return "incomplete"
        
        # 缺少其他抽象方法的实现
    
    with pytest.raises(TypeError):
        IncompleteExecutor()


# ============================================================
# 集成测试
# ============================================================

def test_executor_workflow(mock_executor, temp_circuit_file):
    """测试完整的执行器工作流"""
    # 1. 检查是否能处理文件
    assert mock_executor.can_handle(temp_circuit_file) is True
    
    # 2. 校验文件
    valid, error = mock_executor.validate_file(temp_circuit_file)
    assert valid is True
    
    # 3. 执行仿真
    config = {"analysis_type": "ac"}
    result = mock_executor.execute(temp_circuit_file, config)
    
    # 4. 验证结果
    assert result.success is True
    assert result.executor == "mock"
    assert result.file_path == temp_circuit_file
    assert result.analysis_type == "ac"
