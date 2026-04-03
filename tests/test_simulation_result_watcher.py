# Test SimulationResultWatcher
"""
SimulationResultWatcher 单元测试

测试内容：
- 项目打开事件的数据解包
- 项目关闭事件停止监控
"""

from unittest.mock import MagicMock

from domain.simulation.service.simulation_result_watcher import SimulationResultWatcher


class TestSimulationResultWatcher:
    """SimulationResultWatcher 测试"""

    def test_on_project_opened_unwraps_event_bus_data(self):
        """测试项目打开事件正确解包 EventBus 包装层"""
        watcher = SimulationResultWatcher()
        watcher.start = MagicMock(return_value=True)

        watcher._on_project_opened({"data": {"path": "/test/project"}})

        watcher.start.assert_called_once_with("/test/project")

    def test_on_project_opened_ignores_missing_path(self):
        """测试项目打开事件缺少路径时不启动监控"""
        watcher = SimulationResultWatcher()
        watcher.start = MagicMock(return_value=True)

        watcher._on_project_opened({"data": {}})

        watcher.start.assert_not_called()

    def test_on_project_closed_stops_watcher(self):
        """测试项目关闭事件停止监控"""
        watcher = SimulationResultWatcher()
        watcher.stop = MagicMock()

        watcher._on_project_closed({"data": {"path": "/test/project"}})

        watcher.stop.assert_called_once()
