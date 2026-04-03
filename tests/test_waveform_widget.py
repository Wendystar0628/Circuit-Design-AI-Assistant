# Test WaveformWidget
"""
波形图表组件测试

测试覆盖：
- WaveformMeasurement 数据类
- WaveformWidget 基本功能
- 波形加载和显示
- 光标测量功能
- 信号管理
"""

import numpy as np
import pytest

from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
)
from presentation.panels.simulation.waveform_widget import (
    WaveformMeasurement,
    WaveformWidget,
    SIGNAL_COLORS,
    INITIAL_POINTS,
)


# ============================================================
# WaveformMeasurement 测试
# ============================================================

class TestWaveformMeasurement:
    """WaveformMeasurement 数据类测试"""
    
    def test_create_empty_measurement(self):
        """测试创建空测量结果"""
        measurement = WaveformMeasurement()
        
        assert measurement.cursor_a_x is None
        assert measurement.cursor_a_y is None
        assert measurement.cursor_b_x is None
        assert measurement.cursor_b_y is None
        assert measurement.delta_x is None
        assert measurement.delta_y is None
        assert measurement.slope is None
        assert measurement.frequency is None
    
    def test_create_single_cursor_measurement(self):
        """测试单光标测量"""
        measurement = WaveformMeasurement(
            cursor_a_x=0.001,
            cursor_a_y=1.5
        )
        
        assert measurement.cursor_a_x == 0.001
        assert measurement.cursor_a_y == 1.5
        assert measurement.has_dual_cursor() is False
    
    def test_create_dual_cursor_measurement(self):
        """测试双光标测量"""
        measurement = WaveformMeasurement(
            cursor_a_x=0.001,
            cursor_a_y=1.0,
            cursor_b_x=0.002,
            cursor_b_y=2.0,
            delta_x=0.001,
            delta_y=1.0,
            slope=1000.0,
            frequency=1000.0
        )
        
        assert measurement.has_dual_cursor() is True
        assert measurement.delta_x == 0.001
        assert measurement.delta_y == 1.0
        assert measurement.slope == 1000.0
        assert measurement.frequency == 1000.0
    
    def test_has_dual_cursor(self):
        """测试双光标判断"""
        # 无光标
        m1 = WaveformMeasurement()
        assert m1.has_dual_cursor() is False
        
        # 只有光标 A
        m2 = WaveformMeasurement(cursor_a_x=0.001)
        assert m2.has_dual_cursor() is False
        
        # 只有光标 B
        m3 = WaveformMeasurement(cursor_b_x=0.002)
        assert m3.has_dual_cursor() is False
        
        # 双光标
        m4 = WaveformMeasurement(cursor_a_x=0.001, cursor_b_x=0.002)
        assert m4.has_dual_cursor() is True


# ============================================================
# 辅助函数
# ============================================================

def create_mock_simulation_result(
    num_points: int = 1000,
    signal_names: list = None
) -> SimulationResult:
    """创建模拟仿真结果"""
    if signal_names is None:
        signal_names = ["V(out)", "V(in)"]
    
    # 生成时间数据
    time = np.linspace(0, 0.01, num_points)
    
    # 生成信号数据
    signals = {}
    for i, name in enumerate(signal_names):
        # 生成正弦波，不同信号有不同频率
        freq = 1000 * (i + 1)
        signals[name] = np.sin(2 * np.pi * freq * time)
    
    sim_data = SimulationData(
        time=time,
        signals=signals
    )
    
    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        success=True,
        data=sim_data,
        timestamp="2026-01-06T10:00:00"
    )


def create_mock_ac_simulation_result() -> SimulationResult:
    frequency = np.logspace(1, 6, 1000)
    v_out = 1 / (1 + 1j * (frequency / 10000))

    sim_data = SimulationData(
        frequency=frequency,
        signals={
            "V(out)": v_out,
            "V(out)_mag": np.abs(v_out),
            "V(out)_phase": np.angle(v_out, deg=True),
            "V(out)_real": np.real(v_out),
            "V(out)_imag": np.imag(v_out),
        },
        signal_types={
            "V(out)": "voltage",
            "V(out)_mag": "voltage",
            "V(out)_phase": "voltage",
            "V(out)_real": "voltage",
            "V(out)_imag": "voltage",
        },
    )

    return SimulationResult(
        executor="spice",
        file_path="ac_test.cir",
        analysis_type="ac",
        success=True,
        data=sim_data,
        timestamp="2026-01-06T10:05:00",
    )


# ============================================================
# WaveformWidget 测试（需要 Qt 环境）
# ============================================================

class TestWaveformWidgetUnit:
    """WaveformWidget 单元测试（不需要 Qt 环境的部分）"""
    
    def test_signal_colors_defined(self):
        """测试信号颜色已定义"""
        assert len(SIGNAL_COLORS) >= 10
        for color in SIGNAL_COLORS:
            assert color.startswith("#")
            assert len(color) == 7
    
    def test_initial_points_reasonable(self):
        """测试初始点数合理"""
        assert INITIAL_POINTS > 0
        assert INITIAL_POINTS <= 1000


# ============================================================
# WaveformWidget GUI 测试（需要 Qt 环境）
# ============================================================

@pytest.fixture
def qt_app():
    """创建 Qt 应用（如果需要）"""
    try:
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app
    except ImportError:
        pytest.skip("PyQt6 not available")


@pytest.fixture
def waveform_widget(qt_app):
    """创建 WaveformWidget 实例"""
    try:
        widget = WaveformWidget()
        yield widget
        widget.close()
    except Exception as e:
        pytest.skip(f"Cannot create WaveformWidget: {e}")


class TestWaveformWidgetGUI:
    """WaveformWidget GUI 测试"""
    
    def test_widget_creation(self, waveform_widget):
        """测试组件创建"""
        assert waveform_widget is not None
    
    def test_load_waveform(self, waveform_widget):
        """测试加载波形"""
        result = create_mock_simulation_result()
        
        success = waveform_widget.load_waveform(result, "V(out)")
        
        assert success is True
        assert "V(out)" in waveform_widget.get_displayed_signals()
    
    def test_add_multiple_waveforms(self, waveform_widget):
        """测试添加多个波形"""
        result = create_mock_simulation_result()
        
        waveform_widget.load_waveform(result, "V(out)", clear_existing=True)
        waveform_widget.add_waveform(result, "V(in)")
        
        signals = waveform_widget.get_displayed_signals()
        assert "V(out)" in signals
        assert "V(in)" in signals

    def test_add_duplicate_waveform_does_not_duplicate_display(self, waveform_widget):
        """测试重复添加同一信号不会重复显示"""
        result = create_mock_simulation_result()

        waveform_widget.load_waveform(result, "V(out)")
        success = waveform_widget.add_waveform(result, "V(out)")

        assert success is True
        assert waveform_widget.get_displayed_signals() == ["V(out)"]
        assert len(waveform_widget._plot_items) == 1
    
    def test_remove_waveform(self, waveform_widget):
        """测试移除波形"""
        result = create_mock_simulation_result()
        
        waveform_widget.load_waveform(result, "V(out)")
        waveform_widget.add_waveform(result, "V(in)")
        
        success = waveform_widget.remove_waveform("V(out)")
        
        assert success is True
        assert "V(out)" not in waveform_widget.get_displayed_signals()
        assert "V(in)" in waveform_widget.get_displayed_signals()
    
    def test_clear_waveforms(self, waveform_widget):
        """测试清空波形"""
        result = create_mock_simulation_result()
        
        waveform_widget.load_waveform(result, "V(out)")
        waveform_widget.add_waveform(result, "V(in)")
        waveform_widget.clear_waveforms()
        
        assert len(waveform_widget.get_displayed_signals()) == 0

    def test_clear_all_signals_preserves_result_context(self, waveform_widget):
        """测试清除显示信号后仍可继续从当前结果添加新曲线"""
        result = create_mock_simulation_result()

        waveform_widget.load_waveform(result, "V(out)")
        waveform_widget._on_clear_all_signals()

        assert waveform_widget.get_displayed_signals() == []
        assert waveform_widget._current_result is result

        success = waveform_widget.add_waveform(result, "V(in)")
        assert success is True
        assert waveform_widget.get_displayed_signals() == ["V(in)"]

    def test_add_waveform_uses_current_viewport_range(self, waveform_widget):
        """测试在当前视口中新增曲线时使用当前视口范围的数据"""
        result = create_mock_simulation_result()

        waveform_widget.load_waveform(result, "V(out)")
        waveform_widget._pending_range = (0.002, 0.004)

        success = waveform_widget.add_waveform(result, "V(in)")

        assert success is True
        waveform_data = waveform_widget._plot_items["V(in)"].waveform_data
        assert waveform_data is not None
        assert float(waveform_data.x_data.min()) >= 0.002 - 1e-9
        assert float(waveform_data.x_data.max()) <= 0.004 + 1e-9
    
    def test_set_cursor_a(self, waveform_widget):
        """测试设置光标 A"""
        result = create_mock_simulation_result()
        waveform_widget.load_waveform(result, "V(out)")
        
        waveform_widget.set_cursor_a(0.005)
        
        measurement = waveform_widget.get_measurement()
        assert measurement.cursor_a_x == 0.005
        assert measurement.cursor_a_y is not None
    
    def test_set_cursor_b(self, waveform_widget):
        """测试设置光标 B"""
        result = create_mock_simulation_result()
        waveform_widget.load_waveform(result, "V(out)")
        
        waveform_widget.set_cursor_b(0.006)
        
        measurement = waveform_widget.get_measurement()
        assert measurement.cursor_b_x == 0.006
        assert measurement.cursor_b_y is not None
    
    def test_dual_cursor_measurement(self, waveform_widget):
        """测试双光标测量"""
        result = create_mock_simulation_result()
        waveform_widget.load_waveform(result, "V(out)")
        
        waveform_widget.set_cursor_a(0.001)
        waveform_widget.set_cursor_b(0.002)
        
        measurement = waveform_widget.get_measurement()
        
        assert measurement.has_dual_cursor() is True
        assert measurement.delta_x == pytest.approx(0.001, rel=1e-6)
        assert measurement.frequency is not None
        assert measurement.frequency == pytest.approx(1000.0, rel=1e-6)
    
    def test_load_nonexistent_signal(self, waveform_widget):
        """测试加载不存在的信号"""
        result = create_mock_simulation_result()
        
        success = waveform_widget.load_waveform(result, "V(nonexistent)")
        
        assert success is False

    def test_load_ac_complex_signal_uses_magnitude_display_signal(self, waveform_widget):
        result = create_mock_ac_simulation_result()

        success = waveform_widget.load_waveform(result, "V(out)")

        assert success is True
        assert waveform_widget.get_displayed_signals() == ["V(out)_mag"]

    def test_remove_ac_waveform_by_base_signal_name(self, waveform_widget):
        result = create_mock_ac_simulation_result()
        waveform_widget.load_waveform(result, "V(out)")

        success = waveform_widget.remove_waveform("V(out)")

        assert success is True
        assert waveform_widget.get_displayed_signals() == []
    
    def test_get_measurement_empty(self, waveform_widget):
        """测试空状态下获取测量"""
        measurement = waveform_widget.get_measurement()
        
        assert measurement.cursor_a_x is None
        assert measurement.cursor_b_x is None
        assert measurement.has_dual_cursor() is False
    
    def test_auto_range(self, waveform_widget):
        """测试自动范围"""
        result = create_mock_simulation_result()
        waveform_widget.load_waveform(result, "V(out)")
        
        # 应该不抛出异常
        waveform_widget.auto_range()
