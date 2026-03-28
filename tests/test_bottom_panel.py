# test_bottom_panel.py
"""
BottomPanel 单元测试

测试下栏面板容器的核心功能：
- 标签页管理
- 事件响应
- 国际化支持
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication

# 确保 Qt 应用程序存在
@pytest.fixture(scope="session")
def qapp():
    """创建 Qt 应用程序"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestBottomPanel:
    """BottomPanel 测试类"""
    
    @pytest.fixture
    def mock_event_bus(self):
        """模拟 EventBus"""
        event_bus = MagicMock()
        event_bus.subscribe = MagicMock()
        event_bus.unsubscribe = MagicMock()
        return event_bus
    
    @pytest.fixture
    def mock_service_locator(self, mock_event_bus):
        """模拟 ServiceLocator"""
        with patch("shared.service_locator.ServiceLocator") as mock_sl:
            mock_sl.get_optional = MagicMock(return_value=mock_event_bus)
            yield mock_sl
    
    @pytest.fixture
    def bottom_panel(self, qapp, mock_service_locator):
        """创建 BottomPanel 实例"""
        # 延迟导入以确保 mock 生效
        from presentation.panels.bottom_panel import BottomPanel
        panel = BottomPanel()
        yield panel
        panel.close()
    
    def test_init(self, bottom_panel):
        """测试初始化"""
        assert bottom_panel is not None
        assert bottom_panel._tab_widget is not None
        assert bottom_panel._simulation_tab is not None
        assert bottom_panel._report_tab is None
    
    def test_tab_count(self, bottom_panel):
        """测试标签页数量"""
        # 初始只有仿真标签页
        assert bottom_panel._tab_widget.count() == 1
    
    def test_switch_to_simulation(self, bottom_panel):
        """测试切换到仿真标签页"""
        bottom_panel.switch_to_simulation()
        assert bottom_panel.get_current_tab() == 0
    
    def test_switch_to_report_without_tab(self, bottom_panel):
        """测试在没有报告标签页时切换"""
        # 不应该抛出异常
        bottom_panel.switch_to_report()
        # 应该保持在仿真标签页
        assert bottom_panel.get_current_tab() == 0
    
    def test_add_report_tab(self, bottom_panel):
        """测试添加报告标签页"""
        from PyQt6.QtWidgets import QWidget
        
        report_tab = QWidget()
        bottom_panel.add_report_tab(report_tab)
        
        assert bottom_panel._report_tab is not None
        assert bottom_panel._tab_widget.count() == 2
    
    def test_add_report_tab_twice(self, bottom_panel):
        """测试重复添加报告标签页"""
        from PyQt6.QtWidgets import QWidget
        
        report_tab1 = QWidget()
        report_tab2 = QWidget()
        
        bottom_panel.add_report_tab(report_tab1)
        bottom_panel.add_report_tab(report_tab2)
        
        # 应该只有一个报告标签页
        assert bottom_panel._tab_widget.count() == 2
    
    def test_switch_to_report_with_tab(self, bottom_panel):
        """测试有报告标签页时切换"""
        from PyQt6.QtWidgets import QWidget
        
        report_tab = QWidget()
        bottom_panel.add_report_tab(report_tab)
        
        bottom_panel.switch_to_report()
        assert bottom_panel.get_current_tab() == 1
    
    def test_get_simulation_tab(self, bottom_panel):
        """测试获取仿真标签页"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        
        sim_tab = bottom_panel.get_simulation_tab()
        assert isinstance(sim_tab, SimulationTab)
    
    def test_tab_changed_signal(self, bottom_panel):
        """测试标签页切换信号"""
        from PyQt6.QtWidgets import QWidget
        
        # 添加报告标签页
        report_tab = QWidget()
        bottom_panel.add_report_tab(report_tab)
        
        # 连接信号
        signal_received = []
        bottom_panel.tab_changed.connect(lambda idx: signal_received.append(idx))
        
        # 切换标签页
        bottom_panel.switch_to_report()
        
        assert len(signal_received) == 1
        assert signal_received[0] == 1
    
    def test_history_requested_signal(self, bottom_panel):
        """测试历史请求信号传递"""
        signal_received = []
        bottom_panel.history_requested.connect(lambda: signal_received.append(True))
        
        # 触发仿真标签页的历史请求
        bottom_panel._simulation_tab.history_requested.emit()
        
        assert len(signal_received) == 1
    
    def test_settings_requested_signal(self, bottom_panel):
        """测试设置请求信号传递"""
        signal_received = []
        bottom_panel.settings_requested.connect(lambda: signal_received.append(True))
        
        # 触发仿真标签页的设置请求
        bottom_panel._simulation_tab.settings_requested.emit()
        
        assert len(signal_received) == 1
    
    def test_retranslate_ui(self, bottom_panel):
        """测试国际化"""
        # 不应该抛出异常
        bottom_panel.retranslate_ui()
        
        # 检查标签页标题已设置
        tab_text = bottom_panel._tab_widget.tabText(0)
        assert tab_text != ""
    
    def test_project_opened_event(self, bottom_panel):
        """测试项目打开事件处理"""
        event_data = {"data": {"path": "/test/project"}}
        bottom_panel._on_project_opened(event_data)
        
        assert bottom_panel._project_root == "/test/project"
    
    def test_project_closed_event(self, bottom_panel):
        """测试项目关闭事件处理"""
        # 先设置项目
        bottom_panel._project_root = "/test/project"
        
        # 触发关闭事件
        bottom_panel._on_project_closed({})
        
        assert bottom_panel._project_root is None
    
    def test_simulation_complete_event(self, bottom_panel):
        """测试仿真完成事件处理"""
        from PyQt6.QtWidgets import QWidget
        
        # 添加报告标签页并切换到它
        report_tab = QWidget()
        bottom_panel.add_report_tab(report_tab)
        bottom_panel.switch_to_report()
        
        assert bottom_panel.get_current_tab() == 1
        
        # 触发仿真完成事件
        bottom_panel._on_simulation_complete({})
        
        # 应该自动切换到仿真标签页
        assert bottom_panel.get_current_tab() == 0


class TestBottomPanelConstants:
    """测试常量定义"""
    
    def test_tab_constants(self):
        """测试标签页索引常量"""
        from presentation.panels.bottom_panel import TAB_SIMULATION, TAB_REPORT
        
        assert TAB_SIMULATION == 0
        assert TAB_REPORT == 1


class TestBottomPanelExports:
    """测试模块导出"""
    
    def test_module_exports(self):
        """测试模块导出"""
        from presentation.panels.bottom_panel import (
            BottomPanel,
            TAB_SIMULATION,
            TAB_REPORT,
        )
        
        assert BottomPanel is not None
        assert TAB_SIMULATION is not None
        assert TAB_REPORT is not None
    
    def test_panels_package_exports(self):
        """测试 panels 包导出"""
        from presentation.panels import (
            BottomPanel,
            TAB_SIMULATION,
            TAB_REPORT,
        )
        
        assert BottomPanel is not None
        assert TAB_SIMULATION is not None
        assert TAB_REPORT is not None
