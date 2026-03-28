# Test SimulationConfigService
"""
仿真配置服务测试

测试内容：
- 配置加载和保存
- 配置校验
- 默认配置
- 配置重置
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from domain.simulation.service.simulation_config_service import (
    SimulationConfigService,
    FullSimulationConfig,
    ValidationResult,
    ValidationError,
    CONFIG_FILE_NAME,
    CONFIG_DIR,
)
from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    DCAnalysisConfig,
    TransientConfig,
    NoiseConfig,
    GlobalSimulationConfig,
    ConvergenceConfig,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def service():
    """创建服务实例"""
    return SimulationConfigService()


@pytest.fixture
def temp_project(tmp_path):
    """创建临时项目目录"""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return str(project_dir)


@pytest.fixture
def config_with_values():
    """创建带自定义值的配置"""
    return FullSimulationConfig(
        global_config=GlobalSimulationConfig(
            timeout_seconds=600,
            temperature=25.0,
            convergence=ConvergenceConfig(
                gmin=1e-11,
                abstol=1e-11,
                reltol=1e-4,
            ),
        ),
        ac=ACAnalysisConfig(
            start_freq=10.0,
            stop_freq=1e8,
            points_per_decade=30,
        ),
        dc=DCAnalysisConfig(
            source_name="Vin",
            start_value=-5.0,
            stop_value=5.0,
            step=0.05,
        ),
        transient=TransientConfig(
            step_time=1e-7,
            end_time=1e-2,
        ),
        noise=NoiseConfig(
            output_node="out",
            input_source="Vin",
            start_freq=10.0,
            stop_freq=1e7,
        ),
    )


# ============================================================
# 配置加载测试
# ============================================================

class TestLoadConfig:
    """配置加载测试"""
    
    def test_load_default_when_file_not_exists(self, service, temp_project):
        """文件不存在时返回默认配置"""
        config = service.load_config(temp_project)
        
        assert config.version == "1.0"
        assert config.global_config.timeout_seconds == 300
        assert config.global_config.temperature == 27.0
        assert config.ac.start_freq == 1.0
        assert config.ac.stop_freq == 1e9
    
    def test_load_existing_config(self, service, temp_project, config_with_values):
        """加载已存在的配置文件"""
        # 先保存配置
        service.save_config(temp_project, config_with_values, publish_event=False)
        
        # 再加载
        loaded = service.load_config(temp_project)
        
        assert loaded.global_config.timeout_seconds == 600
        assert loaded.global_config.temperature == 25.0
        assert loaded.ac.start_freq == 10.0
        assert loaded.dc.source_name == "Vin"
    
    def test_load_invalid_json_returns_default(self, service, temp_project):
        """JSON 解析失败时返回默认配置"""
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("invalid json {", encoding="utf-8")
        
        config = service.load_config(temp_project)
        
        # 应返回默认配置
        assert config.global_config.timeout_seconds == 300


# ============================================================
# 配置保存测试
# ============================================================

class TestSaveConfig:
    """配置保存测试"""
    
    def test_save_creates_directory(self, service, temp_project):
        """保存时自动创建目录"""
        config = FullSimulationConfig.get_default()
        
        result = service.save_config(temp_project, config, publish_event=False)
        
        assert result is True
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        assert config_path.exists()
    
    def test_save_writes_correct_content(self, service, temp_project, config_with_values):
        """保存内容正确"""
        service.save_config(temp_project, config_with_values, publish_event=False)
        
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        content = json.loads(config_path.read_text(encoding="utf-8"))
        
        assert content["global"]["timeout_seconds"] == 600
        assert content["ac"]["start_freq"] == 10.0
        assert content["dc"]["source_name"] == "Vin"
    
    def test_save_publishes_event(self, temp_project):
        """保存时发布事件"""
        mock_bus = MagicMock()
        service = SimulationConfigService(event_bus=mock_bus)
        config = FullSimulationConfig.get_default()
        
        service.save_config(temp_project, config, publish_event=True)
        
        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "sim_config_changed"


# ============================================================
# 配置校验测试
# ============================================================

class TestValidateConfig:
    """配置校验测试"""
    
    def test_valid_default_config(self, service):
        """默认配置应通过校验"""
        config = FullSimulationConfig.get_default()
        
        result = service.validate_config(config)
        
        assert result.is_valid is True
        assert len(result.errors) == 0
    
    def test_invalid_ac_start_freq(self, service):
        """AC 起始频率为负数"""
        config = FullSimulationConfig(
            ac=ACAnalysisConfig(start_freq=-1.0),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "ac.start_freq" for e in result.errors)
    
    def test_invalid_ac_stop_freq(self, service):
        """AC 终止频率小于起始频率"""
        config = FullSimulationConfig(
            ac=ACAnalysisConfig(start_freq=1e6, stop_freq=1e3),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "ac.stop_freq" for e in result.errors)
    
    def test_invalid_sweep_type(self, service):
        """无效的扫描类型"""
        config = FullSimulationConfig(
            ac=ACAnalysisConfig(sweep_type="invalid"),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "ac.sweep_type" for e in result.errors)
    
    def test_invalid_dc_step(self, service):
        """DC 步进值为负数"""
        config = FullSimulationConfig(
            dc=DCAnalysisConfig(step=-0.1),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "dc.step" for e in result.errors)
    
    def test_invalid_transient_step_time(self, service):
        """瞬态步长为负数"""
        config = FullSimulationConfig(
            transient=TransientConfig(step_time=-1e-6),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "transient.step_time" for e in result.errors)
    
    def test_invalid_transient_end_time(self, service):
        """瞬态终止时间小于起始时间"""
        config = FullSimulationConfig(
            transient=TransientConfig(start_time=1e-3, end_time=1e-6),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "transient.end_time" for e in result.errors)
    
    def test_invalid_convergence_reltol(self, service):
        """收敛参数 reltol 超出范围"""
        config = FullSimulationConfig(
            global_config=GlobalSimulationConfig(
                convergence=ConvergenceConfig(reltol=1.5),
            ),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "global.convergence.reltol" for e in result.errors)
    
    def test_invalid_timeout(self, service):
        """超时时间为负数"""
        config = FullSimulationConfig(
            global_config=GlobalSimulationConfig(timeout_seconds=-1),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert any(e.field == "global.timeout_seconds" for e in result.errors)
    
    def test_multiple_errors(self, service):
        """多个校验错误"""
        config = FullSimulationConfig(
            ac=ACAnalysisConfig(start_freq=-1.0, stop_freq=-2.0),
            dc=DCAnalysisConfig(step=-0.1),
        )
        
        result = service.validate_config(config)
        
        assert result.is_valid is False
        assert len(result.errors) >= 3


# ============================================================
# 默认配置和重置测试
# ============================================================

class TestDefaultAndReset:
    """默认配置和重置测试"""
    
    def test_get_default_config(self, service):
        """获取默认配置"""
        config = service.get_default_config()
        
        assert config.version == "1.0"
        assert config.global_config.timeout_seconds == 300
        assert config.ac.points_per_decade == 20
    
    def test_reset_to_default(self, service, temp_project, config_with_values):
        """重置为默认配置"""
        # 先保存自定义配置
        service.save_config(temp_project, config_with_values, publish_event=False)
        
        # 重置
        result = service.reset_to_default(temp_project)
        assert result is True
        
        # 验证已重置
        loaded = service.load_config(temp_project)
        assert loaded.global_config.timeout_seconds == 300
        assert loaded.ac.start_freq == 1.0


# ============================================================
# 配置文件管理测试
# ============================================================

class TestConfigFileManagement:
    """配置文件管理测试"""
    
    def test_config_exists_false(self, service, temp_project):
        """配置文件不存在"""
        assert service.config_exists(temp_project) is False
    
    def test_config_exists_true(self, service, temp_project):
        """配置文件存在"""
        config = FullSimulationConfig.get_default()
        service.save_config(temp_project, config, publish_event=False)
        
        assert service.config_exists(temp_project) is True
    
    def test_delete_config(self, service, temp_project):
        """删除配置文件"""
        config = FullSimulationConfig.get_default()
        service.save_config(temp_project, config, publish_event=False)
        
        result = service.delete_config(temp_project)
        
        assert result is True
        assert service.config_exists(temp_project) is False
    
    def test_delete_nonexistent_config(self, service, temp_project):
        """删除不存在的配置文件"""
        result = service.delete_config(temp_project)
        
        assert result is True  # 不存在也返回 True


# ============================================================
# FullSimulationConfig 序列化测试
# ============================================================

class TestFullSimulationConfigSerialization:
    """完整配置序列化测试"""
    
    def test_to_dict(self, config_with_values):
        """序列化为字典"""
        data = config_with_values.to_dict()
        
        assert data["version"] == "1.0"
        assert data["global"]["timeout_seconds"] == 600
        assert data["ac"]["start_freq"] == 10.0
        assert data["dc"]["source_name"] == "Vin"
    
    def test_from_dict(self):
        """从字典反序列化"""
        data = {
            "version": "1.0",
            "global": {"timeout_seconds": 500, "temperature": 30.0},
            "ac": {"start_freq": 100.0},
            "dc": {"source_name": "Vdd"},
        }
        
        config = FullSimulationConfig.from_dict(data)
        
        assert config.global_config.timeout_seconds == 500
        assert config.global_config.temperature == 30.0
        assert config.ac.start_freq == 100.0
        assert config.dc.source_name == "Vdd"
    
    def test_round_trip(self, config_with_values):
        """序列化往返"""
        data = config_with_values.to_dict()
        restored = FullSimulationConfig.from_dict(data)
        
        assert restored.global_config.timeout_seconds == config_with_values.global_config.timeout_seconds
        assert restored.ac.start_freq == config_with_values.ac.start_freq
        assert restored.dc.source_name == config_with_values.dc.source_name


# ============================================================
# ValidationResult 测试
# ============================================================

class TestValidationResult:
    """校验结果测试"""
    
    def test_success_factory(self):
        """成功工厂方法"""
        result = ValidationResult.success()
        
        assert result.is_valid is True
        assert len(result.errors) == 0
    
    def test_failure_factory(self):
        """失败工厂方法"""
        errors = [
            ValidationError(field="test.field", message="error message"),
        ]
        result = ValidationResult.failure(errors)
        
        assert result.is_valid is False
        assert len(result.errors) == 1
    
    def test_add_error(self):
        """添加错误"""
        result = ValidationResult.success()
        result.add_error("field", "message", 123)
        
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "field"
        assert result.errors[0].value == 123
