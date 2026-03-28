# Test MetricsPanel
"""
MetricsPanel 单元测试

测试指标显示面板的核心功能：
- 指标更新和显示
- 综合评分设置
- 清空操作
- 卡片高亮
- 国际化支持
"""

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from presentation.panels.simulation.metrics_panel import MetricsPanel, FlowLayout
from presentation.panels.simulation.simulation_view_model import DisplayMetric


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def metrics_panel(app):
    """创建 MetricsPanel 实例"""
    panel = MetricsPanel()
    yield panel
    panel.deleteLater()


@pytest.fixture
def sample_metrics():
    """创建示例指标列表"""
    return [
        DisplayMetric(
            name="gain",
            display_name="Gain",
            value="20.5 dB",
            unit="dB",
            target="≥ 20 dB",
            is_met=True,
            trend="up",
            category="amplifier",
            raw_value=20.5,
        ),
        DisplayMetric(
            name="bandwidth",
            display_name="Bandwidth",
            value="1.2 MHz",
            unit="Hz",
            target="≥ 1 MHz",
            is_met=True,
            trend="stable",
            category="amplifier",
            raw_value=1.2e6,
        ),
        DisplayMetric(
            name="phase_margin",
            display_name="Phase Margin",
            value="45°",
            unit="°",
            target="≥ 60°",
            is_met=False,
            trend="down",
            category="stability",
            raw_value=45.0,
        ),
    ]


# ============================================================
# 基础功能测试
# ============================================================

class TestMetricsPanelBasic:
    """MetricsPanel 基础功能测试"""
    
    def test_init(self, metrics_panel):
        """测试初始化"""
        assert metrics_panel is not None
        assert metrics_panel.card_count == 0
        assert metrics_panel.overall_score == 0.0
    
    def test_update_metrics(self, metrics_panel, sample_metrics):
        """测试更新指标"""
        metrics_panel.update_metrics(sample_metrics)
        
        assert metrics_panel.card_count == 3
        assert len(metrics_panel.metrics) == 3
    
    def test_update_metrics_empty(self, metrics_panel):
        """测试更新空指标列表"""
        metrics_panel.update_metrics([])
        
        assert metrics_panel.card_count == 0
        assert len(metrics_panel.metrics) == 0
    
    def test_set_overall_score(self, metrics_panel):
        """测试设置综合评分"""
        metrics_panel.set_overall_score(85.5)
        
        assert metrics_panel.overall_score == 85.5
    
    def test_set_overall_score_clamp(self, metrics_panel):
        """测试评分值范围限制"""
        metrics_panel.set_overall_score(150.0)
        assert metrics_panel.overall_score == 100.0
        
        # 负数值表示无目标模式，不再限制为0
        metrics_panel.set_overall_score(-10.0)
        assert metrics_panel.overall_score == -1.0  # 无目标模式返回 -1.0
    
    def test_set_overall_score_no_goals(self, metrics_panel):
        """测试无目标模式评分显示"""
        metrics_panel.set_overall_score(-1.0)
        assert metrics_panel.overall_score == -1.0
    
    def test_clear(self, metrics_panel, sample_metrics):
        """测试清空操作"""
        metrics_panel.update_metrics(sample_metrics)
        metrics_panel.set_overall_score(75.0)
        
        metrics_panel.clear()
        
        assert metrics_panel.card_count == 0
        assert metrics_panel.overall_score == 0.0
        assert len(metrics_panel.metrics) == 0


# ============================================================
# 卡片操作测试
# ============================================================

class TestMetricsPanelCards:
    """MetricsPanel 卡片操作测试"""
    
    def test_get_metric_card(self, metrics_panel, sample_metrics):
        """测试获取指定指标卡片"""
        metrics_panel.update_metrics(sample_metrics)
        
        card = metrics_panel.get_metric_card("gain")
        assert card is not None
        assert card.metric_name == "gain"
    
    def test_get_metric_card_not_found(self, metrics_panel, sample_metrics):
        """测试获取不存在的指标卡片"""
        metrics_panel.update_metrics(sample_metrics)
        
        card = metrics_panel.get_metric_card("nonexistent")
        assert card is None
    
    def test_highlight_metric(self, metrics_panel, sample_metrics):
        """测试高亮指标卡片"""
        metrics_panel.update_metrics(sample_metrics)
        
        metrics_panel.highlight_metric("gain", True)
        card = metrics_panel.get_metric_card("gain")
        assert card.is_highlighted is True
        
        metrics_panel.highlight_metric("gain", False)
        assert card.is_highlighted is False
    
    def test_card_clicked_signal(self, metrics_panel, sample_metrics):
        """测试卡片点击信号"""
        metrics_panel.update_metrics(sample_metrics)
        
        clicked_metric = []
        metrics_panel.metric_clicked.connect(lambda name: clicked_metric.append(name))
        
        card = metrics_panel.get_metric_card("bandwidth")
        card.clicked.emit("bandwidth")
        
        assert len(clicked_metric) == 1
        assert clicked_metric[0] == "bandwidth"


# ============================================================
# 布局测试
# ============================================================

class TestFlowLayout:
    """FlowLayout 测试"""
    
    def test_init(self, app):
        """测试初始化"""
        layout = FlowLayout()
        assert layout is not None
    
    def test_add_card(self, app):
        """测试添加卡片"""
        from presentation.panels.simulation.metric_card import MetricCard
        
        layout = FlowLayout()
        card = MetricCard()
        layout.add_card(card)
        
        assert len(layout._cards) == 1
    
    def test_clear_cards(self, app):
        """测试清除卡片"""
        from presentation.panels.simulation.metric_card import MetricCard
        
        layout = FlowLayout()
        card1 = MetricCard()
        card2 = MetricCard()
        layout.add_card(card1)
        layout.add_card(card2)
        
        layout.clear_cards()
        
        assert len(layout._cards) == 0


# ============================================================
# 国际化测试
# ============================================================

class TestMetricsPanelI18n:
    """MetricsPanel 国际化测试"""
    
    def test_retranslate_ui(self, metrics_panel):
        """测试重新翻译 UI"""
        # 不应抛出异常
        metrics_panel.retranslate_ui()
    
    @patch('shared.i18n_manager.I18nManager')
    def test_retranslate_ui_with_i18n(self, mock_i18n_class, metrics_panel):
        """测试使用 I18nManager 重新翻译"""
        mock_i18n = MagicMock()
        mock_i18n.get_text.side_effect = lambda key, default=None: {
            "simulation.overall_score": "综合评分",
            "simulation.no_metrics": "暂无指标",
        }.get(key, default)
        mock_i18n_class.return_value = mock_i18n
        
        metrics_panel.retranslate_ui()
        
        # 验证 retranslate_ui 执行成功（不抛出异常）
        assert True


# ============================================================
# 属性测试
# ============================================================

class TestMetricsPanelProperties:
    """MetricsPanel 属性测试"""
    
    def test_metrics_property(self, metrics_panel, sample_metrics):
        """测试 metrics 属性"""
        metrics_panel.update_metrics(sample_metrics)
        
        metrics = metrics_panel.metrics
        assert len(metrics) == 3
        # 验证返回的是副本
        metrics.clear()
        assert len(metrics_panel.metrics) == 3
    
    def test_overall_score_property(self, metrics_panel):
        """测试 overall_score 属性"""
        metrics_panel.set_overall_score(66.7)
        assert metrics_panel.overall_score == 66.7
    
    def test_card_count_property(self, metrics_panel, sample_metrics):
        """测试 card_count 属性"""
        assert metrics_panel.card_count == 0
        
        metrics_panel.update_metrics(sample_metrics)
        assert metrics_panel.card_count == 3


# ============================================================
# 边界条件测试
# ============================================================

class TestMetricsPanelEdgeCases:
    """MetricsPanel 边界条件测试"""
    
    def test_update_metrics_multiple_times(self, metrics_panel, sample_metrics):
        """测试多次更新指标"""
        metrics_panel.update_metrics(sample_metrics)
        assert metrics_panel.card_count == 3
        
        # 更新为更少的指标
        metrics_panel.update_metrics(sample_metrics[:1])
        assert metrics_panel.card_count == 1
        
        # 更新为更多的指标
        metrics_panel.update_metrics(sample_metrics)
        assert metrics_panel.card_count == 3
    
    def test_highlight_nonexistent_metric(self, metrics_panel, sample_metrics):
        """测试高亮不存在的指标"""
        metrics_panel.update_metrics(sample_metrics)
        
        # 不应抛出异常
        metrics_panel.highlight_metric("nonexistent", True)
    
    def test_get_card_before_update(self, metrics_panel):
        """测试更新前获取卡片"""
        card = metrics_panel.get_metric_card("gain")
        assert card is None


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
