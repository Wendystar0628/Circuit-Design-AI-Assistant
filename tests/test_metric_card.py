# Test MetricCard Component
"""
MetricCard 组件测试

测试指标卡片的核心功能：
- 指标数据设置
- 达标状态显示
- 高亮状态切换
- 趋势指示
- 信号发射
"""

import pytest
from unittest.mock import MagicMock

# 尝试导入 PyQt6，若不可用则跳过测试
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例（模块级别共享）"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def metric_card(app):
    """创建 MetricCard 实例"""
    from presentation.panels.simulation.metric_card import MetricCard
    card = MetricCard()
    yield card
    card.deleteLater()


# ============================================================
# 基础功能测试
# ============================================================

class TestMetricCardBasic:
    """MetricCard 基础功能测试"""
    
    def test_init(self, metric_card):
        """测试初始化"""
        assert metric_card is not None
        assert metric_card.metric_name == ""
        assert metric_card.is_met is None
        assert metric_card.is_highlighted is False
    
    def test_set_metric_basic(self, metric_card):
        """测试设置基本指标数据"""
        metric_card.set_metric(
            name="增益",
            value="20.5 dB",
            unit="dB",
            target="≥ 20 dB",
            is_met=True
        )
        
        assert metric_card._name_label.text() == "增益"
        assert "20.5" in metric_card._value_label.text()
        assert metric_card._target_label.text() == "≥ 20 dB"
        assert metric_card.is_met is True
    
    def test_set_metric_without_target(self, metric_card):
        """测试设置无目标的指标"""
        metric_card.set_metric(
            name="带宽",
            value="10 MHz",
            unit="Hz"
        )
        
        assert metric_card._name_label.text() == "带宽"
        assert metric_card.is_met is None
        assert not metric_card._target_label.isVisible()
    
    def test_set_metric_failed(self, metric_card):
        """测试设置未达标的指标"""
        metric_card.set_metric(
            name="相位裕度",
            value="45°",
            target="≥ 60°",
            is_met=False
        )
        
        assert metric_card.is_met is False
        assert "✗" in metric_card._status_icon.text()


# ============================================================
# 状态更新测试
# ============================================================

class TestMetricCardStatus:
    """MetricCard 状态更新测试"""
    
    def test_update_status_to_met(self, metric_card):
        """测试更新为达标状态"""
        metric_card.set_metric(name="Test", value="10", is_met=False)
        metric_card.update_status(True)
        
        assert metric_card.is_met is True
        assert "✓" in metric_card._status_icon.text()
    
    def test_update_status_to_not_met(self, metric_card):
        """测试更新为未达标状态"""
        metric_card.set_metric(name="Test", value="10", is_met=True)
        metric_card.update_status(False)
        
        assert metric_card.is_met is False
        assert "✗" in metric_card._status_icon.text()
    
    def test_update_status_to_none(self, metric_card):
        """测试更新为无目标状态"""
        metric_card.set_metric(name="Test", value="10", is_met=True)
        metric_card.update_status(None)
        
        assert metric_card.is_met is None
        assert metric_card._status_icon.text() == ""


# ============================================================
# 高亮状态测试
# ============================================================

class TestMetricCardHighlight:
    """MetricCard 高亮状态测试"""
    
    def test_set_highlight_on(self, metric_card):
        """测试开启高亮"""
        metric_card.set_highlight(True)
        assert metric_card.is_highlighted is True
    
    def test_set_highlight_off(self, metric_card):
        """测试关闭高亮"""
        metric_card.set_highlight(True)
        metric_card.set_highlight(False)
        assert metric_card.is_highlighted is False
    
    def test_highlight_toggle(self, metric_card):
        """测试高亮切换"""
        assert metric_card.is_highlighted is False
        metric_card.set_highlight(True)
        assert metric_card.is_highlighted is True
        metric_card.set_highlight(False)
        assert metric_card.is_highlighted is False


# ============================================================
# 趋势指示测试
# ============================================================

class TestMetricCardTrend:
    """MetricCard 趋势指示测试"""
    
    def test_trend_up(self, metric_card):
        """测试上升趋势"""
        metric_card.set_metric(name="Test", value="10", trend="up")
        assert "↑" in metric_card._trend_label.text()
    
    def test_trend_down(self, metric_card):
        """测试下降趋势"""
        metric_card.set_metric(name="Test", value="10", trend="down")
        assert "↓" in metric_card._trend_label.text()
    
    def test_trend_stable(self, metric_card):
        """测试稳定趋势"""
        metric_card.set_metric(name="Test", value="10", trend="stable")
        assert "→" in metric_card._trend_label.text()
    
    def test_trend_unknown(self, metric_card):
        """测试未知趋势"""
        metric_card.set_metric(name="Test", value="10", trend="unknown")
        assert metric_card._trend_label.text() == ""


# ============================================================
# 信号测试
# ============================================================

class TestMetricCardSignals:
    """MetricCard 信号测试"""
    
    def test_clicked_signal(self, metric_card):
        """测试点击信号"""
        metric_card.set_metric(name="TestMetric", value="10")
        
        # 使用 mock 捕获信号
        signal_received = []
        metric_card.clicked.connect(lambda name: signal_received.append(name))
        
        # 模拟点击
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF
        
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        metric_card.mousePressEvent(event)
        
        assert len(signal_received) == 1
        assert signal_received[0] == "TestMetric"


# ============================================================
# DisplayMetric 集成测试
# ============================================================

class TestMetricCardDisplayMetric:
    """MetricCard 与 DisplayMetric 集成测试"""
    
    def test_set_from_display_metric(self, metric_card):
        """测试从 DisplayMetric 设置数据"""
        from presentation.panels.simulation.simulation_view_model import DisplayMetric
        
        display_metric = DisplayMetric(
            name="gain",
            display_name="增益",
            value="20.5 dB",
            unit="dB",
            target="≥ 20 dB",
            is_met=True,
            trend="up",
            category="amplifier"
        )
        
        metric_card.set_from_display_metric(display_metric)
        
        assert metric_card._name_label.text() == "增益"
        assert "20.5" in metric_card._value_label.text()
        assert metric_card._target_label.text() == "≥ 20 dB"
        assert metric_card.is_met is True
        assert "↑" in metric_card._trend_label.text()


# ============================================================
# 边界条件测试
# ============================================================

class TestMetricCardEdgeCases:
    """MetricCard 边界条件测试"""
    
    def test_empty_values(self, metric_card):
        """测试空值"""
        metric_card.set_metric(name="", value="")
        assert metric_card._name_label.text() == ""
        assert metric_card._value_label.text() == ""
    
    def test_long_name(self, metric_card):
        """测试长名称"""
        long_name = "这是一个非常长的指标名称用于测试显示效果"
        metric_card.set_metric(name=long_name, value="10")
        assert metric_card._name_label.text() == long_name
    
    def test_special_characters(self, metric_card):
        """测试特殊字符"""
        metric_card.set_metric(
            name="THD+N",
            value="-80 dB",
            target="≤ -70 dB"
        )
        assert "THD+N" in metric_card._name_label.text()
        assert "-80" in metric_card._value_label.text()
    
    def test_unicode_unit(self, metric_card):
        """测试 Unicode 单位"""
        metric_card.set_metric(
            name="噪声",
            value="10 nV/√Hz",
            unit="nV/√Hz"
        )
        assert "√" in metric_card._value_label.text()
    
    def test_retranslate_ui(self, metric_card):
        """测试国际化方法存在"""
        # 确保方法存在且可调用
        metric_card.retranslate_ui()
