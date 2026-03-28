# test_measurement_tool.py - MeasurementTool Unit Tests
"""
双光标测量工具单元测试

测试内容：
- 光标位置设置和获取
- 差值计算（ΔX、ΔY、斜率、频率）
- 关键点快速定位（峰值、谷值、过零点、-3dB 点）
- 波形数据绑定
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch


class TestMeasurementValues:
    """测试 MeasurementValues 数据类"""
    
    def test_default_values(self):
        """测试默认值"""
        from presentation.panels.simulation.measurement_tool import MeasurementValues
        
        mv = MeasurementValues()
        
        assert mv.cursor_a_x is None
        assert mv.cursor_a_y is None
        assert mv.cursor_b_x is None
        assert mv.cursor_b_y is None
        assert mv.delta_x is None
        assert mv.delta_y is None
        assert mv.slope is None
        assert mv.frequency is None
    
    def test_has_cursor_a(self):
        """测试 has_cursor_a 方法"""
        from presentation.panels.simulation.measurement_tool import MeasurementValues
        
        mv = MeasurementValues()
        assert mv.has_cursor_a() is False
        
        mv.cursor_a_x = 1.0
        assert mv.has_cursor_a() is True
    
    def test_has_cursor_b(self):
        """测试 has_cursor_b 方法"""
        from presentation.panels.simulation.measurement_tool import MeasurementValues
        
        mv = MeasurementValues()
        assert mv.has_cursor_b() is False
        
        mv.cursor_b_x = 2.0
        assert mv.has_cursor_b() is True
    
    def test_has_dual_cursor(self):
        """测试 has_dual_cursor 方法"""
        from presentation.panels.simulation.measurement_tool import MeasurementValues
        
        mv = MeasurementValues()
        assert mv.has_dual_cursor() is False
        
        mv.cursor_a_x = 1.0
        assert mv.has_dual_cursor() is False
        
        mv.cursor_b_x = 2.0
        assert mv.has_dual_cursor() is True


class TestSnapTarget:
    """测试 SnapTarget 枚举"""
    
    def test_enum_values(self):
        """测试枚举值"""
        from presentation.panels.simulation.measurement_tool import SnapTarget
        
        assert SnapTarget.PEAK.value == "peak"
        assert SnapTarget.VALLEY.value == "valley"
        assert SnapTarget.ZERO_CROSSING.value == "zero_crossing"
        assert SnapTarget.MINUS_3DB.value == "minus_3db"


@pytest.fixture
def qapp():
    """创建 Qt 应用实例"""
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def measurement_tool(qapp):
    """创建 MeasurementTool 实例"""
    from presentation.panels.simulation.measurement_tool import MeasurementTool
    
    tool = MeasurementTool()
    yield tool
    tool.deleteLater()


class TestMeasurementToolBasic:
    """测试 MeasurementTool 基本功能"""
    
    def test_initialization(self, measurement_tool):
        """测试初始化"""
        assert measurement_tool._x_data is None
        assert measurement_tool._y_data is None
        assert measurement_tool._waveform_widget is None
    
    def test_set_waveform_data(self, measurement_tool):
        """测试设置波形数据"""
        x_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        y_data = np.array([0.0, 1.0, 0.0, -1.0, 0.0])
        
        measurement_tool.set_waveform_data(x_data, y_data)
        
        assert measurement_tool._x_data is not None
        assert measurement_tool._y_data is not None
        assert len(measurement_tool._x_data) == 5
        assert len(measurement_tool._y_data) == 5
    
    def test_set_cursor_a(self, measurement_tool):
        """测试设置光标 A"""
        x_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        y_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        measurement_tool.set_waveform_data(x_data, y_data)
        
        measurement_tool.set_cursor_a(1.5)
        
        assert measurement_tool._measurement.cursor_a_x == 1.5
        assert measurement_tool._measurement.cursor_a_y == pytest.approx(1.5, rel=1e-6)
    
    def test_set_cursor_b(self, measurement_tool):
        """测试设置光标 B"""
        x_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        y_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        measurement_tool.set_waveform_data(x_data, y_data)
        
        measurement_tool.set_cursor_b(2.5)
        
        assert measurement_tool._measurement.cursor_b_x == 2.5
        assert measurement_tool._measurement.cursor_b_y == pytest.approx(2.5, rel=1e-6)
    
    def test_delta_calculation(self, measurement_tool):
        """测试差值计算"""
        x_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        y_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        measurement_tool.set_waveform_data(x_data, y_data)
        
        measurement_tool.set_cursor_a(1.0)
        measurement_tool.set_cursor_b(3.0)
        
        values = measurement_tool.get_delta_values()
        
        assert values.delta_x == pytest.approx(2.0, rel=1e-6)
        assert values.delta_y == pytest.approx(2.0, rel=1e-6)
        assert values.slope == pytest.approx(1.0, rel=1e-6)
        assert values.frequency == pytest.approx(0.5, rel=1e-6)
    
    def test_clear(self, measurement_tool):
        """测试清空"""
        x_data = np.array([0.0, 1.0, 2.0])
        y_data = np.array([0.0, 1.0, 2.0])
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(1.0)
        measurement_tool.set_cursor_b(2.0)
        
        measurement_tool.clear()
        
        assert measurement_tool._x_data is None
        assert measurement_tool._y_data is None
        assert measurement_tool._measurement.cursor_a_x is None
        assert measurement_tool._measurement.cursor_b_x is None


class TestMeasurementToolSnap:
    """测试 MeasurementTool 快速定位功能"""
    
    def test_snap_to_peak(self, measurement_tool):
        """测试吸附到峰值"""
        # 创建有明显峰值的数据
        x_data = np.linspace(0, 10, 100)
        y_data = np.sin(x_data)  # 峰值在 π/2 ≈ 1.57, 5π/2 ≈ 7.85
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(1.0)  # 设置初始位置，接近第一个峰值
        
        result = measurement_tool.snap_to_peak()
        
        assert result is True
        # 应该找到一个峰值位置，Y 值接近 1.0
        assert measurement_tool._measurement.cursor_a_x is not None
        assert measurement_tool._measurement.cursor_a_y is not None
        assert measurement_tool._measurement.cursor_a_y > 0.95  # 峰值 Y 应该接近 1
    
    def test_snap_to_valley(self, measurement_tool):
        """测试吸附到谷值"""
        # 创建有明显谷值的数据
        x_data = np.linspace(0, 10, 100)
        y_data = np.sin(x_data)  # 谷值在 3π/2 ≈ 4.71
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(4.0)  # 设置初始位置
        
        result = measurement_tool.snap_to_valley()
        
        assert result is True
        # 谷值应该在 3π/2 附近
        assert measurement_tool._measurement.cursor_a_x is not None
        assert abs(measurement_tool._measurement.cursor_a_x - 3*np.pi/2) < 0.2
    
    def test_snap_to_zero_crossing(self, measurement_tool):
        """测试吸附到过零点"""
        # 创建有过零点的数据
        x_data = np.linspace(0, 10, 100)
        y_data = np.sin(x_data)  # 过零点在 0, π, 2π, 3π
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(3.0)  # 设置初始位置，接近 π
        
        result = measurement_tool.snap_to_zero_crossing()
        
        assert result is True
        # 过零点应该在 π 附近
        assert measurement_tool._measurement.cursor_a_x is not None
        assert abs(measurement_tool._measurement.cursor_a_x - np.pi) < 0.2
    
    def test_snap_to_minus_3db(self, measurement_tool):
        """测试吸附到 -3dB 点"""
        # 创建模拟频率响应的数据（dB 值）
        x_data = np.logspace(0, 4, 100)  # 1 Hz 到 10 kHz
        # 模拟低通滤波器响应：在截止频率处下降 3dB
        fc = 1000  # 截止频率
        y_data = -10 * np.log10(1 + (x_data / fc) ** 2)  # 一阶低通
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(500)  # 设置初始位置
        
        result = measurement_tool.snap_to_minus_3db()
        
        assert result is True
        # -3dB 点应该在截止频率附近
        assert measurement_tool._measurement.cursor_a_x is not None
        # 允许较大误差，因为是离散数据
        assert abs(measurement_tool._measurement.cursor_a_x - fc) / fc < 0.2
    
    def test_snap_no_data(self, measurement_tool):
        """测试无数据时的快速定位"""
        result = measurement_tool.snap_to_peak()
        assert result is False
        
        result = measurement_tool.snap_to_valley()
        assert result is False
        
        result = measurement_tool.snap_to_zero_crossing()
        assert result is False
        
        result = measurement_tool.snap_to_minus_3db()
        assert result is False


class TestMeasurementToolBinding:
    """测试 MeasurementTool 波形组件绑定"""
    
    def test_bind_waveform_widget(self, measurement_tool):
        """测试绑定波形组件"""
        mock_widget = MagicMock()
        mock_widget.measurement_changed = MagicMock()
        mock_widget.measurement_changed.connect = MagicMock()
        
        measurement_tool.bind_waveform_widget(mock_widget)
        
        assert measurement_tool._waveform_widget is mock_widget
        mock_widget.measurement_changed.connect.assert_called_once()
    
    def test_unbind_waveform_widget(self, measurement_tool):
        """测试解除绑定"""
        mock_widget = MagicMock()
        mock_widget.measurement_changed = MagicMock()
        mock_widget.measurement_changed.connect = MagicMock()
        mock_widget.measurement_changed.disconnect = MagicMock()
        
        measurement_tool.bind_waveform_widget(mock_widget)
        measurement_tool.unbind_waveform_widget()
        
        assert measurement_tool._waveform_widget is None
    
    def test_cursor_sync_to_widget(self, measurement_tool):
        """测试光标同步到波形组件"""
        mock_widget = MagicMock()
        mock_widget.measurement_changed = MagicMock()
        mock_widget.measurement_changed.connect = MagicMock()
        mock_widget.set_cursor_a = MagicMock()
        mock_widget.set_cursor_b = MagicMock()
        
        measurement_tool.bind_waveform_widget(mock_widget)
        
        x_data = np.array([0.0, 1.0, 2.0])
        y_data = np.array([0.0, 1.0, 2.0])
        measurement_tool.set_waveform_data(x_data, y_data)
        
        measurement_tool.set_cursor_a(1.0)
        mock_widget.set_cursor_a.assert_called_with(1.0)
        
        measurement_tool.set_cursor_b(2.0)
        mock_widget.set_cursor_b.assert_called_with(2.0)


class TestMeasurementToolEdgeCases:
    """测试 MeasurementTool 边界情况"""
    
    def test_empty_data(self, measurement_tool):
        """测试空数据"""
        x_data = np.array([])
        y_data = np.array([])
        
        measurement_tool.set_waveform_data(x_data, y_data)
        
        # 应该不会崩溃
        result = measurement_tool._get_y_at_x(1.0)
        assert result is None
    
    def test_single_point_data(self, measurement_tool):
        """测试单点数据"""
        x_data = np.array([1.0])
        y_data = np.array([2.0])
        
        measurement_tool.set_waveform_data(x_data, y_data)
        
        # 插值应该返回该点的值
        result = measurement_tool._get_y_at_x(1.0)
        assert result == pytest.approx(2.0, rel=1e-6)
    
    def test_extrapolation(self, measurement_tool):
        """测试外推"""
        x_data = np.array([0.0, 1.0, 2.0])
        y_data = np.array([0.0, 1.0, 2.0])
        
        measurement_tool.set_waveform_data(x_data, y_data)
        
        # numpy.interp 会在边界外使用边界值
        result = measurement_tool._get_y_at_x(-1.0)
        assert result == pytest.approx(0.0, rel=1e-6)
        
        result = measurement_tool._get_y_at_x(3.0)
        assert result == pytest.approx(2.0, rel=1e-6)
    
    def test_zero_delta_x(self, measurement_tool):
        """测试 ΔX 为零的情况"""
        x_data = np.array([0.0, 1.0, 2.0])
        y_data = np.array([0.0, 1.0, 2.0])
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(1.0)
        measurement_tool.set_cursor_b(1.0)  # 同一位置
        
        values = measurement_tool.get_delta_values()
        
        assert values.delta_x == pytest.approx(0.0, abs=1e-10)
        assert values.slope is None  # 斜率未定义
        assert values.frequency is None  # 频率未定义
    
    def test_no_zero_crossing(self, measurement_tool):
        """测试无过零点的数据"""
        x_data = np.array([0.0, 1.0, 2.0, 3.0])
        y_data = np.array([1.0, 2.0, 3.0, 4.0])  # 全正值
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(1.0)
        
        result = measurement_tool.snap_to_zero_crossing()
        
        assert result is False
    
    def test_flat_data_no_peak(self, measurement_tool):
        """测试平坦数据（无峰值）"""
        x_data = np.array([0.0, 1.0, 2.0, 3.0])
        y_data = np.array([1.0, 1.0, 1.0, 1.0])  # 全相等
        
        measurement_tool.set_waveform_data(x_data, y_data)
        measurement_tool.set_cursor_a(1.0)
        
        # 应该返回全局最大值位置（第一个）
        result = measurement_tool.snap_to_peak()
        
        assert result is True
