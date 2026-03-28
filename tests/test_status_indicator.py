# test_status_indicator.py
"""
StatusIndicator 状态指示器组件测试

测试内容：
- 组件初始化
- 等待确认状态显示
- 运行中状态显示
- 状态隐藏
- 国际化支持
"""

import pytest
from unittest.mock import MagicMock, patch


class TestStatusIndicator:
    """StatusIndicator 测试类"""
    
    @pytest.fixture
    def status_indicator(self, qtbot):
        """创建 StatusIndicator 实例"""
        from presentation.panels.simulation.simulation_tab import StatusIndicator
        indicator = StatusIndicator()
        qtbot.addWidget(indicator)
        return indicator
    
    def test_init_hidden(self, status_indicator):
        """测试初始化时默认隐藏"""
        assert not status_indicator.isVisible()
    
    def test_show_awaiting_confirmation(self, status_indicator):
        """测试显示等待确认状态"""
        status_indicator.show_awaiting_confirmation()
        
        assert status_indicator.isVisible()
        assert status_indicator._icon_label.text() == "⏸"
        assert "迭代完成" in status_indicator._text_label.text() or "awaiting" in status_indicator._text_label.text().lower()
        assert not status_indicator._progress_bar.isVisible()
    
    def test_show_running_default_message(self, status_indicator):
        """测试显示运行中状态（默认消息）"""
        status_indicator.show_running()
        
        assert status_indicator.isVisible()
        assert status_indicator._icon_label.text() == "⏳"
        assert "优化进行中" in status_indicator._text_label.text() or "running" in status_indicator._text_label.text().lower()
        assert status_indicator._progress_bar.isVisible()
    
    def test_show_running_custom_message(self, status_indicator):
        """测试显示运行中状态（自定义消息）"""
        custom_message = "正在执行仿真..."
        status_indicator.show_running(custom_message)
        
        assert status_indicator.isVisible()
        assert status_indicator._text_label.text() == custom_message
        assert status_indicator._progress_bar.isVisible()
    
    def test_hide_status(self, status_indicator):
        """测试隐藏状态"""
        # 先显示
        status_indicator.show_running()
        assert status_indicator.isVisible()
        
        # 再隐藏
        status_indicator.hide_status()
        assert not status_indicator.isVisible()
    
    def test_state_transitions(self, status_indicator):
        """测试状态转换"""
        # 初始隐藏
        assert not status_indicator.isVisible()
        
        # 显示等待确认
        status_indicator.show_awaiting_confirmation()
        assert status_indicator.isVisible()
        assert status_indicator._icon_label.text() == "⏸"
        
        # 切换到运行中
        status_indicator.show_running()
        assert status_indicator.isVisible()
        assert status_indicator._icon_label.text() == "⏳"
        
        # 隐藏
        status_indicator.hide_status()
        assert not status_indicator.isVisible()
        
        # 再次显示等待确认
        status_indicator.show_awaiting_confirmation()
        assert status_indicator.isVisible()
    
    def test_fixed_height(self, status_indicator):
        """测试固定高度"""
        from presentation.panels.simulation.simulation_tab import STATUS_BAR_HEIGHT
        assert status_indicator.height() == STATUS_BAR_HEIGHT
    
    def test_object_name(self, status_indicator):
        """测试对象名称"""
        assert status_indicator.objectName() == "statusIndicator"
    
    def test_retranslate_ui(self, status_indicator):
        """测试国际化方法存在"""
        assert hasattr(status_indicator, 'retranslate_ui')
        # 调用不应抛出异常
        status_indicator.retranslate_ui()
    
    def test_progress_bar_indeterminate(self, status_indicator):
        """测试进度条为不确定模式"""
        status_indicator.show_running()
        
        # 不确定模式：minimum == maximum == 0
        assert status_indicator._progress_bar.minimum() == 0
        assert status_indicator._progress_bar.maximum() == 0


class TestStatusIndicatorIntegration:
    """StatusIndicator 集成测试"""
    
    @pytest.fixture
    def simulation_tab(self, qtbot):
        """创建 SimulationTab 实例"""
        from presentation.panels.simulation.simulation_tab import SimulationTab
        tab = SimulationTab()
        qtbot.addWidget(tab)
        return tab
    
    def test_status_indicator_in_simulation_tab(self, simulation_tab):
        """测试 StatusIndicator 在 SimulationTab 中的集成"""
        assert hasattr(simulation_tab, '_status_indicator')
        assert simulation_tab._status_indicator is not None
    
    def test_awaiting_confirmation_event(self, simulation_tab):
        """测试等待确认事件处理"""
        # 直接调用事件处理方法
        simulation_tab._on_awaiting_confirmation({})
        
        # 使用 isHidden() 检查，因为 isVisible() 对未显示的窗口返回 False
        assert not simulation_tab._status_indicator.isHidden()
    
    def test_user_confirmed_event(self, simulation_tab):
        """测试用户确认事件处理"""
        # 先显示
        simulation_tab._status_indicator.show_awaiting_confirmation()
        assert not simulation_tab._status_indicator.isHidden()
        
        # 处理确认事件
        simulation_tab._on_user_confirmed({})
        
        assert simulation_tab._status_indicator.isHidden()
    
    def test_workflow_locked_event(self, simulation_tab):
        """测试工作流锁定事件处理"""
        simulation_tab._on_workflow_locked({})
        
        assert not simulation_tab._status_indicator.isHidden()
        assert simulation_tab._is_workflow_running
    
    def test_workflow_unlocked_event(self, simulation_tab):
        """测试工作流解锁事件处理"""
        # 先锁定
        simulation_tab._on_workflow_locked({})
        assert not simulation_tab._status_indicator.isHidden()
        
        # 解锁
        simulation_tab._on_workflow_unlocked({})
        
        assert simulation_tab._status_indicator.isHidden()
        assert not simulation_tab._is_workflow_running
    
    def test_clear_hides_status(self, simulation_tab):
        """测试清空时隐藏状态指示器"""
        # 先显示
        simulation_tab._status_indicator.show_running()
        assert not simulation_tab._status_indicator.isHidden()
        
        # 清空
        simulation_tab.clear()
        
        assert simulation_tab._status_indicator.isHidden()


class TestStatusIndicatorExport:
    """StatusIndicator 导出测试"""
    
    def test_import_from_simulation_tab(self):
        """测试从 simulation_tab 模块导入"""
        from presentation.panels.simulation.simulation_tab import StatusIndicator
        assert StatusIndicator is not None
    
    def test_import_from_package(self):
        """测试从包导入"""
        from presentation.panels.simulation import StatusIndicator
        assert StatusIndicator is not None
    
    def test_in_all_list(self):
        """测试在 __all__ 列表中"""
        from presentation.panels.simulation import simulation_tab
        assert "StatusIndicator" in simulation_tab.__all__
