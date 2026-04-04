# test_bottom_panel.py
"""
仿真结果面板测试

测试当前主界面直接使用 SimulationTab 的结构。
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """创建 Qt 应用程序"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_event_bus():
    """模拟 EventBus"""
    event_bus = MagicMock()
    event_bus.subscribe = MagicMock()
    event_bus.unsubscribe = MagicMock()
    return event_bus


@pytest.fixture
def mock_service_locator(mock_event_bus):
    """模拟 ServiceLocator"""
    with patch("shared.service_locator.ServiceLocator") as mock_sl:
        mock_sl.get_optional = MagicMock(return_value=mock_event_bus)
        yield mock_sl


@pytest.fixture
def simulation_tab(qapp, mock_service_locator):
    """创建仿真结果面板实例"""
    from presentation.panels.simulation.simulation_tab import SimulationTab

    tab = SimulationTab()
    yield tab
    tab.close()


class TestSimulationPanelRegion:
    """仿真结果面板测试类"""

    def test_init(self, simulation_tab):
        """测试初始化"""
        assert simulation_tab is not None
        assert simulation_tab._chart_viewer_panel is not None
        assert simulation_tab._chart_viewer_panel.metrics_summary_panel is not None
        assert simulation_tab._chart_viewer_panel._tab_widget.count() == 6

    def test_history_requested_signal(self, simulation_tab):
        """测试历史请求信号"""
        signal_received = []
        simulation_tab.history_requested.connect(lambda: signal_received.append(True))

        simulation_tab._chart_viewer_panel.metrics_summary_panel._history_btn.click()

        assert len(signal_received) == 1

    def test_project_opened_event(self, simulation_tab):
        """测试项目打开事件处理"""
        simulation_tab._on_project_opened({"data": {"path": "/test/project"}})

        assert simulation_tab._project_root == "/test/project"
        assert not simulation_tab._empty_widget.isHidden()

    def test_project_closed_event(self, simulation_tab):
        """测试项目关闭事件处理"""
        simulation_tab._project_root = "/test/project"
        simulation_tab._on_project_closed({})

        assert simulation_tab._project_root is None
        assert not simulation_tab._empty_widget.isHidden()


__all__ = ["TestSimulationPanelRegion"]
