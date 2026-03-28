# test_simulation_tab_timestamp.py
"""
测试仿真面板时间戳显示功能

测试内容：
- MetricsSummaryPanel 时间戳格式化
- MetricsSummaryPanel 时间戳显示/隐藏
- SimulationTab 空状态 UI
"""

import pytest
from datetime import datetime


@pytest.fixture(scope="module")
def qapp():
    """创建 Qt 应用实例"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestLeftPanelTimestamp:
    """测试 MetricsSummaryPanel 时间戳功能"""
    
    def test_format_timestamp_iso_format(self, qapp):
        """测试 ISO 格式时间戳转换"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        # 测试标准 ISO 格式
        result = panel._format_timestamp("2026-01-06T14:30:22")
        assert result == "2026-01-06 14:30:22"
    
    def test_format_timestamp_with_timezone(self, qapp):
        """测试带时区的 ISO 格式"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        # 测试带 Z 后缀的 UTC 时间
        result = panel._format_timestamp("2026-01-06T14:30:22Z")
        assert "2026-01-06" in result
        assert "14:30:22" in result or ":" in result  # 可能有时区转换
    
    def test_format_timestamp_empty_string(self, qapp):
        """测试空字符串"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        result = panel._format_timestamp("")
        assert result == ""
    
    def test_format_timestamp_invalid_format(self, qapp):
        """测试无效格式返回原始字符串"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        invalid_str = "not-a-timestamp"
        result = panel._format_timestamp(invalid_str)
        assert result == invalid_str
    
    def test_set_result_timestamp(self, qapp):
        """测试设置时间戳"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        # 设置时间戳
        panel.set_result_timestamp("2026-01-06T14:30:22")
        
        # 验证顶部信息栏没有被隐藏（isHidden 检查组件本身的隐藏状态，而非父组件）
        assert not panel._header_bar.isHidden()
        
        # 验证文本包含格式化后的时间
        label_text = panel._timestamp_label.text()
        assert "2026-01-06" in label_text
    
    def test_clear_result_timestamp(self, qapp):
        """测试清空时间戳"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        # 先设置时间戳
        panel.set_result_timestamp("2026-01-06T14:30:22")
        assert not panel._header_bar.isHidden()
        
        # 清空时间戳
        panel.clear_result_timestamp()
        
        # 验证顶部信息栏隐藏
        assert panel._header_bar.isHidden()
        assert panel._timestamp_label.text() == ""
    
    def test_clear_includes_timestamp(self, qapp):
        """测试 clear 方法包含清空时间戳"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        # 先设置时间戳
        panel.set_result_timestamp("2026-01-06T14:30:22")
        
        # 调用 clear
        panel.clear()
        
        # 验证时间戳被清空
        assert panel._header_bar.isHidden()


class TestSimulationTabEmptyState:
    """测试 SimulationTab 空状态功能"""
    
    def test_empty_state_has_load_history_button(self, qapp):
        """测试空状态包含加载历史按钮"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        # 验证加载历史按钮存在
        assert hasattr(tab, '_load_history_btn')
        assert tab._load_history_btn is not None
    
    def test_show_empty_state_shows_button(self, qapp):
        """测试显示空状态时按钮没有被隐藏"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        tab._show_empty_state()
        
        # 验证按钮没有被隐藏
        assert not tab._load_history_btn.isHidden()
    
    def test_show_file_missing_state_hides_button(self, qapp):
        """测试文件丢失状态时按钮隐藏"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        tab._show_file_missing_state()
        
        # 验证按钮隐藏
        assert tab._load_history_btn.isHidden()


class TestSvgIconsExist:
    """测试 SVG 图标文件存在"""
    
    def test_clock_svg_exists(self):
        """测试时钟图标存在"""
        from pathlib import Path
        
        icon_path = Path(__file__).parent.parent / "resources" / "icons" / "simulation" / "clock.svg"
        assert icon_path.exists(), f"Missing icon: {icon_path}"
    
    def test_chart_empty_svg_exists(self):
        """测试空图表图标存在"""
        from pathlib import Path
        
        icon_path = Path(__file__).parent.parent / "resources" / "icons" / "simulation" / "chart-empty.svg"
        assert icon_path.exists(), f"Missing icon: {icon_path}"
    
    def test_file_missing_svg_exists(self):
        """测试文件丢失图标存在"""
        from pathlib import Path
        
        icon_path = Path(__file__).parent.parent / "resources" / "icons" / "simulation" / "file-missing.svg"
        assert icon_path.exists(), f"Missing icon: {icon_path}"
