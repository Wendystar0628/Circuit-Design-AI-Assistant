# Test Simulation Config Dialog
"""
仿真配置对话框测试

测试内容：
- 对话框初始化
- UI 组件创建
- 配置加载和同步
- 保存和重置功能
- ViewModel 集成
"""

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from presentation.dialogs.simulation_config.simulation_config_dialog import (
    SimulationConfigDialog,
)
from presentation.dialogs.simulation_config.simulation_config_view_model import (
    SimulationConfigViewModel,
)
from domain.simulation.models.simulation_config import (
    ACAnalysisConfig,
    DCAnalysisConfig,
    TransientConfig,
    NoiseConfig,
    ConvergenceConfig,
    GlobalSimulationConfig,
)
from domain.simulation.service.simulation_config_service import (
    FullSimulationConfig,
    ValidationResult,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_view_model():
    """创建 Mock ViewModel"""
    vm = MagicMock(spec=SimulationConfigViewModel)
    
    # 配置属性
    vm.ac_config = ACAnalysisConfig()
    vm.dc_config = DCAnalysisConfig()
    vm.transient_config = TransientConfig()
    vm.noise_config = NoiseConfig()
    vm.convergence_config = ConvergenceConfig()
    vm.global_config = GlobalSimulationConfig()
    vm.is_dirty = False
    vm.validation_errors = []
    
    # 配置方法
    vm.load_config.return_value = True
    vm.save_config.return_value = True
    vm.validate_all.return_value = True
    
    return vm


@pytest.fixture
def dialog(app, mock_view_model):
    """创建对话框实例"""
    dialog = SimulationConfigDialog(view_model=mock_view_model)
    yield dialog
    dialog.close()


# ============================================================
# 初始化测试
# ============================================================

class TestDialogInitialization:
    """对话框初始化测试"""
    
    def test_dialog_created(self, dialog):
        """测试对话框创建"""
        assert dialog is not None
    
    def test_tab_widget_created(self, dialog):
        """测试标签页容器创建"""
        assert dialog._tab_widget is not None
        assert dialog._tab_widget.count() == 5
    
    def test_ac_tab_components(self, dialog):
        """测试 AC 标签页组件"""
        assert dialog._ac_start_freq_spin is not None
        assert dialog._ac_stop_freq_spin is not None
        assert dialog._ac_points_spin is not None
        assert dialog._ac_sweep_combo is not None
    
    def test_dc_tab_components(self, dialog):
        """测试 DC 标签页组件"""
        assert dialog._dc_source_edit is not None
        assert dialog._dc_start_spin is not None
        assert dialog._dc_stop_spin is not None
        assert dialog._dc_step_spin is not None
    
    def test_transient_tab_components(self, dialog):
        """测试瞬态标签页组件"""
        assert dialog._tran_step_spin is not None
        assert dialog._tran_end_spin is not None
        assert dialog._tran_start_spin is not None
        assert dialog._tran_max_step_spin is not None
        assert dialog._tran_uic_check is not None
    
    def test_noise_tab_components(self, dialog):
        """测试噪声标签页组件"""
        assert dialog._noise_output_edit is not None
        assert dialog._noise_input_edit is not None
        assert dialog._noise_start_freq_spin is not None
        assert dialog._noise_stop_freq_spin is not None
    
    def test_convergence_tab_components(self, dialog):
        """测试收敛标签页组件"""
        assert dialog._conv_gmin_spin is not None
        assert dialog._conv_abstol_spin is not None
        assert dialog._conv_reltol_spin is not None
        assert dialog._conv_vntol_spin is not None
        assert dialog._conv_itl1_spin is not None
        assert dialog._conv_itl4_spin is not None
        assert dialog._global_timeout_spin is not None
        assert dialog._global_temp_spin is not None
    
    def test_buttons_created(self, dialog):
        """测试按钮创建"""
        assert dialog._save_btn is not None
        assert dialog._reset_btn is not None
        assert dialog._cancel_btn is not None


# ============================================================
# 配置加载测试
# ============================================================

class TestConfigLoading:
    """配置加载测试"""
    
    def test_load_config_success(self, dialog, mock_view_model):
        """测试配置加载成功"""
        result = dialog.load_config("/test/project")
        
        assert result is True
        mock_view_model.load_config.assert_called_once_with("/test/project")
        assert dialog._project_root == "/test/project"
    
    def test_load_config_failure(self, dialog, mock_view_model):
        """测试配置加载失败"""
        mock_view_model.load_config.return_value = False
        
        result = dialog.load_config("/test/project")
        
        assert result is False
    
    def test_set_project_root(self, dialog):
        """测试设置项目根目录"""
        dialog.set_project_root("/another/project")
        assert dialog._project_root == "/another/project"


# ============================================================
# UI 同步测试
# ============================================================

class TestUISynchronization:
    """UI 同步测试"""
    
    def test_sync_ac_config(self, dialog, mock_view_model):
        """测试 AC 配置同步"""
        mock_view_model.ac_config = ACAnalysisConfig(
            start_freq=10.0,
            stop_freq=1e6,
            points_per_decade=50,
            sweep_type="lin"
        )
        
        dialog._sync_ui_from_view_model()
        
        assert dialog._ac_start_freq_spin.value() == 10.0
        assert dialog._ac_stop_freq_spin.value() == 1e6
        assert dialog._ac_points_spin.value() == 50
        assert dialog._ac_sweep_combo.currentData() == "lin"
    
    def test_sync_dc_config(self, dialog, mock_view_model):
        """测试 DC 配置同步"""
        mock_view_model.dc_config = DCAnalysisConfig(
            source_name="Vtest",
            start_value=-1.0,
            stop_value=3.0,
            step=0.05
        )
        
        dialog._sync_ui_from_view_model()
        
        assert dialog._dc_source_edit.text() == "Vtest"
        assert dialog._dc_start_spin.value() == -1.0
        assert dialog._dc_stop_spin.value() == 3.0
        assert dialog._dc_step_spin.value() == 0.05
    
    def test_sync_transient_config(self, dialog, mock_view_model):
        """测试瞬态配置同步"""
        mock_view_model.transient_config = TransientConfig(
            step_time=1e-9,
            end_time=1e-6,
            start_time=0,
            max_step=1e-8,
            use_initial_conditions=True
        )
        
        dialog._sync_ui_from_view_model()
        
        assert dialog._tran_step_spin.value() == 1e-9
        assert dialog._tran_end_spin.value() == 1e-6
        assert dialog._tran_start_spin.value() == 0
        assert dialog._tran_max_step_spin.value() == 1e-8
        assert dialog._tran_uic_check.isChecked() is True
    
    def test_sync_noise_config(self, dialog, mock_view_model):
        """测试噪声配置同步"""
        mock_view_model.noise_config = NoiseConfig(
            output_node="vout",
            input_source="Vin",
            start_freq=100.0,
            stop_freq=1e9
        )
        
        dialog._sync_ui_from_view_model()
        
        assert dialog._noise_output_edit.text() == "vout"
        assert dialog._noise_input_edit.text() == "Vin"
        assert dialog._noise_start_freq_spin.value() == 100.0
        assert dialog._noise_stop_freq_spin.value() == 1e9
    
    def test_sync_convergence_config(self, dialog, mock_view_model):
        """测试收敛配置同步"""
        mock_view_model.convergence_config = ConvergenceConfig(
            gmin=1e-10,
            abstol=1e-10,
            reltol=1e-4,
            vntol=1e-5,
            itl1=200,
            itl4=20
        )
        
        dialog._sync_ui_from_view_model()
        
        assert dialog._conv_gmin_spin.value() == 1e-10
        assert dialog._conv_abstol_spin.value() == 1e-10
        assert dialog._conv_reltol_spin.value() == 1e-4
        assert dialog._conv_vntol_spin.value() == 1e-5
        assert dialog._conv_itl1_spin.value() == 200
        assert dialog._conv_itl4_spin.value() == 20
    
    def test_sync_global_config(self, dialog, mock_view_model):
        """测试全局配置同步"""
        mock_view_model.global_config = GlobalSimulationConfig(
            timeout_seconds=600,
            temperature=85.0
        )
        
        dialog._sync_ui_from_view_model()
        
        assert dialog._global_timeout_spin.value() == 600
        assert dialog._global_temp_spin.value() == 85.0


# ============================================================
# 按钮行为测试
# ============================================================

class TestButtonBehavior:
    """按钮行为测试"""
    
    def test_save_without_project_root(self, dialog, mock_view_model):
        """测试无项目根目录时保存"""
        dialog._project_root = None
        
        # 不应调用 ViewModel 的保存方法
        dialog._on_save_clicked()
        mock_view_model.save_config.assert_not_called()
    
    def test_save_with_project_root(self, dialog, mock_view_model):
        """测试有项目根目录时保存"""
        dialog._project_root = "/test/project"
        
        dialog._on_save_clicked()
        mock_view_model.save_config.assert_called_once_with("/test/project")
    
    def test_reset_calls_view_model(self, dialog, mock_view_model):
        """测试重置调用 ViewModel"""
        # 直接调用重置方法（跳过确认对话框）
        mock_view_model.reset_to_default.return_value = None
        
        # 模拟确认对话框返回 Yes
        with patch('PyQt6.QtWidgets.QMessageBox.question') as mock_question:
            from PyQt6.QtWidgets import QMessageBox
            mock_question.return_value = QMessageBox.StandardButton.Yes
            
            dialog._on_reset_clicked()
            
            mock_view_model.reset_to_default.assert_called_once()


# ============================================================
# 国际化测试
# ============================================================

class TestInternationalization:
    """国际化测试"""
    
    def test_retranslate_ui(self, dialog):
        """测试国际化文本更新"""
        # 应该不抛出异常
        dialog.retranslate_ui()
        
        # 检查标签页标题
        assert dialog._tab_widget.tabText(0) == "AC 分析"
        assert dialog._tab_widget.tabText(1) == "DC 分析"
        assert dialog._tab_widget.tabText(2) == "瞬态分析"
        assert dialog._tab_widget.tabText(3) == "噪声分析"
        assert dialog._tab_widget.tabText(4) == "收敛参数"


# ============================================================
# 集成测试
# ============================================================

class TestIntegration:
    """集成测试（使用真实 ViewModel）"""
    
    def test_with_real_view_model(self, app):
        """测试使用真实 ViewModel"""
        dialog = SimulationConfigDialog()
        
        assert dialog._view_model is not None
        assert isinstance(dialog._view_model, SimulationConfigViewModel)
        
        dialog.close()
    
    def test_default_values_displayed(self, app):
        """测试默认值显示"""
        dialog = SimulationConfigDialog()
        
        # AC 默认值
        assert dialog._ac_start_freq_spin.value() == 1.0
        assert dialog._ac_stop_freq_spin.value() == 1e9
        assert dialog._ac_points_spin.value() == 20
        
        # DC 默认值
        assert dialog._dc_start_spin.value() == 0.0
        assert dialog._dc_stop_spin.value() == 5.0
        assert dialog._dc_step_spin.value() == 0.1
        
        # 瞬态默认值
        assert dialog._tran_step_spin.value() == 1e-6
        assert dialog._tran_end_spin.value() == 1e-3
        
        # 收敛默认值
        assert dialog._conv_gmin_spin.value() == 1e-12
        assert dialog._conv_reltol_spin.value() == 1e-3
        
        dialog.close()
