# test_waveform_integration.py - 波形工具集成测试
"""
测试波形工具在仿真面板中的集成
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

# 跳过 GUI 测试如果没有显示器
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("PyQt6.QtWidgets", reason="PyQt6 not available"),
    reason="PyQt6 not available"
)


@pytest.fixture
def qapp():
    """创建 Qt 应用实例"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_simulation_result():
    """创建模拟的仿真结果"""
    from domain.simulation.models.simulation_result import (
        SimulationResult, SimulationData
    )
    
    # 创建测试数据
    time = np.linspace(0, 1e-3, 1000)
    v_out = np.sin(2 * np.pi * 1000 * time)
    v_in = np.cos(2 * np.pi * 1000 * time)
    
    data = SimulationData(
        time=time,
        signals={"V(out)": v_out, "V(in)": v_in}
    )
    
    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        success=True,
        data=data,
        timestamp="2026-01-06T12:00:00",
        raw_output="Test simulation output\nCompleted successfully"
    )


class TestChartViewerPanelIntegration:
    """测试 ChartViewerPanel 集成"""
    
    def test_panel_has_all_tabs(self, qapp):
        """测试面板包含所有标签页"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        
        # 验证标签页数量
        assert panel._tab_widget.count() == 4
        
        # 验证各组件存在
        assert panel.chart_viewer is not None
        assert panel.waveform_widget is not None
        assert panel.raw_data_table is not None
        assert panel.output_log_viewer is not None
    
    def test_switch_tabs(self, qapp):
        """测试标签页切换"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        
        # 切换到波形标签页
        panel.switch_to_waveform()
        assert panel._tab_widget.currentIndex() == ChartViewerPanel.TAB_WAVEFORM
        
        # 切换到原始数据标签页
        panel.switch_to_raw_data()
        assert panel._tab_widget.currentIndex() == ChartViewerPanel.TAB_RAW_DATA
        
        # 切换到日志标签页
        panel.switch_to_log()
        assert panel._tab_widget.currentIndex() == ChartViewerPanel.TAB_LOG
        
        # 切换回图表标签页
        panel.switch_to_chart()
        assert panel._tab_widget.currentIndex() == ChartViewerPanel.TAB_CHART
    
    def test_clear_all(self, qapp):
        """测试清空所有内容"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        
        # 清空不应抛出异常
        panel.clear()


class TestSimulationTabWaveformIntegration:
    """测试 SimulationTab 波形集成"""
    
    def test_get_waveform_widget(self, qapp):
        """测试获取波形组件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        waveform = tab.get_waveform_widget()
        assert waveform is not None
    
    def test_get_raw_data_table(self, qapp):
        """测试获取原始数据表格"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        table = tab.get_raw_data_table()
        assert table is not None
    
    def test_get_output_log_viewer(self, qapp):
        """测试获取输出日志查看器"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        viewer = tab.get_output_log_viewer()
        assert viewer is not None
    
    def test_load_result_populates_components(self, qapp, mock_simulation_result):
        """测试加载结果时填充各组件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        # 加载结果
        tab.load_result(mock_simulation_result)
        
        # 验证波形组件有数据
        waveform = tab.get_waveform_widget()
        displayed_signals = waveform.get_displayed_signals()
        assert len(displayed_signals) > 0


class TestDataExportIntegration:
    """测试数据导出集成"""
    
    def test_export_waveform_data_no_result(self, qapp):
        """测试无数据时导出"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        # 无数据时导出应该显示警告（不抛出异常）
        with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warning:
            tab.export_waveform_data("csv")
            # 应该调用了警告对话框
            mock_warning.assert_called_once()
    
    def test_export_formats_available(self):
        """测试导出格式可用"""
        from domain.simulation.data.data_exporter import data_exporter
        
        formats = data_exporter.get_supported_formats()
        
        assert "csv" in formats
        assert "json" in formats
        assert "mat" in formats
        assert "npy" in formats
        assert "npz" in formats


class TestActionHandlersExport:
    """测试 ActionHandlers 导出回调"""
    
    def test_export_callbacks_exist(self, qapp):
        """测试导出回调存在"""
        from presentation.action_handlers import ActionHandlers
        
        handlers = ActionHandlers(MagicMock(), {})
        callbacks = handlers.get_callbacks()
        
        assert "on_export_csv" in callbacks
        assert "on_export_json" in callbacks
        assert "on_export_matlab" in callbacks
        assert "on_export_numpy" in callbacks
    
    def test_export_csv_with_simulation_tab(self, qapp, mock_simulation_result):
        """测试通过 ActionHandlers 导出 CSV"""
        from presentation.action_handlers import ActionHandlers
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        # 创建仿真标签页并加载数据
        sim_tab = SimulationTab()
        sim_tab.load_result(mock_simulation_result)
        
        # 创建 ActionHandlers
        panels = {"simulation": sim_tab}
        handlers = ActionHandlers(MagicMock(), panels)
        
        # 模拟文件对话框取消
        with patch('PyQt6.QtWidgets.QFileDialog.getSaveFileName', return_value=("", "")):
            handlers.on_export_csv()
            # 不应抛出异常
