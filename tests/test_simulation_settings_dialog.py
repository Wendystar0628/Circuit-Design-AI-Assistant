# Test Simulation Settings Dialog
"""
仿真设置对话框测试

测试内容：
- 对话框初始化
- 分析类型选择功能
- 图表类型选择功能
- 设置加载和保存
- 快捷操作功能
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from domain.simulation.service.analysis_selector import (
    AnalysisSelector,
    AnalysisType,
)
from domain.simulation.service.chart_selector import (
    ChartSelector,
    ChartType,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def analysis_selector():
    """创建分析选择器实例"""
    return AnalysisSelector()


@pytest.fixture
def chart_selector():
    """创建图表选择器实例"""
    return ChartSelector()


@pytest.fixture
def temp_project_dir():
    """创建临时项目目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ============================================================
# 分析选择器集成测试
# ============================================================

class TestAnalysisSelectorIntegration:
    """分析选择器集成测试"""
    
    def test_default_basic_analyses_enabled(self, analysis_selector):
        """测试默认启用基础分析"""
        # OP, AC, DC, TRANSIENT 默认启用
        assert analysis_selector.is_enabled(AnalysisType.OP)
        assert analysis_selector.is_enabled(AnalysisType.AC)
        assert analysis_selector.is_enabled(AnalysisType.DC)
        assert analysis_selector.is_enabled(AnalysisType.TRANSIENT)
        # NOISE 默认禁用
        assert not analysis_selector.is_enabled(AnalysisType.NOISE)
    
    def test_default_advanced_analyses_disabled(self, analysis_selector):
        """测试默认禁用高级分析"""
        assert not analysis_selector.is_enabled(AnalysisType.PVT)
        assert not analysis_selector.is_enabled(AnalysisType.MONTE_CARLO)
        assert not analysis_selector.is_enabled(AnalysisType.PARAMETRIC)
        assert not analysis_selector.is_enabled(AnalysisType.WORST_CASE)
        assert not analysis_selector.is_enabled(AnalysisType.SENSITIVITY)
    
    def test_set_analysis_enabled(self, analysis_selector):
        """测试启用/禁用分析"""
        # 禁用 AC
        analysis_selector.set_analysis_enabled(
            AnalysisType.AC, False, publish_event=False
        )
        assert not analysis_selector.is_enabled(AnalysisType.AC)
        
        # 启用 PVT
        analysis_selector.set_analysis_enabled(
            AnalysisType.PVT, True, publish_event=False
        )
        assert analysis_selector.is_enabled(AnalysisType.PVT)
    
    def test_get_execution_order(self, analysis_selector):
        """测试获取执行顺序"""
        order = analysis_selector.get_execution_order()
        
        # 应该按优先级排序
        assert len(order) > 0
        # OP 应该在最前面（优先级 0）
        assert order[0] == AnalysisType.OP
    
    def test_save_and_load_selection(self, analysis_selector, temp_project_dir):
        """测试保存和加载选择"""
        # 修改选择
        analysis_selector.set_analysis_enabled(
            AnalysisType.AC, False, publish_event=False
        )
        analysis_selector.set_analysis_enabled(
            AnalysisType.PVT, True, publish_event=False
        )
        
        # 保存
        assert analysis_selector.save_selection(temp_project_dir)
        
        # 创建新实例并加载
        new_selector = AnalysisSelector()
        assert new_selector.load_selection(temp_project_dir)
        
        # 验证加载的选择
        assert not new_selector.is_enabled(AnalysisType.AC)
        assert new_selector.is_enabled(AnalysisType.PVT)
    
    def test_reset_to_default(self, analysis_selector):
        """测试重置为默认"""
        # 修改选择
        analysis_selector.set_analysis_enabled(
            AnalysisType.AC, False, publish_event=False
        )
        
        # 重置
        analysis_selector.reset_to_default(publish_event=False)
        
        # 验证恢复默认
        assert analysis_selector.is_enabled(AnalysisType.AC)
    
    def test_set_selections_from_list(self, analysis_selector):
        """测试从列表设置选择"""
        enabled_list = [AnalysisType.AC, AnalysisType.TRANSIENT]
        analysis_selector.set_selections_from_list(
            enabled_list, publish_event=False
        )
        
        # 验证只有列表中的类型被启用
        assert analysis_selector.is_enabled(AnalysisType.AC)
        assert analysis_selector.is_enabled(AnalysisType.TRANSIENT)
        assert not analysis_selector.is_enabled(AnalysisType.OP)
        assert not analysis_selector.is_enabled(AnalysisType.DC)


# ============================================================
# 图表选择器集成测试
# ============================================================

class TestChartSelectorIntegration:
    """图表选择器集成测试"""
    
    def test_default_charts_enabled(self, chart_selector):
        """测试默认启用的图表"""
        # 时域波形、Bode 组合图、DC 传输默认启用
        assert chart_selector.is_enabled(ChartType.WAVEFORM_TIME)
        assert chart_selector.is_enabled(ChartType.BODE_COMBINED)
        assert chart_selector.is_enabled(ChartType.DC_TRANSFER)
    
    def test_default_charts_disabled(self, chart_selector):
        """测试默认禁用的图表"""
        # 统计图表默认禁用
        assert not chart_selector.is_enabled(ChartType.HISTOGRAM)
        assert not chart_selector.is_enabled(ChartType.SCATTER)
        # 3D 图表默认禁用
        assert not chart_selector.is_enabled(ChartType.SURFACE_3D)
    
    def test_set_chart_enabled(self, chart_selector):
        """测试启用/禁用图表"""
        # 禁用时域波形
        chart_selector.set_chart_enabled(
            ChartType.WAVEFORM_TIME, False, publish_event=False
        )
        assert not chart_selector.is_enabled(ChartType.WAVEFORM_TIME)
        
        # 启用直方图
        chart_selector.set_chart_enabled(
            ChartType.HISTOGRAM, True, publish_event=False
        )
        assert chart_selector.is_enabled(ChartType.HISTOGRAM)
    
    def test_get_recommended_charts(self, chart_selector):
        """测试获取推荐图表"""
        # AC 分析推荐 Bode 图
        recommended = chart_selector.get_recommended_charts(["ac"])
        assert ChartType.BODE_COMBINED in recommended
        
        # 瞬态分析推荐时域波形
        recommended = chart_selector.get_recommended_charts(["tran"])
        assert ChartType.WAVEFORM_TIME in recommended
        
        # 蒙特卡洛推荐直方图
        recommended = chart_selector.get_recommended_charts(["monte_carlo"])
        assert ChartType.HISTOGRAM in recommended
    
    def test_get_charts_by_category(self, chart_selector):
        """测试按类别获取图表"""
        bode_charts = chart_selector.get_charts_by_category("bode")
        assert ChartType.BODE_MAGNITUDE in bode_charts
        assert ChartType.BODE_PHASE in bode_charts
        assert ChartType.BODE_COMBINED in bode_charts
    
    def test_save_and_load_selection(self, chart_selector, temp_project_dir):
        """测试保存和加载选择"""
        # 修改选择
        chart_selector.set_chart_enabled(
            ChartType.WAVEFORM_TIME, False, publish_event=False
        )
        chart_selector.set_chart_enabled(
            ChartType.HISTOGRAM, True, publish_event=False
        )
        
        # 保存
        assert chart_selector.save_selection(temp_project_dir)
        
        # 创建新实例并加载
        new_selector = ChartSelector()
        assert new_selector.load_selection(temp_project_dir)
        
        # 验证加载的选择
        assert not new_selector.is_enabled(ChartType.WAVEFORM_TIME)
        assert new_selector.is_enabled(ChartType.HISTOGRAM)
    
    def test_reset_to_default(self, chart_selector):
        """测试重置为默认"""
        # 修改选择
        chart_selector.set_chart_enabled(
            ChartType.WAVEFORM_TIME, False, publish_event=False
        )
        
        # 重置
        chart_selector.reset_to_default(publish_event=False)
        
        # 验证恢复默认
        assert chart_selector.is_enabled(ChartType.WAVEFORM_TIME)


# ============================================================
# 对话框单元测试（无 GUI）
# ============================================================

class TestSimulationSettingsDialogLogic:
    """对话框逻辑测试（不依赖 GUI）"""
    
    def test_analysis_type_display_names(self):
        """测试分析类型显示名称"""
        assert "AC" in AnalysisType.get_display_name(AnalysisType.AC)
        assert "DC" in AnalysisType.get_display_name(AnalysisType.DC)
        assert "瞬态" in AnalysisType.get_display_name(AnalysisType.TRANSIENT)
        assert "PVT" in AnalysisType.get_display_name(AnalysisType.PVT)
    
    def test_chart_type_display_names(self):
        """测试图表类型显示名称"""
        assert "时域" in ChartType.get_display_name(ChartType.WAVEFORM_TIME)
        assert "Bode" in ChartType.get_display_name(ChartType.BODE_COMBINED)
        assert "直方图" in ChartType.get_display_name(ChartType.HISTOGRAM)
    
    def test_chart_type_categories(self):
        """测试图表类型分类"""
        assert ChartType.get_category(ChartType.WAVEFORM_TIME) == "waveform"
        assert ChartType.get_category(ChartType.BODE_COMBINED) == "bode"
        assert ChartType.get_category(ChartType.HISTOGRAM) == "statistics"
        assert ChartType.get_category(ChartType.TORNADO) == "sensitivity"
    
    def test_analysis_type_classification(self):
        """测试分析类型分类"""
        # 基础分析
        assert AnalysisType.is_basic(AnalysisType.OP)
        assert AnalysisType.is_basic(AnalysisType.AC)
        assert AnalysisType.is_basic(AnalysisType.DC)
        assert AnalysisType.is_basic(AnalysisType.TRANSIENT)
        assert AnalysisType.is_basic(AnalysisType.NOISE)
        
        # 高级分析
        assert AnalysisType.is_advanced(AnalysisType.PVT)
        assert AnalysisType.is_advanced(AnalysisType.MONTE_CARLO)
        assert AnalysisType.is_advanced(AnalysisType.PARAMETRIC)
        assert AnalysisType.is_advanced(AnalysisType.WORST_CASE)
        assert AnalysisType.is_advanced(AnalysisType.SENSITIVITY)
        
        # 互斥
        assert not AnalysisType.is_basic(AnalysisType.PVT)
        assert not AnalysisType.is_advanced(AnalysisType.AC)


# ============================================================
# 配置持久化测试
# ============================================================

class TestConfigPersistence:
    """配置持久化测试"""
    
    def test_config_file_created(self, analysis_selector, temp_project_dir):
        """测试配置文件创建"""
        analysis_selector.save_selection(temp_project_dir)
        
        config_path = Path(temp_project_dir) / ".circuit_ai" / "analysis_selection.json"
        assert config_path.exists()
    
    def test_chart_config_file_created(self, chart_selector, temp_project_dir):
        """测试图表配置文件创建"""
        chart_selector.save_selection(temp_project_dir)
        
        config_path = Path(temp_project_dir) / ".circuit_ai" / "chart_selection.json"
        assert config_path.exists()
    
    def test_load_nonexistent_config(self, analysis_selector, temp_project_dir):
        """测试加载不存在的配置"""
        # 应该返回 True（使用默认配置）
        assert analysis_selector.load_selection(temp_project_dir)
        
        # 默认配置应该生效
        assert analysis_selector.is_enabled(AnalysisType.AC)


# ============================================================
# 校验测试
# ============================================================

class TestValidation:
    """校验测试"""
    
    def test_analysis_validation_no_selection(self, analysis_selector):
        """测试无选择时的校验"""
        # 禁用所有分析
        for at in AnalysisType:
            analysis_selector.set_analysis_enabled(at, False, publish_event=False)
        
        result = analysis_selector.validate_selection()
        assert not result.is_valid
        assert len(result.errors) > 0
    
    def test_analysis_validation_advanced_without_basic(self, analysis_selector):
        """测试只启用高级分析时的警告"""
        # 禁用所有基础分析
        for at in analysis_selector.get_basic_analyses():
            analysis_selector.set_analysis_enabled(at, False, publish_event=False)
        
        # 启用高级分析
        analysis_selector.set_analysis_enabled(
            AnalysisType.PVT, True, publish_event=False
        )
        
        result = analysis_selector.validate_selection()
        # 应该有警告但仍然有效
        assert result.is_valid
        assert len(result.warnings) > 0
    
    def test_chart_validation_no_selection(self, chart_selector):
        """测试无图表选择时的警告"""
        # 禁用所有图表
        chart_selector.disable_all_charts(publish_event=False)
        
        result = chart_selector.validate_selection()
        # 应该有警告但仍然有效
        assert result.is_valid
        assert len(result.warnings) > 0
