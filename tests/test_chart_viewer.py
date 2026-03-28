# Test ChartViewer
"""
图表查看器测试

测试内容：
- 图表标签设置和切换
- 图表加载和显示
- 缩放功能
- 导出功能
- 测量模式
- 数据导出
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QApplication

from presentation.panels.simulation.chart_viewer import (
    ChartViewer,
    ZoomableImageLabel,
    MeasurementInfoBar,
    MeasurementMode,
    MeasurementResult,
    CursorPosition,
    ZOOM_MIN,
    ZOOM_MAX,
    ZOOM_STEP,
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
def chart_viewer(app):
    """创建 ChartViewer 实例"""
    viewer = ChartViewer()
    yield viewer
    viewer.deleteLater()


@pytest.fixture
def zoomable_label(app):
    """创建 ZoomableImageLabel 实例"""
    label = ZoomableImageLabel()
    yield label
    label.deleteLater()


@pytest.fixture
def measurement_bar(app):
    """创建 MeasurementInfoBar 实例"""
    bar = MeasurementInfoBar()
    yield bar
    bar.deleteLater()


@pytest.fixture
def temp_chart_file(app):
    """创建临时图表文件"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / "test_chart.png"
    
    # 创建简单的测试图片
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    image.save(str(temp_path), "PNG")
    
    yield str(temp_path)
    
    # 清理
    temp_path.unlink(missing_ok=True)
    Path(temp_dir).rmdir()


# ============================================================
# ZoomableImageLabel 测试
# ============================================================

class TestZoomableImageLabel:
    """ZoomableImageLabel 测试类"""
    
    def test_initial_state(self, zoomable_label):
        """测试初始状态"""
        assert zoomable_label.get_zoom_level() == 1.0
        assert zoomable_label.pixmap() is None or zoomable_label.pixmap().isNull()
    
    def test_set_pixmap(self, zoomable_label, temp_chart_file):
        """测试设置图片"""
        pixmap = QPixmap(temp_chart_file)
        zoomable_label.set_pixmap(pixmap)
        
        assert zoomable_label.get_zoom_level() == 1.0
        assert zoomable_label.pixmap() is not None
    
    def test_zoom_in(self, zoomable_label, temp_chart_file):
        """测试放大"""
        pixmap = QPixmap(temp_chart_file)
        zoomable_label.set_pixmap(pixmap)
        
        initial_zoom = zoomable_label.get_zoom_level()
        zoomable_label.zoom_in()
        
        assert zoomable_label.get_zoom_level() > initial_zoom
    
    def test_zoom_out(self, zoomable_label, temp_chart_file):
        """测试缩小"""
        pixmap = QPixmap(temp_chart_file)
        zoomable_label.set_pixmap(pixmap)
        
        # 先放大
        zoomable_label.set_zoom_level(2.0)
        
        initial_zoom = zoomable_label.get_zoom_level()
        zoomable_label.zoom_out()
        
        assert zoomable_label.get_zoom_level() < initial_zoom
    
    def test_zoom_limits(self, zoomable_label):
        """测试缩放限制"""
        # 测试最小值
        zoomable_label.set_zoom_level(0.01)
        assert zoomable_label.get_zoom_level() >= ZOOM_MIN
        
        # 测试最大值
        zoomable_label.set_zoom_level(100.0)
        assert zoomable_label.get_zoom_level() <= ZOOM_MAX
    
    def test_reset_view(self, zoomable_label, temp_chart_file):
        """测试重置视图"""
        pixmap = QPixmap(temp_chart_file)
        zoomable_label.set_pixmap(pixmap)
        
        # 修改缩放
        zoomable_label.set_zoom_level(2.0)
        assert zoomable_label.get_zoom_level() == 2.0
        
        # 重置
        zoomable_label.reset_view()
        assert zoomable_label.get_zoom_level() == 1.0
    
    def test_zoom_changed_signal(self, zoomable_label, temp_chart_file):
        """测试缩放变化信号"""
        pixmap = QPixmap(temp_chart_file)
        zoomable_label.set_pixmap(pixmap)
        
        signal_received = []
        zoomable_label.zoom_changed.connect(lambda level: signal_received.append(level))
        
        zoomable_label.set_zoom_level(1.5)
        
        assert len(signal_received) == 1
        assert signal_received[0] == 1.5
    
    def test_measurement_mode(self, zoomable_label):
        """测试测量模式设置"""
        assert zoomable_label.get_measurement_mode() == MeasurementMode.NONE
        
        zoomable_label.set_measurement_mode(MeasurementMode.DUAL_CURSOR)
        assert zoomable_label.get_measurement_mode() == MeasurementMode.DUAL_CURSOR
        
        zoomable_label.set_measurement_mode(MeasurementMode.NONE)
        assert zoomable_label.get_measurement_mode() == MeasurementMode.NONE


# ============================================================
# MeasurementInfoBar 测试
# ============================================================

class TestMeasurementInfoBar:
    """MeasurementInfoBar 测试类"""
    
    def test_initial_state(self, measurement_bar):
        """测试初始状态"""
        assert measurement_bar.isHidden()
    
    def test_update_measurement(self, measurement_bar):
        """测试更新测量结果"""
        result = MeasurementResult(
            cursor1=CursorPosition(x=1.0, y=2.0),
            cursor2=CursorPosition(x=3.0, y=4.0),
            delta_x=2.0,
            delta_y=2.0,
            slope=1.0,
            frequency=0.5,
        )
        
        measurement_bar.update_measurement(result)
        
        # 检查数值已更新（不是 "--"）
        assert measurement_bar._value_cursor1.text() != "--"
        assert measurement_bar._value_cursor2.text() != "--"
        assert measurement_bar._value_delta_x.text() != "--"
    
    def test_clear_measurement(self, measurement_bar):
        """测试清空测量结果"""
        result = MeasurementResult(
            cursor1=CursorPosition(x=1.0, y=2.0),
            delta_x=2.0,
        )
        measurement_bar.update_measurement(result)
        
        measurement_bar.clear_measurement()
        
        assert measurement_bar._value_cursor1.text() == "--"
        assert measurement_bar._value_delta_x.text() == "--"
    
    def test_retranslate_ui(self, measurement_bar):
        """测试国际化"""
        measurement_bar.retranslate_ui()
        # 应该不抛出异常
        assert measurement_bar._label_cursor1.text() != ""


# ============================================================
# ChartViewer 测试
# ============================================================

class TestChartViewer:
    """ChartViewer 测试类"""
    
    def test_initial_state(self, chart_viewer):
        """测试初始状态"""
        assert chart_viewer.get_current_chart_type() is None
        assert chart_viewer.get_current_chart_path() is None
    
    def test_set_chart_tabs(self, chart_viewer):
        """测试设置图表标签"""
        chart_types = ["bode_combined", "waveform_time", "dc_transfer"]
        chart_viewer.set_chart_tabs(chart_types)
        
        assert chart_viewer._tab_bar.count() == 3
        assert chart_viewer.get_current_chart_type() == "bode_combined"
    
    def test_set_empty_chart_tabs(self, chart_viewer):
        """测试设置空标签"""
        chart_viewer.set_chart_tabs([])
        
        assert chart_viewer._tab_bar.count() == 0
    
    def test_load_chart(self, chart_viewer, temp_chart_file):
        """测试加载图表"""
        chart_viewer.load_chart(temp_chart_file, "test_chart")
        
        assert chart_viewer._chart_paths.get("test_chart") == temp_chart_file
    
    def test_load_nonexistent_chart(self, chart_viewer):
        """测试加载不存在的图表"""
        chart_viewer.load_chart("/nonexistent/path.png")
        
        # 检查空状态标签应该显示（通过检查 scroll_area 是否隐藏）
        assert chart_viewer._scroll_area.isHidden()
        assert not chart_viewer._empty_label.isHidden()
    
    def test_load_charts_batch(self, chart_viewer, temp_chart_file):
        """测试批量加载图表"""
        chart_paths = {
            "bode_combined": temp_chart_file,
            "waveform_time": temp_chart_file,
        }
        
        chart_viewer.load_charts(chart_paths)
        
        assert chart_viewer._tab_bar.count() == 2
        assert chart_viewer.get_current_chart_type() == "bode_combined"
        assert chart_viewer.get_current_chart_path() == temp_chart_file
    
    def test_clear(self, chart_viewer, temp_chart_file):
        """测试清空"""
        chart_viewer.load_charts({"test": temp_chart_file})
        chart_viewer.clear()
        
        assert chart_viewer._tab_bar.count() == 0
        assert chart_viewer.get_current_chart_type() is None
        assert chart_viewer.get_current_chart_path() is None
    
    def test_tab_changed_signal(self, chart_viewer, temp_chart_file):
        """测试标签切换信号"""
        chart_paths = {
            "bode_combined": temp_chart_file,
            "waveform_time": temp_chart_file,
        }
        chart_viewer.load_charts(chart_paths)
        
        signal_received = []
        chart_viewer.tab_changed.connect(lambda t: signal_received.append(t))
        
        # 切换到第二个标签
        chart_viewer._tab_bar.setCurrentIndex(1)
        
        assert len(signal_received) == 1
        assert signal_received[0] == "waveform_time"
    
    def test_zoom_controls(self, chart_viewer, temp_chart_file):
        """测试缩放控制"""
        chart_viewer.load_chart(temp_chart_file)
        
        initial_zoom = chart_viewer._image_label.get_zoom_level()
        
        chart_viewer.zoom_in()
        assert chart_viewer._image_label.get_zoom_level() > initial_zoom
        
        chart_viewer.reset_zoom()
        assert chart_viewer._image_label.get_zoom_level() == 1.0
    
    def test_export_chart(self, chart_viewer, temp_chart_file):
        """测试导出图表"""
        chart_viewer.load_chart(temp_chart_file, "test")
        chart_viewer._current_chart_type = "test"
        
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            export_path = f.name
        
        try:
            result = chart_viewer.export_chart(export_path)
            assert result is True
            assert Path(export_path).exists()
        finally:
            Path(export_path).unlink(missing_ok=True)
    
    def test_export_chart_no_chart(self, chart_viewer):
        """测试无图表时导出"""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            export_path = f.name
        
        try:
            result = chart_viewer.export_chart(export_path)
            assert result is False
        finally:
            Path(export_path).unlink(missing_ok=True)
    
    def test_copy_to_clipboard(self, chart_viewer, temp_chart_file):
        """测试复制到剪贴板"""
        chart_viewer.load_chart(temp_chart_file)
        
        result = chart_viewer.copy_to_clipboard()
        assert result is True
    
    def test_copy_to_clipboard_no_chart(self, chart_viewer):
        """测试无图表时复制"""
        result = chart_viewer.copy_to_clipboard()
        assert result is False
    
    def test_retranslate_ui(self, chart_viewer):
        """测试国际化"""
        # 应该不抛出异常
        chart_viewer.retranslate_ui()
        
        # 检查文本已设置
        assert chart_viewer._empty_label.text() != ""
        assert chart_viewer._action_zoom_in.text() != ""
        assert chart_viewer._action_measure.text() != ""
        assert chart_viewer._action_export_data.text() != ""
    
    def test_get_chart_display_name(self, chart_viewer):
        """测试获取图表显示名称"""
        # 测试已知类型
        name = chart_viewer._get_chart_display_name("bode_combined")
        assert name != ""
        
        # 测试未知类型
        name = chart_viewer._get_chart_display_name("unknown_type")
        assert name == "Unknown Type"
    
    def test_measurement_mode(self, chart_viewer):
        """测试测量模式"""
        assert not chart_viewer.is_measurement_mode()
        assert chart_viewer.get_measurement_mode() == MeasurementMode.NONE
        
        chart_viewer.enter_measurement_mode()
        assert chart_viewer.is_measurement_mode()
        assert chart_viewer.get_measurement_mode() == MeasurementMode.DUAL_CURSOR
        # 检查测量栏不是隐藏状态（isHidden 检查的是 hide() 是否被调用）
        assert not chart_viewer._measurement_bar.isHidden()
        
        chart_viewer.exit_measurement_mode()
        assert not chart_viewer.is_measurement_mode()
        assert chart_viewer._measurement_bar.isHidden()
    
    def test_measurement_mode_signal(self, chart_viewer):
        """测试测量模式变化信号"""
        signal_received = []
        chart_viewer.measurement_mode_changed.connect(lambda m: signal_received.append(m))
        
        chart_viewer.enter_measurement_mode()
        assert len(signal_received) == 1
        assert signal_received[0] == MeasurementMode.DUAL_CURSOR.value
        
        chart_viewer.exit_measurement_mode()
        assert len(signal_received) == 2
        assert signal_received[1] == MeasurementMode.NONE.value
    
    def test_update_measurement_result(self, chart_viewer):
        """测试更新测量结果"""
        chart_viewer.enter_measurement_mode()
        
        result = MeasurementResult(
            cursor1=CursorPosition(x=1.0, y=2.0),
            delta_x=2.0,
        )
        chart_viewer.update_measurement_result(result)
        
        # 检查测量栏已更新
        assert chart_viewer._measurement_bar._value_cursor1.text() != "--"
    
    def test_set_measurement_click_handler(self, chart_viewer):
        """测试设置测量点击处理器"""
        handler_called = []
        
        def handler(x, y):
            handler_called.append((x, y))
        
        chart_viewer.set_measurement_click_handler(handler)
        assert chart_viewer._on_measurement_click == handler
    
    def test_set_simulation_data(self, chart_viewer):
        """测试设置仿真数据"""
        mock_data = MagicMock()
        chart_viewer.set_simulation_data(mock_data)
        assert chart_viewer._simulation_data == mock_data
    
    def test_export_data_no_data(self, chart_viewer):
        """测试无数据时导出"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            export_path = f.name
        
        try:
            result = chart_viewer.export_data("csv", export_path)
            assert result is False
        finally:
            Path(export_path).unlink(missing_ok=True)
    
    def test_export_data_csv(self, chart_viewer):
        """测试 CSV 数据导出"""
        import numpy as np
        
        # 创建模拟数据
        mock_data = MagicMock()
        mock_data.time = np.array([0.0, 0.1, 0.2])
        mock_data.frequency = None
        mock_data.signals = {"v_out": np.array([1.0, 2.0, 3.0])}
        
        chart_viewer.set_simulation_data(mock_data)
        
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            export_path = f.name
        
        try:
            result = chart_viewer.export_data("csv", export_path)
            assert result is True
            assert Path(export_path).exists()
            
            # 检查文件内容
            content = Path(export_path).read_text()
            assert "time" in content
            assert "v_out" in content
        finally:
            Path(export_path).unlink(missing_ok=True)
    
    def test_export_data_json(self, chart_viewer):
        """测试 JSON 数据导出"""
        import numpy as np
        import json
        
        # 创建模拟数据
        mock_data = MagicMock()
        mock_data.time = np.array([0.0, 0.1, 0.2])
        mock_data.frequency = None
        mock_data.signals = {"v_out": np.array([1.0, 2.0, 3.0])}
        
        chart_viewer.set_simulation_data(mock_data)
        
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            export_path = f.name
        
        try:
            result = chart_viewer.export_data("json", export_path)
            assert result is True
            assert Path(export_path).exists()
            
            # 检查文件内容
            with open(export_path, "r") as f:
                data = json.load(f)
            assert "time" in data
            assert "signals" in data
            assert "v_out" in data["signals"]
        finally:
            Path(export_path).unlink(missing_ok=True)
    
    def test_data_exported_signal(self, chart_viewer):
        """测试数据导出信号"""
        import numpy as np
        
        mock_data = MagicMock()
        mock_data.time = np.array([0.0, 0.1])
        mock_data.frequency = None
        mock_data.signals = {"v_out": np.array([1.0, 2.0])}
        
        chart_viewer.set_simulation_data(mock_data)
        
        signal_received = []
        chart_viewer.data_exported.connect(lambda p: signal_received.append(p))
        
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            export_path = f.name
        
        try:
            chart_viewer.export_data("csv", export_path)
            assert len(signal_received) == 1
            assert signal_received[0] == export_path
        finally:
            Path(export_path).unlink(missing_ok=True)


# ============================================================
# 集成测试
# ============================================================

class TestChartViewerIntegration:
    """ChartViewer 集成测试"""
    
    def test_full_workflow(self, chart_viewer, temp_chart_file):
        """测试完整工作流程"""
        # 1. 设置标签
        chart_types = ["bode_combined", "waveform_time"]
        chart_viewer.set_chart_tabs(chart_types)
        
        # 2. 加载图表
        chart_viewer.load_chart(temp_chart_file, "bode_combined")
        chart_viewer.load_chart(temp_chart_file, "waveform_time")
        
        # 3. 验证初始状态
        assert chart_viewer.get_current_chart_type() == "bode_combined"
        
        # 4. 切换标签
        chart_viewer._tab_bar.setCurrentIndex(1)
        assert chart_viewer.get_current_chart_type() == "waveform_time"
        
        # 5. 缩放操作
        chart_viewer.zoom_in()
        chart_viewer.zoom_in()
        assert chart_viewer._image_label.get_zoom_level() > 1.0
        
        # 6. 重置
        chart_viewer.reset_zoom()
        assert chart_viewer._image_label.get_zoom_level() == 1.0
        
        # 7. 清空
        chart_viewer.clear()
        assert chart_viewer.get_current_chart_type() is None
    
    def test_measurement_workflow(self, chart_viewer, temp_chart_file):
        """测试测量工作流程"""
        # 加载图表
        chart_viewer.load_chart(temp_chart_file)
        
        # 进入测量模式
        chart_viewer.enter_measurement_mode()
        assert chart_viewer.is_measurement_mode()
        # 检查测量栏不是隐藏状态
        assert not chart_viewer._measurement_bar.isHidden()
        
        # 更新测量结果
        result = MeasurementResult(
            cursor1=CursorPosition(x=0.0, y=1.0),
            cursor2=CursorPosition(x=1.0, y=2.0),
            delta_x=1.0,
            delta_y=1.0,
            slope=1.0,
            frequency=1.0,
        )
        chart_viewer.update_measurement_result(result)
        
        # 退出测量模式
        chart_viewer.exit_measurement_mode()
        assert not chart_viewer.is_measurement_mode()
        assert chart_viewer._measurement_bar.isHidden()


# ============================================================
# CursorPosition 和 MeasurementResult 测试
# ============================================================

class TestDataClasses:
    """数据类测试"""
    
    def test_cursor_position_display_string(self):
        """测试光标位置显示字符串"""
        pos = CursorPosition(x=1.5, y=2.5, signal_name="v_out")
        display = pos.to_display_string("s", "V")
        assert "1.5" in display
        assert "2.5" in display
        assert "s" in display
        assert "V" in display
    
    def test_measurement_result_has_dual_cursor(self):
        """测试测量结果双光标检查"""
        # 无光标
        result1 = MeasurementResult()
        assert not result1.has_dual_cursor()
        
        # 单光标
        result2 = MeasurementResult(cursor1=CursorPosition(x=0, y=0))
        assert not result2.has_dual_cursor()
        
        # 双光标
        result3 = MeasurementResult(
            cursor1=CursorPosition(x=0, y=0),
            cursor2=CursorPosition(x=1, y=1),
        )
        assert result3.has_dual_cursor()


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
