# Test SimulationTab
"""
SimulationTab 单元测试

测试仿真结果标签页的核心功能：
- UI 组件初始化
- 指标更新
- 图表加载
- 状态切换
- 事件响应
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


# 确保 QApplication 实例存在
@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_event_bus():
    """模拟 EventBus"""
    mock = MagicMock()
    mock.subscribe = MagicMock()
    mock.unsubscribe = MagicMock()
    mock.publish = MagicMock()
    return mock


@pytest.fixture
def mock_service_locator(mock_event_bus):
    """模拟 ServiceLocator"""
    with patch("shared.service_locator.ServiceLocator") as mock_locator:
        mock_locator.get_optional = MagicMock(return_value=mock_event_bus)
        yield mock_locator


@pytest.fixture
def mock_simulation_result():
    from domain.simulation.models.simulation_result import SimulationResult, SimulationData

    time = np.linspace(0, 1e-3, 100)
    data = SimulationData(
        time=time,
        signals={
            "V(out)": np.sin(2 * np.pi * 1000 * time),
            "V(in)": np.cos(2 * np.pi * 1000 * time),
        },
    )

    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        success=True,
        data=data,
        timestamp="2026-01-06T12:00:00",
        raw_output="ok",
    )


class TestStatusIndicator:
    """StatusIndicator 测试"""
    
    def test_init(self, app):
        """测试初始化"""
        from presentation.panels.simulation.simulation_tab import StatusIndicator
        
        indicator = StatusIndicator()
        
        assert indicator is not None
        assert not indicator.isVisible()
    
    def test_show_awaiting_confirmation(self, app):
        """测试显示等待确认状态"""
        from presentation.panels.simulation.simulation_tab import StatusIndicator
        
        indicator = StatusIndicator()
        indicator.show_awaiting_confirmation()
        
        assert indicator.isVisible()
    
    def test_show_running(self, app):
        """测试显示运行中状态"""
        from presentation.panels.simulation.simulation_tab import StatusIndicator
        
        indicator = StatusIndicator()
        indicator.show_running("测试运行中")
        
        assert indicator.isVisible()
    
    def test_hide_status(self, app):
        """测试隐藏状态"""
        from presentation.panels.simulation.simulation_tab import StatusIndicator
        
        indicator = StatusIndicator()
        indicator.show_running()
        indicator.hide_status()
        
        assert not indicator.isVisible()


class TestMetricsSummaryPanel:
    """MetricsSummaryPanel 测试"""
    
    def test_init(self, app):
        """测试初始化"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        assert panel is not None
        assert panel.metrics_panel is not None
    
    def test_update_metrics(self, app):
        """测试更新指标"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        panel = MetricsSummaryPanel()
        
        metrics = [
            DisplayMetric(
                name="gain",
                display_name="增益",
                value="20.5 dB",
                unit="dB",
                target="≥ 20 dB",
                is_met=True,
                trend="up",
                category="gain",
            ),
        ]
        
        panel.update_metrics(metrics)
        
        assert panel.metrics_panel.card_count == 1
    
    def test_set_overall_score(self, app):
        """测试设置综合评分"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        panel.set_overall_score(85.5)
        
        # 检查顶部信息栏的分数值
        assert panel._overall_score == 85.5
    
    def test_clear(self, app):
        """测试清空"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        panel = MetricsSummaryPanel()
        
        metrics = [
            DisplayMetric(
                name="gain",
                display_name="增益",
                value="20.5 dB",
                unit="dB",
                target="≥ 20 dB",
                is_met=True,
                trend="up",
                category="gain",
            ),
        ]
        
        panel.update_metrics(metrics)
        panel.clear()
        
        assert panel.metrics_panel.card_count == 0
    
    def test_history_clicked_signal(self, app):
        """测试历史按钮点击信号"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        signal_received = []
        panel.history_clicked.connect(lambda: signal_received.append(True))
        
        # 模拟点击
        panel._history_btn.click()
        
        assert len(signal_received) == 1
    
    def test_header_bar_visibility(self, app):
        """测试顶部信息栏显示/隐藏"""
        from presentation.panels.simulation.simulation_tab import MetricsSummaryPanel
        
        panel = MetricsSummaryPanel()
        
        # 默认隐藏
        assert panel._header_bar.isHidden()
        
        # 设置时间戳后显示
        panel.set_result_timestamp("2026-01-06T14:30:22")
        assert not panel._header_bar.isHidden()
        
        # 清空后隐藏
        panel.clear_result_timestamp()
        assert panel._header_bar.isHidden()


class TestChartViewerPanel:
    """ChartViewerPanel 测试"""
    
    def test_init(self, app):
        """测试初始化"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        
        assert panel is not None
        assert panel.chart_viewer is not None
    
    def test_clear(self, app):
        """测试清空"""
        from presentation.panels.simulation.simulation_tab import ChartViewerPanel
        
        panel = ChartViewerPanel()
        panel.clear()
        
        # 清空后应该没有图表
        assert panel.chart_viewer.get_current_chart_path() is None


class TestSimulationTab:
    """SimulationTab 测试"""
    
    def test_init(self, app, mock_service_locator):
        """测试初始化"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        assert tab is not None
        assert tab._metrics_summary_panel is not None
        assert tab._chart_viewer_panel is not None
        assert tab._status_indicator is not None
    
    def test_set_project_root(self, app, mock_service_locator):
        """测试设置项目根目录"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        tab.set_project_root("/test/project")
        
        assert tab._project_root == "/test/project"
    
    def test_update_metrics(self, app, mock_service_locator):
        """测试更新指标"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        tab = SimulationTab()
        
        metrics = [
            DisplayMetric(
                name="gain",
                display_name="增益",
                value="20.5 dB",
                unit="dB",
                target="≥ 20 dB",
                is_met=True,
                trend="up",
                category="gain",
            ),
            DisplayMetric(
                name="bandwidth",
                display_name="带宽",
                value="10 MHz",
                unit="MHz",
                target="≥ 5 MHz",
                is_met=True,
                trend="stable",
                category="bandwidth",
            ),
        ]
        
        tab.update_metrics(metrics)
        
        assert tab._metrics_summary_panel.metrics_panel.card_count == 2
    
    def test_clear(self, app, mock_service_locator):
        """测试清空"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        tab = SimulationTab()
        
        metrics = [
            DisplayMetric(
                name="gain",
                display_name="增益",
                value="20.5 dB",
                unit="dB",
                target="≥ 20 dB",
                is_met=True,
                trend="up",
                category="gain",
            ),
        ]
        
        tab.update_metrics(metrics)
        tab.clear()
        
        assert tab._metrics_summary_panel.metrics_panel.card_count == 0
    
    def test_retranslate_ui(self, app, mock_service_locator):
        """测试国际化"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        # 应该不抛出异常
        tab.retranslate_ui()
    
    def test_history_requested_signal(self, app, mock_service_locator):
        """测试历史请求信号"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        signal_received = []
        tab.history_requested.connect(lambda: signal_received.append(True))
        
        # 模拟点击历史按钮
        tab._metrics_summary_panel._history_btn.click()
        
        assert len(signal_received) == 1
    
    def test_empty_state_visibility(self, app, mock_service_locator):
        """测试空状态显示"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        # 初始应该显示空状态
        # splitter 应该被隐藏，empty_widget 应该未被隐藏
        assert tab._splitter.isHidden()
        assert not tab._empty_widget.isHidden()
    
    def test_hide_empty_state_on_metrics(self, app, mock_service_locator):
        """测试有指标时隐藏空状态"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        tab = SimulationTab()
        
        metrics = [
            DisplayMetric(
                name="gain",
                display_name="增益",
                value="20.5 dB",
                unit="dB",
                target="≥ 20 dB",
                is_met=True,
                trend="up",
                category="gain",
            ),
        ]
        
        tab.update_metrics(metrics)
        
        # 应该隐藏空状态（检查 isHidden 而非 isVisible）
        assert tab._empty_widget.isHidden()
        assert not tab._splitter.isHidden()


class TestSimulationTabEvents:
    """SimulationTab 事件处理测试"""
    
    def test_on_workflow_locked(self, app, mock_service_locator):
        """测试工作流锁定事件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        tab._on_workflow_locked({})
        
        assert tab._is_workflow_running
        # 检查状态指示器未被隐藏（而非 isVisible）
        assert not tab._status_indicator.isHidden()
    
    def test_on_workflow_unlocked(self, app, mock_service_locator):
        """测试工作流解锁事件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        tab._on_workflow_locked({})
        tab._on_workflow_unlocked({})
        
        assert not tab._is_workflow_running
        assert not tab._status_indicator.isVisible()
    
    def test_on_awaiting_confirmation(self, app, mock_service_locator):
        """测试等待确认事件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        tab._on_awaiting_confirmation({})
        
        # 检查状态指示器未被隐藏
        assert not tab._status_indicator.isHidden()
    
    def test_on_user_confirmed(self, app, mock_service_locator):
        """测试用户确认事件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        tab = SimulationTab()
        
        tab._on_awaiting_confirmation({})
        tab._on_user_confirmed({})
        
        assert not tab._status_indicator.isVisible()
    
    def test_on_project_closed(self, app, mock_service_locator):
        """测试项目关闭事件"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        tab = SimulationTab()
        tab._project_root = "/test/project"
        
        metrics = [
            DisplayMetric(
                name="gain",
                display_name="增益",
                value="20.5 dB",
                unit="dB",
                target="≥ 20 dB",
                is_met=True,
                trend="up",
                category="gain",
            ),
        ]
        tab.update_metrics(metrics)
        
        tab._on_project_closed({"path": "/test/project"})
        
        assert tab._project_root is None
        # 检查空状态组件未被隐藏
        assert not tab._empty_widget.isHidden()

    def test_file_created_event_does_not_reload_same_result_path_twice(self, app, mock_service_locator):
        """测试文件监控不会重复加载刚刚通过完成事件加载过的结果"""
        from presentation.panels.simulation.simulation_tab import SimulationTab

        tab = SimulationTab()
        tab._project_root = "/test/project"

        load_result_obj = MagicMock()
        load_result_obj.success = True
        load_result_obj.data = MagicMock()

        with patch("domain.services.simulation_service.SimulationService.load_sim_result", return_value=load_result_obj):
            with patch.object(tab, "load_result") as mock_load_result:
                tab._on_simulation_complete({
                    "data": {
                        "result_path": ".circuit_ai/sim_results/result.json",
                        "success": True,
                    }
                })

                assert mock_load_result.call_count == 1

                tab._on_sim_result_file_created({
                    "data": {
                        "file_path": ".circuit_ai/sim_results/result.json",
                        "project_root": "/test/project",
                    }
                })

                assert mock_load_result.call_count == 1

    def test_displayed_signals_change_updates_raw_data_filter(self, app, mock_service_locator, mock_simulation_result):
        """测试波形显示信号变化直接驱动原始数据刷新"""
        from presentation.panels.simulation.simulation_tab import SimulationTab

        tab = SimulationTab()
        tab.load_result(mock_simulation_result)

        with patch.object(tab._chart_viewer_panel.raw_data_table, "load_data") as mock_load_data:
            tab._on_displayed_signals_changed(["V(out)"])
            mock_load_data.assert_called_once_with(mock_simulation_result, ["V(out)"])

        with patch.object(tab._chart_viewer_panel.raw_data_table, "load_data") as mock_load_data:
            tab._on_displayed_signals_changed([])
            mock_load_data.assert_called_once_with(mock_simulation_result, None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
