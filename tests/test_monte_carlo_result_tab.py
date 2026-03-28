# Test Monte Carlo Result Tab
"""
蒙特卡洛结果标签页测试

测试内容：
- 组件初始化
- 数据更新
- 指标切换
- 统计数据显示
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Dict, List, Any


# Mock MonteCarloStatistics
@dataclass
class MockMonteCarloStatistics:
    """模拟统计数据"""
    metric_name: str
    mean: float = 0.0
    std: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0
    median: float = 0.0
    percentile_3sigma_low: float = 0.0
    percentile_3sigma_high: float = 0.0
    values: List[float] = field(default_factory=list)


# Mock MonteCarloAnalysisResult
@dataclass
class MockMonteCarloResult:
    """模拟蒙特卡洛分析结果"""
    circuit_file: str = "test.cir"
    analysis_type: str = "ac"
    num_runs: int = 100
    successful_runs: int = 95
    failed_runs: int = 5
    statistics: Dict[str, MockMonteCarloStatistics] = field(default_factory=dict)
    yield_percent: float = 92.5
    sensitive_params: List[str] = field(default_factory=list)
    timestamp: str = "2026-01-07T10:00:00"
    duration_seconds: float = 10.5


def create_mock_result() -> MockMonteCarloResult:
    """创建模拟结果"""
    gain_stats = MockMonteCarloStatistics(
        metric_name="gain",
        mean=40.5,
        std=2.3,
        min_value=35.2,
        max_value=46.8,
        median=40.3,
        percentile_3sigma_low=33.6,
        percentile_3sigma_high=47.4,
        values=[38.0 + i * 0.1 for i in range(100)]
    )
    
    bandwidth_stats = MockMonteCarloStatistics(
        metric_name="bandwidth",
        mean=1.2e6,
        std=0.15e6,
        min_value=0.8e6,
        max_value=1.6e6,
        median=1.18e6,
        percentile_3sigma_low=0.75e6,
        percentile_3sigma_high=1.65e6,
        values=[1.0e6 + i * 0.01e6 for i in range(100)]
    )
    
    return MockMonteCarloResult(
        statistics={
            "gain": gain_stats,
            "bandwidth": bandwidth_stats
        },
        sensitive_params=["R1.resistance", "C1.capacitance", "M1.vth0"]
    )


class TestMonteCarloResultTabUnit:
    """单元测试（不需要 Qt）"""
    
    def test_mock_result_creation(self):
        """测试模拟结果创建"""
        result = create_mock_result()
        
        assert result.num_runs == 100
        assert result.successful_runs == 95
        assert result.failed_runs == 5
        assert result.yield_percent == 92.5
        assert len(result.statistics) == 2
        assert "gain" in result.statistics
        assert "bandwidth" in result.statistics
        assert len(result.sensitive_params) == 3
    
    def test_statistics_values(self):
        """测试统计数据值"""
        result = create_mock_result()
        gain_stats = result.statistics["gain"]
        
        assert gain_stats.mean == 40.5
        assert gain_stats.std == 2.3
        assert gain_stats.min_value == 35.2
        assert gain_stats.max_value == 46.8
        assert len(gain_stats.values) == 100


@pytest.fixture
def qt_app():
    """创建 Qt 应用（如果可用）"""
    try:
        from PyQt6.QtWidgets import QApplication
        import sys
        
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app
    except ImportError:
        pytest.skip("PyQt6 not available")


class TestMonteCarloResultTabQt:
    """Qt 组件测试"""
    
    def test_tab_creation(self, qt_app):
        """测试标签页创建"""
        from presentation.panels.simulation.monte_carlo_result_tab import MonteCarloResultTab
        
        tab = MonteCarloResultTab()
        assert tab is not None
        assert tab._mc_result is None
        assert tab._current_metric == ""
    
    def test_update_results(self, qt_app):
        """测试更新结果"""
        from presentation.panels.simulation.monte_carlo_result_tab import MonteCarloResultTab
        
        tab = MonteCarloResultTab()
        result = create_mock_result()
        
        tab.update_results(result)
        
        assert tab._mc_result is not None
        assert tab._current_metric == "gain"  # 第一个指标
    
    def test_switch_metric(self, qt_app):
        """测试切换指标"""
        from presentation.panels.simulation.monte_carlo_result_tab import MonteCarloResultTab
        
        tab = MonteCarloResultTab()
        result = create_mock_result()
        
        tab.update_results(result)
        tab.switch_metric("bandwidth")
        
        assert tab._current_metric == "bandwidth"
    
    def test_clear(self, qt_app):
        """测试清空"""
        from presentation.panels.simulation.monte_carlo_result_tab import MonteCarloResultTab
        
        tab = MonteCarloResultTab()
        result = create_mock_result()
        
        tab.update_results(result)
        tab.clear()
        
        assert tab._mc_result is None
        assert tab._current_metric == ""
    
    def test_statistics_card(self, qt_app):
        """测试统计摘要卡片"""
        from presentation.panels.simulation.monte_carlo_result_tab import StatisticsSummaryCard
        
        card = StatisticsSummaryCard()
        card.update_statistics(
            mean=40.5,
            std=2.3,
            min_val=35.2,
            max_val=46.8,
            median=40.3,
            sigma_low=33.6,
            sigma_high=47.4
        )
        
        assert card._mean_row.value_widget.text() == "40.5"
        assert card._std_row.value_widget.text() == "2.3"
    
    def test_yield_display(self, qt_app):
        """测试良率显示"""
        from presentation.panels.simulation.monte_carlo_result_tab import YieldDisplay
        
        display = YieldDisplay()
        
        # 测试高良率
        display.set_yield(98.5)
        assert display._yield_percent == 98.5
        assert "98.5%" in display._value_label.text()
        
        # 测试低良率
        display.set_yield(75.0)
        assert display._yield_percent == 75.0
    
    def test_sensitive_params_panel(self, qt_app):
        """测试敏感参数面板"""
        from presentation.panels.simulation.monte_carlo_result_tab import SensitiveParamsPanel
        
        panel = SensitiveParamsPanel()
        params = ["R1.resistance", "C1.capacitance", "M1.vth0"]
        
        panel.set_params(params)
        
        assert panel._table.rowCount() == 3
        assert panel._table.item(0, 1).text() == "R1.resistance"
    
    def test_metric_selector(self, qt_app):
        """测试指标选择器"""
        from presentation.panels.simulation.monte_carlo_result_tab import MetricSelector
        
        selector = MetricSelector()
        metrics = ["gain", "bandwidth", "phase_margin"]
        
        selector.set_metrics(metrics)
        
        assert selector._combo.count() == 3
        assert selector.current_metric() == "gain"


class TestHistogramChart:
    """直方图组件测试"""
    
    def test_histogram_creation(self, qt_app):
        """测试直方图创建"""
        from presentation.panels.simulation.monte_carlo_result_tab import HistogramChart
        
        chart = HistogramChart()
        assert chart is not None
    
    def test_histogram_update(self, qt_app):
        """测试直方图更新"""
        from presentation.panels.simulation.monte_carlo_result_tab import HistogramChart
        
        chart = HistogramChart()
        values = [38.0 + i * 0.1 for i in range(100)]
        
        # 不应抛出异常
        chart.update_histogram(values=values, bins=20, mean=40.5)
    
    def test_histogram_clear(self, qt_app):
        """测试直方图清空"""
        from presentation.panels.simulation.monte_carlo_result_tab import HistogramChart
        
        chart = HistogramChart()
        values = [38.0 + i * 0.1 for i in range(100)]
        
        chart.update_histogram(values=values)
        chart.clear()
        
        # 清空后不应有数据
        assert chart._bar_item is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
