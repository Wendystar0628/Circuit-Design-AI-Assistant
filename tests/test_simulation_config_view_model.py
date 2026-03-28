# Test Simulation Config ViewModel
"""
SimulationConfigViewModel 单元测试

测试内容：
- 配置加载和保存
- 字段更新和脏标记
- 配置校验
- 重置和撤销
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from presentation.dialogs.simulation_config.simulation_config_view_model import (
    SimulationConfigViewModel,
)
from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    ConvergenceConfig,
    DCAnalysisConfig,
    GlobalSimulationConfig,
    NoiseConfig,
    TransientConfig,
)
from domain.simulation.service.simulation_config_service import (
    FullSimulationConfig,
    SimulationConfigService,
    ValidationResult,
    ValidationError,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def temp_project_dir():
    """创建临时项目目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        circuit_ai_dir = Path(tmpdir) / ".circuit_ai"
        circuit_ai_dir.mkdir(parents=True, exist_ok=True)
        yield tmpdir


@pytest.fixture
def mock_config_service():
    """创建模拟的配置服务"""
    service = MagicMock(spec=SimulationConfigService)
    service.load_config.return_value = FullSimulationConfig.get_default()
    service.save_config.return_value = True
    service.validate_config.return_value = ValidationResult.success()
    return service


@pytest.fixture
def view_model(mock_config_service):
    """创建 ViewModel 实例"""
    vm = SimulationConfigViewModel(config_service=mock_config_service)
    vm.initialize()
    return vm


# ============================================================
# 初始化测试
# ============================================================

class TestInitialization:
    """初始化测试"""
    
    def test_default_state(self, view_model):
        """测试默认状态"""
        assert view_model.is_dirty is False
        assert view_model.validation_errors == []
        assert view_model.project_root is None
    
    def test_default_config_values(self, view_model):
        """测试默认配置值"""
        # AC 配置默认值
        assert view_model.ac_config.start_freq == 1.0
        assert view_model.ac_config.stop_freq == 1e9
        assert view_model.ac_config.points_per_decade == 20
        assert view_model.ac_config.sweep_type == "dec"
        
        # DC 配置默认值
        assert view_model.dc_config.source_name == ""
        assert view_model.dc_config.start_value == 0.0
        assert view_model.dc_config.stop_value == 5.0
        assert view_model.dc_config.step == 0.1
        
        # 瞬态配置默认值
        assert view_model.transient_config.step_time == 1e-6
        assert view_model.transient_config.end_time == 1e-3
        assert view_model.transient_config.start_time == 0.0
        
        # 收敛配置默认值
        assert view_model.convergence_config.gmin == 1e-12
        assert view_model.convergence_config.reltol == 1e-3


# ============================================================
# 配置加载测试
# ============================================================

class TestConfigLoading:
    """配置加载测试"""
    
    def test_load_config_success(self, view_model, mock_config_service, temp_project_dir):
        """测试成功加载配置"""
        result = view_model.load_config(temp_project_dir)
        
        assert result is True
        assert view_model.project_root == temp_project_dir
        assert view_model.is_dirty is False
        mock_config_service.load_config.assert_called_once_with(temp_project_dir)
    
    def test_load_config_failure(self, view_model, mock_config_service, temp_project_dir):
        """测试加载配置失败"""
        mock_config_service.load_config.side_effect = Exception("Load failed")
        
        result = view_model.load_config(temp_project_dir)
        
        assert result is False
    
    def test_load_config_updates_properties(self, view_model, mock_config_service, temp_project_dir):
        """测试加载配置后属性更新"""
        custom_config = FullSimulationConfig.get_default()
        custom_config.ac.start_freq = 100.0
        mock_config_service.load_config.return_value = custom_config
        
        view_model.load_config(temp_project_dir)
        
        assert view_model.ac_config.start_freq == 100.0


# ============================================================
# 配置保存测试
# ============================================================

class TestConfigSaving:
    """配置保存测试"""
    
    def test_save_config_success(self, view_model, mock_config_service, temp_project_dir):
        """测试成功保存配置"""
        view_model.load_config(temp_project_dir)
        view_model.update_ac_config("start_freq", 50.0)
        
        result = view_model.save_config()
        
        assert result is True
        assert view_model.is_dirty is False
        mock_config_service.save_config.assert_called()
    
    def test_save_config_without_project_root(self, view_model, mock_config_service):
        """测试未设置项目路径时保存"""
        result = view_model.save_config()
        
        assert result is False
    
    def test_save_config_validation_failure(self, view_model, mock_config_service, temp_project_dir):
        """测试校验失败时保存"""
        view_model.load_config(temp_project_dir)
        mock_config_service.validate_config.return_value = ValidationResult.failure([
            ValidationError(field="ac.start_freq", message="必须大于 0", value=-1)
        ])
        
        result = view_model.save_config()
        
        assert result is False
        assert len(view_model.validation_errors) > 0
    
    def test_save_completed_signal(self, view_model, mock_config_service, temp_project_dir):
        """测试保存完成信号"""
        view_model.load_config(temp_project_dir)
        
        signal_received = []
        view_model.save_completed.connect(lambda success: signal_received.append(success))
        
        view_model.save_config()
        
        assert len(signal_received) == 1
        assert signal_received[0] is True


# ============================================================
# 字段更新测试
# ============================================================

class TestFieldUpdates:
    """字段更新测试"""
    
    def test_update_ac_config(self, view_model):
        """测试更新 AC 配置"""
        view_model.update_ac_config("start_freq", 100.0)
        
        assert view_model.ac_config.start_freq == 100.0
        assert view_model.is_dirty is True
    
    def test_update_dc_config(self, view_model):
        """测试更新 DC 配置"""
        view_model.update_dc_config("source_name", "Vin")
        
        assert view_model.dc_config.source_name == "Vin"
        assert view_model.is_dirty is True
    
    def test_update_transient_config(self, view_model):
        """测试更新瞬态配置"""
        view_model.update_transient_config("end_time", 1e-2)
        
        assert view_model.transient_config.end_time == 1e-2
        assert view_model.is_dirty is True
    
    def test_update_noise_config(self, view_model):
        """测试更新噪声配置"""
        view_model.update_noise_config("output_node", "vout")
        
        assert view_model.noise_config.output_node == "vout"
        assert view_model.is_dirty is True
    
    def test_update_convergence_config(self, view_model):
        """测试更新收敛配置"""
        view_model.update_convergence_config("reltol", 1e-4)
        
        assert view_model.convergence_config.reltol == 1e-4
        assert view_model.is_dirty is True
    
    def test_update_global_config(self, view_model):
        """测试更新全局配置"""
        view_model.update_global_config("timeout_seconds", 600)
        
        assert view_model.global_config.timeout_seconds == 600
        assert view_model.is_dirty is True
    
    def test_update_unknown_field(self, view_model):
        """测试更新未知字段"""
        view_model.update_ac_config("unknown_field", 123)
        
        # 不应该崩溃，也不应该标记为脏
        assert view_model.is_dirty is False
    
    def test_config_changed_signal(self, view_model):
        """测试配置变更信号"""
        signal_count = [0]
        view_model.config_changed.connect(lambda: signal_count.__setitem__(0, signal_count[0] + 1))
        
        view_model.update_ac_config("start_freq", 100.0)
        view_model.update_dc_config("step", 0.5)
        
        assert signal_count[0] == 2


# ============================================================
# 完整配置设置测试
# ============================================================

class TestSetFullConfig:
    """完整配置设置测试"""
    
    def test_set_ac_config(self, view_model):
        """测试设置完整 AC 配置"""
        new_config = ACAnalysisConfig(
            start_freq=10.0,
            stop_freq=1e6,
            points_per_decade=50,
            sweep_type="lin"
        )
        
        view_model.set_ac_config(new_config)
        
        assert view_model.ac_config.start_freq == 10.0
        assert view_model.ac_config.stop_freq == 1e6
        assert view_model.ac_config.points_per_decade == 50
        assert view_model.ac_config.sweep_type == "lin"
        assert view_model.is_dirty is True
    
    def test_set_convergence_config(self, view_model):
        """测试设置完整收敛配置"""
        new_config = ConvergenceConfig(
            gmin=1e-14,
            abstol=1e-14,
            reltol=1e-4,
            vntol=1e-7,
            itl1=200,
            itl4=20
        )
        
        view_model.set_convergence_config(new_config)
        
        assert view_model.convergence_config.gmin == 1e-14
        assert view_model.convergence_config.itl1 == 200
        assert view_model.is_dirty is True


# ============================================================
# 校验测试
# ============================================================

class TestValidation:
    """校验测试"""
    
    def test_validate_all_success(self, view_model, mock_config_service):
        """测试校验全部通过"""
        mock_config_service.validate_config.return_value = ValidationResult.success()
        
        result = view_model.validate_all()
        
        assert result is True
        assert view_model.validation_errors == []
    
    def test_validate_all_failure(self, view_model, mock_config_service):
        """测试校验失败"""
        mock_config_service.validate_config.return_value = ValidationResult.failure([
            ValidationError(field="ac.start_freq", message="必须大于 0", value=-1),
            ValidationError(field="dc.step", message="必须大于 0", value=0),
        ])
        
        result = view_model.validate_all()
        
        assert result is False
        assert len(view_model.validation_errors) == 2
        assert "ac.start_freq" in view_model.validation_errors[0]
    
    def test_validation_failed_signal(self, view_model, mock_config_service):
        """测试校验失败信号"""
        mock_config_service.validate_config.return_value = ValidationResult.failure([
            ValidationError(field="ac.start_freq", message="必须大于 0", value=-1),
        ])
        
        signal_received = []
        view_model.validation_failed.connect(lambda errors: signal_received.extend(errors))
        
        view_model.validate_all()
        
        assert len(signal_received) == 1
    
    def test_validate_field(self, view_model, mock_config_service):
        """测试单字段校验"""
        mock_config_service.validate_config.return_value = ValidationResult.failure([
            ValidationError(field="ac.start_freq", message="必须大于 0", value=-1),
        ])
        
        error = view_model.validate_field("ac", "start_freq")
        
        assert error == "必须大于 0"
    
    def test_validate_field_no_error(self, view_model, mock_config_service):
        """测试单字段校验无错误"""
        mock_config_service.validate_config.return_value = ValidationResult.success()
        
        error = view_model.validate_field("ac", "start_freq")
        
        assert error is None


# ============================================================
# 重置和撤销测试
# ============================================================

class TestResetAndRevert:
    """重置和撤销测试"""
    
    def test_reset_to_default(self, view_model):
        """测试重置为默认值"""
        view_model.update_ac_config("start_freq", 999.0)
        
        view_model.reset_to_default()
        
        assert view_model.ac_config.start_freq == 1.0
        assert view_model.is_dirty is True
    
    def test_revert_changes(self, view_model, mock_config_service, temp_project_dir):
        """测试撤销修改"""
        view_model.load_config(temp_project_dir)
        original_freq = view_model.ac_config.start_freq
        
        view_model.update_ac_config("start_freq", 999.0)
        assert view_model.ac_config.start_freq == 999.0
        
        view_model.revert_changes()
        
        assert view_model.ac_config.start_freq == original_freq
        assert view_model.is_dirty is False


# ============================================================
# 辅助方法测试
# ============================================================

class TestHelperMethods:
    """辅助方法测试"""
    
    def test_get_config_dict(self, view_model):
        """测试获取配置字典"""
        config_dict = view_model.get_config_dict()
        
        assert "ac" in config_dict
        assert "dc" in config_dict
        assert "transient" in config_dict
        assert "noise" in config_dict
        assert "global" in config_dict
    
    def test_get_full_config(self, view_model):
        """测试获取完整配置对象"""
        config = view_model.get_full_config()
        
        assert isinstance(config, FullSimulationConfig)
        assert config.ac is view_model.ac_config


# ============================================================
# 属性通知测试
# ============================================================

class TestPropertyNotification:
    """属性通知测试"""
    
    def test_property_changed_on_update(self, view_model):
        """测试更新时属性变更通知"""
        notifications = []
        view_model.property_changed.connect(
            lambda name, value: notifications.append((name, value))
        )
        
        view_model.update_ac_config("start_freq", 100.0)
        
        assert any(n[0] == "ac_config" for n in notifications)
        assert any(n[0] == "is_dirty" for n in notifications)
    
    def test_property_changed_on_load(self, view_model, mock_config_service, temp_project_dir):
        """测试加载时属性变更通知"""
        notifications = []
        view_model.property_changed.connect(
            lambda name, value: notifications.append((name, value))
        )
        
        view_model.load_config(temp_project_dir)
        
        # 应该通知所有配置属性
        property_names = [n[0] for n in notifications]
        assert "ac_config" in property_names
        assert "dc_config" in property_names
        assert "transient_config" in property_names


# ============================================================
# 集成测试（使用真实服务）
# ============================================================

class TestIntegration:
    """集成测试"""
    
    def test_full_workflow(self, temp_project_dir):
        """测试完整工作流程"""
        # 使用真实的配置服务
        vm = SimulationConfigViewModel()
        vm.initialize()
        
        # 加载配置
        assert vm.load_config(temp_project_dir) is True
        
        # 修改配置
        vm.update_ac_config("start_freq", 100.0)
        vm.update_dc_config("source_name", "Vin")
        vm.update_transient_config("end_time", 1e-2)
        
        assert vm.is_dirty is True
        
        # 校验
        assert vm.validate_all() is True
        
        # 保存
        assert vm.save_config() is True
        assert vm.is_dirty is False
        
        # 重新加载验证
        vm2 = SimulationConfigViewModel()
        vm2.initialize()
        vm2.load_config(temp_project_dir)
        
        assert vm2.ac_config.start_freq == 100.0
        assert vm2.dc_config.source_name == "Vin"
        assert vm2.transient_config.end_time == 1e-2
