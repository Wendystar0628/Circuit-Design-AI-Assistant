# Test Main Window Integration - Phase 4 Task 6.8
"""
测试主窗口集成功能

测试内容：
- 下栏面板集成到主窗口
- 仿真设置菜单项
- 仿真工具栏按钮
"""

import pytest
from unittest.mock import MagicMock, patch
import json
from pathlib import Path


class TestActionHandlersSimulationSettings:
    """测试动作处理器中的仿真设置回调"""
    
    def test_simulation_settings_callback_exists(self):
        """测试仿真设置回调存在"""
        from presentation.action_handlers import ActionHandlers
        
        mock_window = MagicMock()
        panels = {}
        
        handlers = ActionHandlers(mock_window, panels)
        callbacks = handlers.get_callbacks()
        
        assert "on_simulation_settings" in callbacks
        assert callable(callbacks["on_simulation_settings"])
    
    def test_all_simulation_callbacks_exist(self):
        """测试所有仿真相关回调存在"""
        from presentation.action_handlers import ActionHandlers
        
        mock_window = MagicMock()
        panels = {}
        
        handlers = ActionHandlers(mock_window, panels)
        callbacks = handlers.get_callbacks()
        
        # 验证所有仿真相关回调
        assert "on_run_auto_simulation" in callbacks
        assert "on_run_select_simulation" in callbacks
        assert "on_stop_simulation" in callbacks
        assert "on_simulation_settings" in callbacks


class TestI18nSimulationSettings:
    """测试仿真设置国际化文本"""
    
    def test_english_texts_exist(self):
        """测试英文文本存在"""
        i18n_path = Path(__file__).parent.parent / "resources" / "i18n" / "en_US.json"
        with open(i18n_path, "r", encoding="utf-8") as f:
            texts = json.load(f)
        
        # 验证仿真设置相关文本
        assert "menu.settings.simulation" in texts
        assert texts["menu.settings.simulation"] == "Simulation Settings..."
        assert "sim_settings_title" in texts
        assert "sim_settings_analysis_tab" in texts
        assert "sim_settings_chart_tab" in texts
        assert "sim_settings_basic_group" in texts
        assert "sim_settings_advanced_group" in texts
    
    def test_chinese_texts_exist(self):
        """测试中文文本存在"""
        i18n_path = Path(__file__).parent.parent / "resources" / "i18n" / "zh_CN.json"
        with open(i18n_path, "r", encoding="utf-8") as f:
            texts = json.load(f)
        
        # 验证仿真设置相关文本
        assert "menu.settings.simulation" in texts
        assert texts["menu.settings.simulation"] == "仿真设置..."
        assert "sim_settings_title" in texts
        assert texts["sim_settings_title"] == "仿真设置"
        assert "sim_settings_analysis_tab" in texts
        assert "sim_settings_chart_tab" in texts


class TestMenuManagerStructure:
    """测试菜单管理器结构"""
    
    def test_settings_menu_has_simulation_action(self):
        """测试设置菜单包含仿真设置动作"""
        # 读取 menu_manager.py 源码验证结构
        menu_manager_path = Path(__file__).parent.parent / "presentation" / "menu_manager.py"
        with open(menu_manager_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 验证仿真设置动作定义
        assert 'self._actions["settings_simulation"]' in content
        assert '"on_simulation_settings"' in content
        assert 'Ctrl+Shift+,' in content  # 快捷键


class TestToolbarManagerStructure:
    """测试工具栏管理器结构"""
    
    def test_toolbar_has_simulation_buttons(self):
        """测试工具栏包含仿真按钮"""
        toolbar_manager_path = Path(__file__).parent.parent / "presentation" / "toolbar_manager.py"
        with open(toolbar_manager_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 验证仿真按钮定义
        assert 'self._actions["toolbar_run_auto"]' in content
        assert 'self._actions["toolbar_run_select"]' in content
        assert 'self._actions["toolbar_stop"]' in content


class TestBottomPanelStructure:
    """测试下栏面板结构"""
    
    def test_bottom_panel_has_simulation_tab(self):
        """测试下栏面板包含仿真标签页"""
        bottom_panel_path = Path(__file__).parent.parent / "presentation" / "panels" / "bottom_panel.py"
        with open(bottom_panel_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 验证仿真标签页
        assert "SimulationTab" in content
        assert "get_simulation_tab" in content
        assert "TAB_SIMULATION" in content


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TestActionHandlersSimulationSettings",
    "TestI18nSimulationSettings",
    "TestMenuManagerStructure",
    "TestToolbarManagerStructure",
    "TestBottomPanelStructure",
]
