# Test SessionManager integration with SimulationResultWatcher
"""
测试 SessionManager 与 SimulationResultWatcher 的集成

验证：
1. SessionManager 初始化时会调用 SimulationResultWatcher.initialize()
2. SessionManager.dispose() 会调用 SimulationResultWatcher.dispose()
3. 监控器能正确响应项目生命周期事件
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtWidgets import QMainWindow


@pytest.fixture
def mock_main_window():
    """创建模拟主窗口"""
    return Mock(spec=QMainWindow)


@pytest.fixture
def mock_panels():
    """创建模拟面板字典"""
    return {}


class TestSessionManagerWatcherIntegration:
    """测试 SessionManager 与 SimulationResultWatcher 的集成"""
    
    def test_session_manager_initializes_watcher(
        self, mock_main_window, mock_panels
    ):
        """测试 SessionManager 初始化时会调用监控器的 initialize()"""
        mock_watcher = Mock()
        mock_watcher.initialize = Mock()
        
        with patch(
            'domain.simulation.service.simulation_result_watcher.simulation_result_watcher',
            mock_watcher
        ):
            from presentation.session_manager import SessionManager
            
            # 创建 SessionManager
            session_manager = SessionManager(mock_main_window, mock_panels)
            
            # 验证监控器的 initialize() 被调用
            mock_watcher.initialize.assert_called_once()
    
    def test_session_manager_disposes_watcher(
        self, mock_main_window, mock_panels
    ):
        """测试 SessionManager.dispose() 会调用监控器的 dispose()"""
        mock_watcher = Mock()
        mock_watcher.initialize = Mock()
        mock_watcher.dispose = Mock()
        
        with patch(
            'domain.simulation.service.simulation_result_watcher.simulation_result_watcher',
            mock_watcher
        ):
            from presentation.session_manager import SessionManager
            
            # 创建 SessionManager
            session_manager = SessionManager(mock_main_window, mock_panels)
            
            # 调用 dispose
            session_manager.dispose()
            
            # 验证监控器的 dispose() 被调用
            mock_watcher.dispose.assert_called_once()
    
    def test_watcher_initialization_error_handling(
        self, mock_main_window, mock_panels
    ):
        """测试监控器初始化失败时的错误处理"""
        mock_watcher = Mock()
        mock_watcher.initialize = Mock(side_effect=Exception("Init failed"))
        
        with patch(
            'domain.simulation.service.simulation_result_watcher.simulation_result_watcher',
            mock_watcher
        ):
            from presentation.session_manager import SessionManager
            
            # 创建 SessionManager 不应该抛出异常
            session_manager = SessionManager(mock_main_window, mock_panels)
            
            # 验证监控器的 initialize() 被调用（即使失败）
            mock_watcher.initialize.assert_called_once()
    
    def test_watcher_dispose_error_handling(
        self, mock_main_window, mock_panels
    ):
        """测试监控器释放失败时的错误处理"""
        mock_watcher = Mock()
        mock_watcher.initialize = Mock()
        mock_watcher.dispose = Mock(side_effect=Exception("Dispose failed"))
        
        with patch(
            'domain.simulation.service.simulation_result_watcher.simulation_result_watcher',
            mock_watcher
        ):
            from presentation.session_manager import SessionManager
            
            # 创建 SessionManager
            session_manager = SessionManager(mock_main_window, mock_panels)
            
            # 调用 dispose 不应该抛出异常
            session_manager.dispose()
            
            # 验证监控器的 dispose() 被调用（即使失败）
            mock_watcher.dispose.assert_called_once()


class TestWatcherLifecycle:
    """测试监控器生命周期管理"""
    
    def test_watcher_has_initialize_method(self):
        """测试监控器有 initialize 方法"""
        from domain.simulation.service.simulation_result_watcher import (
            simulation_result_watcher
        )
        
        assert hasattr(simulation_result_watcher, 'initialize')
        assert callable(simulation_result_watcher.initialize)
    
    def test_watcher_has_dispose_method(self):
        """测试监控器有 dispose 方法"""
        from domain.simulation.service.simulation_result_watcher import (
            simulation_result_watcher
        )
        
        assert hasattr(simulation_result_watcher, 'dispose')
        assert callable(simulation_result_watcher.dispose)
    
    def test_watcher_has_start_method(self):
        """测试监控器有 start 方法"""
        from domain.simulation.service.simulation_result_watcher import (
            simulation_result_watcher
        )
        
        assert hasattr(simulation_result_watcher, 'start')
        assert callable(simulation_result_watcher.start)
    
    def test_watcher_has_stop_method(self):
        """测试监控器有 stop 方法"""
        from domain.simulation.service.simulation_result_watcher import (
            simulation_result_watcher
        )
        
        assert hasattr(simulation_result_watcher, 'stop')
        assert callable(simulation_result_watcher.stop)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

