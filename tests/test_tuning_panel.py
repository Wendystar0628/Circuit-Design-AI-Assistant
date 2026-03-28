# Test Tuning Panel
"""
快速调参面板测试

测试内容：
- 参数提取器功能
- 参数滑块组件
- 调参面板整体功能
"""

import pytest
from unittest.mock import MagicMock, patch

# 参数提取器测试
class TestParameterExtractor:
    """参数提取器测试"""
    
    def test_extract_param_statement(self):
        """测试提取 .param 语句"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
* Test circuit
.param Rf = 10k
.param Cf = 100p
.param gain = 2.5
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 3
        
        # 检查参数名
        names = [p.name for p in result.parameters]
        assert "Rf" in names
        assert "Cf" in names
        assert "gain" in names
        
        # 检查参数类型
        for param in result.parameters:
            assert param.param_type == ParameterType.PARAM
    
    def test_extract_resistor(self):
        """测试提取电阻参数"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
R1 in out 10k
R2 out gnd 4.7k
Rfb vout vin 100k
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 3
        
        # 检查参数类型
        for param in result.parameters:
            assert param.param_type == ParameterType.RESISTOR
            assert param.unit == "Ω"
    
    def test_extract_capacitor(self):
        """测试提取电容参数"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
C1 in gnd 100p
C2 out gnd 10n
Ccomp vout gnd 1u
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 3
        
        for param in result.parameters:
            assert param.param_type == ParameterType.CAPACITOR
            assert param.unit == "F"
    
    def test_extract_inductor(self):
        """测试提取电感参数"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
L1 in out 10u
L2 vcc gnd 100n
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 2
        
        for param in result.parameters:
            assert param.param_type == ParameterType.INDUCTOR
            assert param.unit == "H"
    
    def test_extract_voltage_source(self):
        """测试提取电压源参数"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
Vcc vcc gnd 5
Vin in gnd DC 1.0
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 2
        
        for param in result.parameters:
            assert param.param_type == ParameterType.VOLTAGE
            assert param.unit == "V"
    
    def test_extract_current_source(self):
        """测试提取电流源参数"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
Ibias bias gnd 10u
Iref ref gnd DC 1m
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 2
        
        for param in result.parameters:
            assert param.param_type == ParameterType.CURRENT
            assert param.unit == "A"
    
    def test_skip_comments(self):
        """测试跳过注释行"""
        from domain.simulation.service.parameter_extractor import ParameterExtractor
        
        extractor = ParameterExtractor()
        content = """
* This is a comment
; Another comment
.param Rf = 10k
* R1 in out 10k  <- this should be skipped
R2 out gnd 4.7k
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        assert result.count == 2
        
        names = [p.name for p in result.parameters]
        assert "Rf" in names
        assert "R2" in names
        assert "R1" not in names
    
    def test_unit_prefix_parsing(self):
        """测试单位前缀解析"""
        from domain.simulation.service.parameter_extractor import ParameterExtractor
        
        extractor = ParameterExtractor()
        content = """
.param val_f = 1f
.param val_p = 1p
.param val_n = 1n
.param val_u = 1u
.param val_m = 1m
.param val_k = 1k
.param val_meg = 1meg
"""
        result = extractor.extract_from_content(content)
        
        assert result.success
        
        # 检查数值解析
        params = {p.name: p.value for p in result.parameters}
        assert abs(params["val_f"] - 1e-15) < 1e-20
        assert abs(params["val_p"] - 1e-12) < 1e-17
        assert abs(params["val_n"] - 1e-9) < 1e-14
        assert abs(params["val_u"] - 1e-6) < 1e-11
        assert abs(params["val_m"] - 1e-3) < 1e-8
        assert abs(params["val_k"] - 1e3) < 1e-2
        assert abs(params["val_meg"] - 1e6) < 1e1
    
    def test_auto_range_calculation(self):
        """测试自动范围计算"""
        from domain.simulation.service.parameter_extractor import TunableParameter
        
        param = TunableParameter(
            name="test",
            value=100.0,
            unit="Ω",
        )
        
        # 默认范围应该是 0.1x 到 10x
        assert param.min_value == pytest.approx(10.0)
        assert param.max_value == pytest.approx(1000.0)
        assert param.step > 0
    
    def test_format_value_with_unit(self):
        """测试数值格式化"""
        from domain.simulation.service.parameter_extractor import ParameterExtractor
        
        extractor = ParameterExtractor()
        
        assert "1 kΩ" == extractor.format_value_with_unit(1000, "Ω")
        assert "10 uF" == extractor.format_value_with_unit(10e-6, "F")
        assert "100 nH" == extractor.format_value_with_unit(100e-9, "H")
        assert "1 mA" == extractor.format_value_with_unit(1e-3, "A")
    
    def test_get_by_name(self):
        """测试按名称获取参数"""
        from domain.simulation.service.parameter_extractor import ParameterExtractor
        
        extractor = ParameterExtractor()
        content = """
.param Rf = 10k
R1 in out 4.7k
"""
        result = extractor.extract_from_content(content)
        
        param = result.get_by_name("Rf")
        assert param is not None
        assert param.name == "Rf"
        
        param = result.get_by_name("R1")
        assert param is not None
        assert param.name == "R1"
        
        param = result.get_by_name("nonexistent")
        assert param is None
    
    def test_get_by_type(self):
        """测试按类型获取参数"""
        from domain.simulation.service.parameter_extractor import (
            ParameterExtractor,
            ParameterType,
        )
        
        extractor = ParameterExtractor()
        content = """
.param Rf = 10k
R1 in out 4.7k
C1 out gnd 100p
"""
        result = extractor.extract_from_content(content)
        
        params = result.get_by_type(ParameterType.PARAM)
        assert len(params) == 1
        assert params[0].name == "Rf"
        
        resistors = result.get_by_type(ParameterType.RESISTOR)
        assert len(resistors) == 1
        assert resistors[0].name == "R1"
        
        capacitors = result.get_by_type(ParameterType.CAPACITOR)
        assert len(capacitors) == 1
        assert capacitors[0].name == "C1"


class TestTuningPanelUnit:
    """调参面板单元测试（不依赖 Qt）"""
    
    def test_parameter_state_creation(self):
        """测试参数状态创建"""
        from presentation.panels.simulation.tuning_panel import ParameterState
        
        state = ParameterState(
            name="R1",
            current_value=1000.0,
            original_value=1000.0,
            min_value=100.0,
            max_value=10000.0,
            step=100.0,
            unit="Ω",
            param_type="resistor",
            line_number=5,
            element_name="R1",
        )
        
        assert state.name == "R1"
        assert state.current_value == 1000.0
        assert state.original_value == 1000.0
        assert state.min_value == 100.0
        assert state.max_value == 10000.0


# Qt 相关测试需要 pytest-qt
@pytest.fixture
def qapp():
    """创建 Qt 应用实例"""
    try:
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app
    except ImportError:
        pytest.skip("PyQt6 not available")


class TestTuningPanelQt:
    """调参面板 Qt 测试"""
    
    def test_panel_creation(self, qapp):
        """测试面板创建"""
        from presentation.panels.simulation.tuning_panel import TuningPanel
        
        panel = TuningPanel()
        panel.show()  # 需要显示才能检测可见性
        assert panel is not None
        
        # 初始状态应该是空状态（scroll_area 隐藏）
        assert not panel._scroll_area.isVisible()
    
    def test_load_parameters(self, qapp):
        """测试加载参数"""
        from presentation.panels.simulation.tuning_panel import TuningPanel
        from domain.simulation.service.parameter_extractor import (
            TunableParameter,
            ParameterType,
        )
        
        panel = TuningPanel()
        panel.show()  # 需要显示才能检测可见性
        
        params = [
            TunableParameter(
                name="R1",
                value=1000.0,
                unit="Ω",
                param_type=ParameterType.RESISTOR,
            ),
            TunableParameter(
                name="C1",
                value=100e-12,
                unit="F",
                param_type=ParameterType.CAPACITOR,
            ),
        ]
        
        panel.load_parameters(params)
        
        # 应该隐藏空状态，显示滚动区域
        assert not panel._empty_widget.isVisible()
        assert panel._scroll_area.isVisible()
        
        # 应该有两个滑块
        assert len(panel._sliders) == 2
        assert "R1" in panel._sliders
        assert "C1" in panel._sliders
    
    def test_get_modified_parameters(self, qapp):
        """测试获取已修改参数"""
        from presentation.panels.simulation.tuning_panel import TuningPanel
        from domain.simulation.service.parameter_extractor import (
            TunableParameter,
            ParameterType,
        )
        
        panel = TuningPanel()
        
        params = [
            TunableParameter(
                name="R1",
                value=1000.0,
                unit="Ω",
                param_type=ParameterType.RESISTOR,
            ),
        ]
        
        panel.load_parameters(params)
        
        # 初始状态没有修改
        modified = panel.get_modified_parameters()
        assert len(modified) == 0
        
        # 修改参数
        panel._sliders["R1"].set_value(2000.0)
        
        modified = panel.get_modified_parameters()
        assert len(modified) == 1
        assert "R1" in modified
        assert modified["R1"] == 2000.0
    
    def test_reset_parameters(self, qapp):
        """测试重置参数"""
        from presentation.panels.simulation.tuning_panel import TuningPanel
        from domain.simulation.service.parameter_extractor import (
            TunableParameter,
            ParameterType,
        )
        
        panel = TuningPanel()
        
        params = [
            TunableParameter(
                name="R1",
                value=1000.0,
                unit="Ω",
                param_type=ParameterType.RESISTOR,
            ),
        ]
        
        panel.load_parameters(params)
        
        # 修改参数
        panel._sliders["R1"].set_value(2000.0)
        assert panel._sliders["R1"].is_modified
        
        # 重置
        panel._on_reset_clicked()
        
        # 应该恢复原始值
        assert not panel._sliders["R1"].is_modified
        assert panel._sliders["R1"].current_value == 1000.0
    
    def test_clear_parameters(self, qapp):
        """测试清空参数"""
        from presentation.panels.simulation.tuning_panel import TuningPanel
        from domain.simulation.service.parameter_extractor import (
            TunableParameter,
            ParameterType,
        )
        
        panel = TuningPanel()
        panel.show()  # 需要显示才能检测可见性
        
        params = [
            TunableParameter(
                name="R1",
                value=1000.0,
                unit="Ω",
                param_type=ParameterType.RESISTOR,
            ),
        ]
        
        panel.load_parameters(params)
        assert len(panel._sliders) == 1
        
        panel.clear()
        
        assert len(panel._sliders) == 0
        # 清空后应该显示空状态
        assert not panel._scroll_area.isVisible()
    
    def test_auto_simulation_toggle(self, qapp):
        """测试自动仿真开关"""
        from presentation.panels.simulation.tuning_panel import TuningPanel
        
        panel = TuningPanel()
        
        assert not panel._auto_simulation_enabled
        
        panel.set_auto_simulation(True)
        assert panel._auto_simulation_enabled
        assert panel._auto_sim_checkbox.isChecked()
        
        panel.set_auto_simulation(False)
        assert not panel._auto_simulation_enabled
        assert not panel._auto_sim_checkbox.isChecked()


class TestParameterSliderWidget:
    """参数滑块组件测试"""
    
    def test_slider_creation(self, qapp):
        """测试滑块创建"""
        from presentation.panels.simulation.tuning_panel import (
            ParameterSliderWidget,
            ParameterState,
        )
        
        state = ParameterState(
            name="R1",
            current_value=1000.0,
            original_value=1000.0,
            min_value=100.0,
            max_value=10000.0,
            step=100.0,
            unit="Ω",
            param_type="resistor",
            line_number=5,
            element_name="R1",
        )
        
        slider = ParameterSliderWidget(state)
        
        assert slider.param_name == "R1"
        assert slider.current_value == 1000.0
        assert slider.original_value == 1000.0
        assert not slider.is_modified
    
    def test_slider_value_change(self, qapp):
        """测试滑块值变化"""
        from presentation.panels.simulation.tuning_panel import (
            ParameterSliderWidget,
            ParameterState,
        )
        
        state = ParameterState(
            name="R1",
            current_value=1000.0,
            original_value=1000.0,
            min_value=100.0,
            max_value=10000.0,
            step=100.0,
            unit="Ω",
            param_type="resistor",
            line_number=5,
            element_name="R1",
        )
        
        slider = ParameterSliderWidget(state)
        
        # 记录信号
        received_values = []
        slider.value_changed.connect(lambda name, val: received_values.append((name, val)))
        
        # 设置新值
        slider.set_value(2000.0)
        
        assert slider.current_value == 2000.0
        assert slider.is_modified
    
    def test_slider_reset(self, qapp):
        """测试滑块重置"""
        from presentation.panels.simulation.tuning_panel import (
            ParameterSliderWidget,
            ParameterState,
        )
        
        state = ParameterState(
            name="R1",
            current_value=1000.0,
            original_value=1000.0,
            min_value=100.0,
            max_value=10000.0,
            step=100.0,
            unit="Ω",
            param_type="resistor",
            line_number=5,
            element_name="R1",
        )
        
        slider = ParameterSliderWidget(state)
        
        slider.set_value(2000.0)
        assert slider.is_modified
        
        slider.reset_to_original()
        assert not slider.is_modified
        assert slider.current_value == 1000.0
    
    def test_slider_range_change(self, qapp):
        """测试滑块范围变化"""
        from presentation.panels.simulation.tuning_panel import (
            ParameterSliderWidget,
            ParameterState,
        )
        
        state = ParameterState(
            name="R1",
            current_value=1000.0,
            original_value=1000.0,
            min_value=100.0,
            max_value=10000.0,
            step=100.0,
            unit="Ω",
            param_type="resistor",
            line_number=5,
            element_name="R1",
        )
        
        slider = ParameterSliderWidget(state)
        
        slider.set_range(500.0, 5000.0)
        
        # 范围应该更新
        assert slider._param.min_value == 500.0
        assert slider._param.max_value == 5000.0
