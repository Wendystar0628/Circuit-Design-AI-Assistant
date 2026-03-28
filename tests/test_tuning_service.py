# Test Tuning Service
"""
快速调参服务测试

测试内容：
- 参数应用到电路文件
- 文件备份和恢复
- 值格式化
"""

import pytest
import tempfile
from pathlib import Path

from domain.simulation.service.tuning_service import (
    TuningService,
    TuningApplyResult,
    tuning_service,
)
from domain.simulation.service.parameter_extractor import ParameterType


class TestTuningService:
    """TuningService 测试类"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return TuningService()
    
    @pytest.fixture
    def sample_circuit(self, tmp_path):
        """创建示例电路文件"""
        content = """\
* Sample Circuit for Testing
.param Rf = 10k
.param Cf = 100n

R1 in out 1k
R2 out gnd 2.2k
C1 out gnd 10u
Vin in gnd DC 5

.ac dec 100 1 1Meg
.end
"""
        file_path = tmp_path / "test_circuit.cir"
        file_path.write_text(content, encoding='utf-8')
        return str(file_path)
    
    def test_get_backup_path(self, service, tmp_path):
        """测试备份路径生成"""
        file_path = str(tmp_path / "circuit.cir")
        backup_path = service.get_backup_path(file_path, str(tmp_path))
        
        assert backup_path.name == "circuit.bak"
        # 使用 Path 的 parts 检查，避免路径分隔符问题
        assert ".circuit_ai" in backup_path.parts
        assert "temp" in backup_path.parts
    
    def test_apply_parameter_changes_param(self, service, sample_circuit, tmp_path):
        """测试 .param 参数修改"""
        changes = {"Rf": 20000.0}  # 20k
        
        result = service.apply_parameter_changes(
            sample_circuit, changes, str(tmp_path)
        )
        
        assert result.success
        assert len(result.modified_lines) == 1
        assert result.backup_path != ""
        assert "Rf" in result.changes_applied
        
        # 验证文件内容
        content = Path(sample_circuit).read_text()
        assert "20k" in content or "20000" in content
    
    def test_apply_parameter_changes_element(self, service, sample_circuit, tmp_path):
        """测试元件值修改"""
        changes = {"R1": 2000.0}  # 2k
        
        result = service.apply_parameter_changes(
            sample_circuit, changes, str(tmp_path)
        )
        
        assert result.success
        assert len(result.modified_lines) == 1
        
        content = Path(sample_circuit).read_text()
        assert "2k" in content or "2000" in content
    
    def test_apply_multiple_changes(self, service, sample_circuit, tmp_path):
        """测试多参数修改"""
        changes = {
            "Rf": 15000.0,
            "R1": 500.0,
            "C1": 22e-6,
        }
        
        result = service.apply_parameter_changes(
            sample_circuit, changes, str(tmp_path)
        )
        
        assert result.success
        assert len(result.modified_lines) == 3
        assert len(result.changes_applied) == 3
    
    def test_apply_empty_changes(self, service, sample_circuit, tmp_path):
        """测试空变更"""
        result = service.apply_parameter_changes(
            sample_circuit, {}, str(tmp_path)
        )
        
        assert result.success
        assert len(result.modified_lines) == 0
    
    def test_apply_nonexistent_param(self, service, sample_circuit, tmp_path):
        """测试不存在的参数"""
        changes = {"NonExistent": 100.0}
        
        result = service.apply_parameter_changes(
            sample_circuit, changes, str(tmp_path)
        )
        
        assert result.success  # 不存在的参数被跳过，不算失败
        assert len(result.modified_lines) == 0
    
    def test_apply_file_not_found(self, service, tmp_path):
        """测试文件不存在"""
        result = service.apply_parameter_changes(
            str(tmp_path / "nonexistent.cir"),
            {"R1": 100.0},
            str(tmp_path)
        )
        
        assert not result.success
        assert "不存在" in result.error_message
    
    def test_restore_original(self, service, sample_circuit, tmp_path):
        """测试恢复原始文件"""
        # 先读取原始内容
        original_content = Path(sample_circuit).read_text()
        
        # 应用修改
        changes = {"Rf": 99999.0}
        service.apply_parameter_changes(sample_circuit, changes, str(tmp_path))
        
        # 验证已修改
        modified_content = Path(sample_circuit).read_text()
        assert modified_content != original_content
        
        # 恢复
        success = service.restore_original(sample_circuit, str(tmp_path))
        assert success
        
        # 验证已恢复
        restored_content = Path(sample_circuit).read_text()
        assert restored_content == original_content
    
    def test_restore_no_backup(self, service, sample_circuit, tmp_path):
        """测试无备份时恢复"""
        success = service.restore_original(sample_circuit, str(tmp_path))
        assert not success


class TestValueFormatting:
    """值格式化测试"""
    
    @pytest.fixture
    def service(self):
        return TuningService()
    
    @pytest.mark.parametrize("value,expected_contains", [
        (0, "0"),
        (1000, "1k"),
        (1e6, "1Meg"),
        (1e9, "1G"),
        (0.001, "1m"),
        (1e-6, "1u"),
        (1e-9, "1n"),
        (1e-12, "1p"),
        (2.2e3, "2.2k"),
        (4.7e-6, "4.7u"),
    ])
    def test_format_value(self, service, value, expected_contains):
        """测试值格式化"""
        formatted = service._format_value(value)
        assert expected_contains in formatted


class TestModuleSingleton:
    """模块单例测试"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert tuning_service is not None
        assert isinstance(tuning_service, TuningService)
