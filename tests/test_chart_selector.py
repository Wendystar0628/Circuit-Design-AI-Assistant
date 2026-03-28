# Test ChartSelector
"""
图表类型选择器测试

测试覆盖：
- ChartType 枚举功能
- ChartSelection 数据类序列化/反序列化
- ChartSelector 核心功能
- 图表与分析类型关联
- 持久化功能
- 事件发布
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from domain.simulation.service.chart_selector import (
    ChartType,
    ChartSelection,
    ChartSelector,
    ChartValidationResult,
    chart_selector,
    CONFIG_FILE_NAME,
    CONFIG_DIR,
    EVENT_CHART_SELECTION_CHANGED,
)


# ============================================================
# ChartType 枚举测试
# ============================================================

class TestChartType:
    """ChartType 枚举测试"""
    
    def test_all_chart_types_have_display_name(self):
        """所有图表类型都有显示名称"""
        for chart_type in ChartType:
            name = ChartType.get_display_name(chart_type)
            assert name is not None
            assert len(name) > 0
    
    def test_all_chart_types_have_category(self):
        """所有图表类型都有类别"""
        for chart_type in ChartType:
            category = ChartType.get_category(chart_type)
            assert category is not None
            assert category in [
                "waveform", "bode", "dc", "spectrum", "statistics",
                "sweep", "sensitivity", "pvt", "noise", "other"
            ]
    
    def test_bode_charts_in_bode_category(self):
        """Bode 图表属于 bode 类别"""
        bode_charts = [
            ChartType.BODE_MAGNITUDE,
            ChartType.BODE_PHASE,
            ChartType.BODE_COMBINED,
        ]
        for chart in bode_charts:
            assert ChartType.get_category(chart) == "bode"
    
    def test_statistics_charts_in_statistics_category(self):
        """统计图表属于 statistics 类别"""
        stats_charts = [
            ChartType.HISTOGRAM,
            ChartType.SCATTER,
            ChartType.BOX_PLOT,
        ]
        for chart in stats_charts:
            assert ChartType.get_category(chart) == "statistics"


# ============================================================
# ChartSelection 数据类测试
# ============================================================

class TestChartSelection:
    """ChartSelection 数据类测试"""
    
    def test_to_dict(self):
        """测试序列化为字典"""
        selection = ChartSelection(
            chart_type=ChartType.BODE_COMBINED,
            enabled=True,
            display_order=1,
        )
        data = selection.to_dict()
        
        assert data["type"] == "bode_combined"
        assert data["enabled"] is True
        assert data["order"] == 1
    
    def test_from_dict(self):
        """测试从字典反序列化"""
        data = {
            "type": "waveform_time",
            "enabled": False,
            "order": 5,
        }
        selection = ChartSelection.from_dict(data)
        
        assert selection.chart_type == ChartType.WAVEFORM_TIME
        assert selection.enabled is False
        assert selection.display_order == 5
    
    def test_from_dict_with_defaults(self):
        """测试从字典反序列化（使用默认值）"""
        data = {"type": "histogram"}
        selection = ChartSelection.from_dict(data)
        
        assert selection.chart_type == ChartType.HISTOGRAM
        assert selection.enabled is False  # 默认值
        assert selection.display_order == 99  # 默认值
    
    def test_roundtrip(self):
        """测试序列化/反序列化往返"""
        original = ChartSelection(
            chart_type=ChartType.FFT_SPECTRUM,
            enabled=True,
            display_order=8,
        )
        data = original.to_dict()
        restored = ChartSelection.from_dict(data)
        
        assert restored.chart_type == original.chart_type
        assert restored.enabled == original.enabled
        assert restored.display_order == original.display_order


# ============================================================
# ChartValidationResult 测试
# ============================================================

class TestChartValidationResult:
    """ChartValidationResult 测试"""
    
    def test_success(self):
        """测试成功结果"""
        result = ChartValidationResult.success()
        assert result.is_valid is True
        assert len(result.warnings) == 0
        assert len(result.errors) == 0
    
    def test_add_warning(self):
        """测试添加警告"""
        result = ChartValidationResult.success()
        result.add_warning("测试警告")
        
        assert result.is_valid is True  # 警告不影响有效性
        assert len(result.warnings) == 1
        assert "测试警告" in result.warnings
    
    def test_add_error(self):
        """测试添加错误"""
        result = ChartValidationResult.success()
        result.add_error("测试错误")
        
        assert result.is_valid is False  # 错误导致无效
        assert len(result.errors) == 1
        assert "测试错误" in result.errors


# ============================================================
# ChartSelector 核心功能测试
# ============================================================

class TestChartSelector:
    """ChartSelector 核心功能测试"""
    
    @pytest.fixture
    def selector(self):
        """创建新的选择器实例"""
        return ChartSelector()
    
    def test_get_available_charts(self, selector):
        """测试获取所有可用图表"""
        charts = selector.get_available_charts()
        assert len(charts) == len(ChartType)
        assert ChartType.BODE_COMBINED in charts
        assert ChartType.WAVEFORM_TIME in charts
    
    def test_get_charts_by_category(self, selector):
        """测试按类别获取图表"""
        bode_charts = selector.get_charts_by_category("bode")
        assert ChartType.BODE_COMBINED in bode_charts
        assert ChartType.BODE_MAGNITUDE in bode_charts
        assert ChartType.BODE_PHASE in bode_charts
        assert ChartType.WAVEFORM_TIME not in bode_charts
    
    def test_default_selections(self, selector):
        """测试默认选择"""
        # 默认启用的图表
        assert selector.is_enabled(ChartType.WAVEFORM_TIME) is True
        assert selector.is_enabled(ChartType.BODE_COMBINED) is True
        assert selector.is_enabled(ChartType.DC_TRANSFER) is True
        
        # 默认禁用的图表
        assert selector.is_enabled(ChartType.HISTOGRAM) is False
        assert selector.is_enabled(ChartType.TORNADO) is False
    
    def test_set_chart_enabled(self, selector):
        """测试启用/禁用图表"""
        # 禁用默认启用的图表
        selector.set_chart_enabled(ChartType.BODE_COMBINED, False, publish_event=False)
        assert selector.is_enabled(ChartType.BODE_COMBINED) is False
        
        # 启用默认禁用的图表
        selector.set_chart_enabled(ChartType.HISTOGRAM, True, publish_event=False)
        assert selector.is_enabled(ChartType.HISTOGRAM) is True
    
    def test_set_chart_order(self, selector):
        """测试设置图表顺序"""
        selector.set_chart_order(ChartType.HISTOGRAM, 1)
        selection = selector.get_selection(ChartType.HISTOGRAM)
        assert selection.display_order == 1
    
    def test_get_selected_charts_sorted(self, selector):
        """测试获取选中图表（按顺序排序）"""
        # 启用几个图表并设置顺序
        selector.set_chart_enabled(ChartType.HISTOGRAM, True, publish_event=False)
        selector.set_chart_order(ChartType.HISTOGRAM, 0)  # 最前
        
        selected = selector.get_selected_charts()
        assert len(selected) > 0
        
        # 验证排序
        orders = [s.display_order for s in selected]
        assert orders == sorted(orders)
    
    def test_disable_all_charts(self, selector):
        """测试禁用所有图表"""
        selector.disable_all_charts(publish_event=False)
        
        selected = selector.get_selected_charts()
        assert len(selected) == 0
    
    def test_set_selections_from_list(self, selector):
        """测试从列表设置选择"""
        enabled_types = [ChartType.HISTOGRAM, ChartType.SCATTER]
        selector.set_selections_from_list(enabled_types, publish_event=False)
        
        assert selector.is_enabled(ChartType.HISTOGRAM) is True
        assert selector.is_enabled(ChartType.SCATTER) is True
        assert selector.is_enabled(ChartType.BODE_COMBINED) is False
    
    def test_reset_to_default(self, selector):
        """测试重置为默认"""
        # 修改选择
        selector.disable_all_charts(publish_event=False)
        assert len(selector.get_selected_charts()) == 0
        
        # 重置
        selector.reset_to_default(publish_event=False)
        assert selector.is_enabled(ChartType.WAVEFORM_TIME) is True


# ============================================================
# 图表与分析类型关联测试
# ============================================================

class TestChartAnalysisMapping:
    """图表与分析类型关联测试"""
    
    @pytest.fixture
    def selector(self):
        return ChartSelector()
    
    def test_ac_analysis_charts(self, selector):
        """测试 AC 分析关联的图表"""
        charts = selector.get_available_charts_for_analyses(["ac"])
        assert ChartType.BODE_COMBINED in charts
        assert ChartType.BODE_MAGNITUDE in charts
        assert ChartType.WAVEFORM_FREQ in charts
    
    def test_tran_analysis_charts(self, selector):
        """测试瞬态分析关联的图表"""
        charts = selector.get_available_charts_for_analyses(["tran"])
        assert ChartType.WAVEFORM_TIME in charts
        assert ChartType.FFT_SPECTRUM in charts
    
    def test_monte_carlo_analysis_charts(self, selector):
        """测试蒙特卡洛分析关联的图表"""
        charts = selector.get_available_charts_for_analyses(["monte_carlo"])
        assert ChartType.HISTOGRAM in charts
        assert ChartType.BOX_PLOT in charts
        assert ChartType.SCATTER in charts
    
    def test_multiple_analyses_charts(self, selector):
        """测试多个分析类型关联的图表（去重）"""
        charts = selector.get_available_charts_for_analyses(["ac", "tran"])
        # 应该包含两种分析的图表
        assert ChartType.BODE_COMBINED in charts
        assert ChartType.WAVEFORM_TIME in charts
    
    def test_get_recommended_charts(self, selector):
        """测试获取推荐图表"""
        recommended = selector.get_recommended_charts(["ac"])
        # 应该推荐组合图而非单独的幅度/相位图
        assert ChartType.BODE_COMBINED in recommended
        # 每个类别只推荐一个
        bode_count = sum(1 for c in recommended if ChartType.get_category(c) == "bode")
        assert bode_count == 1
    
    def test_enable_charts_for_analyses(self, selector):
        """测试根据分析类型启用图表"""
        selector.disable_all_charts(publish_event=False)
        selector.enable_charts_for_analyses(["monte_carlo"], publish_event=False)
        
        # 应该启用蒙特卡洛相关的图表
        assert selector.is_enabled(ChartType.HISTOGRAM) is True


# ============================================================
# 持久化测试
# ============================================================

class TestChartSelectorPersistence:
    """ChartSelector 持久化测试"""
    
    @pytest.fixture
    def selector(self):
        return ChartSelector()
    
    @pytest.fixture
    def temp_project(self, tmp_path):
        """创建临时项目目录"""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        return str(project_dir)
    
    def test_save_selection(self, selector, temp_project):
        """测试保存选择"""
        # 修改选择
        selector.set_chart_enabled(ChartType.HISTOGRAM, True, publish_event=False)
        
        # 保存
        result = selector.save_selection(temp_project)
        assert result is True
        
        # 验证文件存在
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        assert config_path.exists()
        
        # 验证内容
        content = json.loads(config_path.read_text(encoding="utf-8"))
        assert "version" in content
        assert "selections" in content
    
    def test_load_selection(self, selector, temp_project):
        """测试加载选择"""
        # 先保存
        selector.set_chart_enabled(ChartType.TORNADO, True, publish_event=False)
        selector.save_selection(temp_project)
        
        # 创建新实例并加载
        new_selector = ChartSelector()
        result = new_selector.load_selection(temp_project)
        
        assert result is True
        assert new_selector.is_enabled(ChartType.TORNADO) is True
    
    def test_load_nonexistent_config(self, selector, temp_project):
        """测试加载不存在的配置"""
        result = selector.load_selection(temp_project)
        assert result is True  # 不存在时返回 True，使用默认配置
    
    def test_load_invalid_json(self, selector, temp_project):
        """测试加载无效 JSON"""
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("invalid json", encoding="utf-8")
        
        result = selector.load_selection(temp_project)
        assert result is False


# ============================================================
# 校验测试
# ============================================================

class TestChartSelectorValidation:
    """ChartSelector 校验测试"""
    
    @pytest.fixture
    def selector(self):
        return ChartSelector()
    
    def test_validate_no_charts_enabled(self, selector):
        """测试无图表启用时的校验"""
        selector.disable_all_charts(publish_event=False)
        result = selector.validate_selection()
        
        assert result.is_valid is True  # 仅警告，不阻止
        assert len(result.warnings) > 0
    
    def test_validate_with_analysis_types(self, selector):
        """测试带分析类型的校验"""
        selector.disable_all_charts(publish_event=False)
        result = selector.validate_selection(analysis_types=["ac"])
        
        # 应该警告有可用图表未启用
        assert len(result.warnings) > 0
    
    def test_validate_matching_charts(self, selector):
        """测试匹配的图表选择"""
        selector.enable_charts_for_analyses(["ac"], publish_event=False)
        result = selector.validate_selection(analysis_types=["ac"])
        
        # 不应该有关于未启用图表的警告
        assert result.is_valid is True


# ============================================================
# 事件发布测试
# ============================================================

class TestChartSelectorEvents:
    """ChartSelector 事件发布测试"""
    
    def test_event_published_on_enable(self):
        """测试启用图表时发布事件"""
        mock_bus = MagicMock()
        selector = ChartSelector(event_bus=mock_bus)
        
        selector.set_chart_enabled(ChartType.HISTOGRAM, True)
        
        mock_bus.publish.assert_called()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == EVENT_CHART_SELECTION_CHANGED
    
    def test_event_not_published_when_disabled(self):
        """测试禁用事件发布时不发布"""
        mock_bus = MagicMock()
        selector = ChartSelector(event_bus=mock_bus)
        
        selector.set_chart_enabled(ChartType.HISTOGRAM, True, publish_event=False)
        
        mock_bus.publish.assert_not_called()
    
    def test_event_data_structure(self):
        """测试事件数据结构"""
        mock_bus = MagicMock()
        selector = ChartSelector(event_bus=mock_bus)
        
        selector.set_chart_enabled(ChartType.HISTOGRAM, True)
        
        call_args = mock_bus.publish.call_args
        event_data = call_args[0][1]
        
        assert "enabled_charts" in event_data
        assert "disabled_charts" in event_data
        assert "source" in event_data


# ============================================================
# 模块级单例测试
# ============================================================

class TestModuleSingleton:
    """模块级单例测试"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert chart_selector is not None
        assert isinstance(chart_selector, ChartSelector)
    
    def test_singleton_functional(self):
        """测试单例功能正常"""
        charts = chart_selector.get_available_charts()
        assert len(charts) > 0
