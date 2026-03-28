# Test Analysis Selector
"""
分析类型选择器测试

测试覆盖：
- AnalysisType 枚举方法
- AnalysisSelection 数据类序列化
- AnalysisSelector 核心功能
- 持久化和加载
- 校验逻辑
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from domain.simulation.service.analysis_selector import (
    AnalysisType,
    AnalysisSelection,
    AnalysisSelector,
    SelectionValidationResult,
    analysis_selector,
    CONFIG_FILE_NAME,
    CONFIG_DIR,
)


# ============================================================
# AnalysisType 枚举测试
# ============================================================

class TestAnalysisType:
    """AnalysisType 枚举测试"""
    
    def test_basic_analysis_types(self):
        """测试基础分析类型识别"""
        basic_types = [
            AnalysisType.OP,
            AnalysisType.AC,
            AnalysisType.DC,
            AnalysisType.TRANSIENT,
            AnalysisType.NOISE,
        ]
        for t in basic_types:
            assert AnalysisType.is_basic(t) is True
            assert AnalysisType.is_advanced(t) is False
    
    def test_advanced_analysis_types(self):
        """测试高级分析类型识别"""
        advanced_types = [
            AnalysisType.PVT,
            AnalysisType.MONTE_CARLO,
            AnalysisType.PARAMETRIC,
            AnalysisType.WORST_CASE,
            AnalysisType.SENSITIVITY,
        ]
        for t in advanced_types:
            assert AnalysisType.is_advanced(t) is True
            assert AnalysisType.is_basic(t) is False
    
    def test_display_names(self):
        """测试显示名称"""
        assert "AC" in AnalysisType.get_display_name(AnalysisType.AC)
        assert "PVT" in AnalysisType.get_display_name(AnalysisType.PVT)
        assert "蒙特卡洛" in AnalysisType.get_display_name(AnalysisType.MONTE_CARLO)
    
    def test_enum_values(self):
        """测试枚举值"""
        assert AnalysisType.AC.value == "ac"
        assert AnalysisType.TRANSIENT.value == "tran"
        assert AnalysisType.MONTE_CARLO.value == "monte_carlo"


# ============================================================
# AnalysisSelection 数据类测试
# ============================================================

class TestAnalysisSelection:
    """AnalysisSelection 数据类测试"""
    
    def test_to_dict(self):
        """测试序列化"""
        selection = AnalysisSelection(
            analysis_type=AnalysisType.AC,
            enabled=True,
            priority=1,
        )
        data = selection.to_dict()
        
        assert data["type"] == "ac"
        assert data["enabled"] is True
        assert data["priority"] == 1
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "type": "tran",
            "enabled": False,
            "priority": 5,
        }
        selection = AnalysisSelection.from_dict(data)
        
        assert selection.analysis_type == AnalysisType.TRANSIENT
        assert selection.enabled is False
        assert selection.priority == 5
    
    def test_from_dict_defaults(self):
        """测试反序列化默认值"""
        data = {"type": "dc"}
        selection = AnalysisSelection.from_dict(data)
        
        assert selection.analysis_type == AnalysisType.DC
        assert selection.enabled is False
        assert selection.priority == 99
    
    def test_roundtrip(self):
        """测试序列化往返"""
        original = AnalysisSelection(
            analysis_type=AnalysisType.PVT,
            enabled=True,
            priority=10,
        )
        restored = AnalysisSelection.from_dict(original.to_dict())
        
        assert restored.analysis_type == original.analysis_type
        assert restored.enabled == original.enabled
        assert restored.priority == original.priority


# ============================================================
# AnalysisSelector 核心功能测试
# ============================================================

class TestAnalysisSelectorCore:
    """AnalysisSelector 核心功能测试"""
    
    @pytest.fixture
    def selector(self):
        """创建新的选择器实例"""
        return AnalysisSelector()
    
    def test_default_selections(self, selector):
        """测试默认选择"""
        # 基础分析默认启用（除 NOISE）
        assert selector.is_enabled(AnalysisType.OP) is True
        assert selector.is_enabled(AnalysisType.AC) is True
        assert selector.is_enabled(AnalysisType.DC) is True
        assert selector.is_enabled(AnalysisType.TRANSIENT) is True
        assert selector.is_enabled(AnalysisType.NOISE) is False
        
        # 高级分析默认禁用
        assert selector.is_enabled(AnalysisType.PVT) is False
        assert selector.is_enabled(AnalysisType.MONTE_CARLO) is False
    
    def test_get_available_analyses(self, selector):
        """测试获取所有可用分析类型"""
        available = selector.get_available_analyses()
        assert len(available) == len(AnalysisType)
        assert AnalysisType.AC in available
        assert AnalysisType.PVT in available
    
    def test_get_basic_analyses(self, selector):
        """测试获取基础分析类型"""
        basic = selector.get_basic_analyses()
        assert len(basic) == 5
        assert AnalysisType.AC in basic
        assert AnalysisType.PVT not in basic
    
    def test_get_advanced_analyses(self, selector):
        """测试获取高级分析类型"""
        advanced = selector.get_advanced_analyses()
        assert len(advanced) == 5
        assert AnalysisType.PVT in advanced
        assert AnalysisType.AC not in advanced
    
    def test_get_selected_analyses(self, selector):
        """测试获取选中的分析"""
        selected = selector.get_selected_analyses()
        # 默认启用 OP, AC, DC, TRANSIENT
        assert len(selected) == 4
        
        enabled_types = {s.analysis_type for s in selected}
        assert AnalysisType.AC in enabled_types
        assert AnalysisType.NOISE not in enabled_types
    
    def test_set_analysis_enabled(self, selector):
        """测试启用/禁用分析"""
        # 禁用 AC
        selector.set_analysis_enabled(AnalysisType.AC, False, publish_event=False)
        assert selector.is_enabled(AnalysisType.AC) is False
        
        # 启用 PVT
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        assert selector.is_enabled(AnalysisType.PVT) is True
    
    def test_set_analysis_priority(self, selector):
        """测试设置优先级"""
        selector.set_analysis_priority(AnalysisType.AC, 100)
        selection = selector.get_selection(AnalysisType.AC)
        assert selection.priority == 100
    
    def test_get_execution_order(self, selector):
        """测试获取执行顺序"""
        order = selector.get_execution_order()
        
        # 应该按优先级排序
        assert order[0] == AnalysisType.OP  # priority=0
        assert order[1] == AnalysisType.AC  # priority=1
        
        # 禁用的不应该出现
        assert AnalysisType.NOISE not in order
        assert AnalysisType.PVT not in order
    
    def test_enable_all_basic(self, selector):
        """测试启用所有基础分析"""
        # 先禁用一些
        selector.set_analysis_enabled(AnalysisType.AC, False, publish_event=False)
        selector.set_analysis_enabled(AnalysisType.NOISE, False, publish_event=False)
        
        # 启用所有基础
        selector.enable_all_basic(publish_event=False)
        
        for t in selector.get_basic_analyses():
            assert selector.is_enabled(t) is True
    
    def test_disable_all_advanced(self, selector):
        """测试禁用所有高级分析"""
        # 先启用一些
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        selector.set_analysis_enabled(AnalysisType.MONTE_CARLO, True, publish_event=False)
        
        # 禁用所有高级
        selector.disable_all_advanced(publish_event=False)
        
        for t in selector.get_advanced_analyses():
            assert selector.is_enabled(t) is False
    
    def test_set_selections_from_list(self, selector):
        """测试从列表设置选择"""
        enabled_types = [AnalysisType.AC, AnalysisType.PVT]
        selector.set_selections_from_list(enabled_types, publish_event=False)
        
        assert selector.is_enabled(AnalysisType.AC) is True
        assert selector.is_enabled(AnalysisType.PVT) is True
        assert selector.is_enabled(AnalysisType.DC) is False
        assert selector.is_enabled(AnalysisType.OP) is False
    
    def test_reset_to_default(self, selector):
        """测试重置为默认"""
        # 修改一些选择
        selector.set_analysis_enabled(AnalysisType.AC, False, publish_event=False)
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        
        # 重置
        selector.reset_to_default(publish_event=False)
        
        # 验证恢复默认
        assert selector.is_enabled(AnalysisType.AC) is True
        assert selector.is_enabled(AnalysisType.PVT) is False


# ============================================================
# 持久化测试
# ============================================================

class TestAnalysisSelectorPersistence:
    """AnalysisSelector 持久化测试"""
    
    @pytest.fixture
    def selector(self):
        """创建新的选择器实例"""
        return AnalysisSelector()
    
    @pytest.fixture
    def temp_project(self, tmp_path):
        """创建临时项目目录"""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        return str(project_dir)
    
    def test_save_selection(self, selector, temp_project):
        """测试保存选择"""
        # 修改选择
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        
        # 保存
        result = selector.save_selection(temp_project)
        assert result is True
        
        # 验证文件存在
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        assert config_path.exists()
        
        # 验证内容
        content = json.loads(config_path.read_text(encoding="utf-8"))
        assert content["version"] == "1.0"
        assert len(content["selections"]) == len(AnalysisType)
    
    def test_load_selection(self, selector, temp_project):
        """测试加载选择"""
        # 先保存
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        selector.set_analysis_enabled(AnalysisType.AC, False, publish_event=False)
        selector.save_selection(temp_project)
        
        # 创建新实例并加载
        new_selector = AnalysisSelector()
        result = new_selector.load_selection(temp_project)
        
        assert result is True
        assert new_selector.is_enabled(AnalysisType.PVT) is True
        assert new_selector.is_enabled(AnalysisType.AC) is False
    
    def test_load_nonexistent_config(self, selector, temp_project):
        """测试加载不存在的配置"""
        result = selector.load_selection(temp_project)
        # 应该成功，保持默认配置
        assert result is True
        assert selector.is_enabled(AnalysisType.AC) is True
    
    def test_load_invalid_json(self, selector, temp_project):
        """测试加载无效 JSON"""
        config_path = Path(temp_project) / CONFIG_DIR / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("invalid json {", encoding="utf-8")
        
        result = selector.load_selection(temp_project)
        assert result is False


# ============================================================
# 校验测试
# ============================================================

class TestAnalysisSelectorValidation:
    """AnalysisSelector 校验测试"""
    
    @pytest.fixture
    def selector(self):
        """创建新的选择器实例"""
        return AnalysisSelector()
    
    def test_validate_default_selection(self, selector):
        """测试默认选择校验"""
        result = selector.validate_selection()
        assert result.is_valid is True
        assert len(result.errors) == 0
    
    def test_validate_no_selection(self, selector):
        """测试无选择校验"""
        # 禁用所有
        for t in AnalysisType:
            selector.set_analysis_enabled(t, False, publish_event=False)
        
        result = selector.validate_selection()
        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "至少需要启用一个分析类型" in result.errors[0]
    
    def test_validate_advanced_without_basic(self, selector):
        """测试仅启用高级分析的警告"""
        # 禁用所有基础，启用高级
        for t in selector.get_basic_analyses():
            selector.set_analysis_enabled(t, False, publish_event=False)
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        
        result = selector.validate_selection()
        # 应该有警告但仍然有效
        assert result.is_valid is True
        assert len(result.warnings) > 0


# ============================================================
# 事件发布测试
# ============================================================

class TestAnalysisSelectorEvents:
    """AnalysisSelector 事件发布测试"""
    
    def test_event_on_enable(self):
        """测试启用时发布事件"""
        mock_bus = MagicMock()
        selector = AnalysisSelector(event_bus=mock_bus)
        
        selector.set_analysis_enabled(AnalysisType.PVT, True)
        
        mock_bus.publish.assert_called()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "analysis_selection_changed"
    
    def test_no_event_when_disabled(self):
        """测试禁用事件发布时不发布"""
        mock_bus = MagicMock()
        selector = AnalysisSelector(event_bus=mock_bus)
        
        selector.set_analysis_enabled(AnalysisType.PVT, True, publish_event=False)
        
        mock_bus.publish.assert_not_called()


# ============================================================
# 模块级单例测试
# ============================================================

class TestModuleSingleton:
    """模块级单例测试"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert analysis_selector is not None
        assert isinstance(analysis_selector, AnalysisSelector)
    
    def test_singleton_has_default_selections(self):
        """测试单例有默认选择"""
        # 重置以确保测试隔离
        analysis_selector.reset_to_default(publish_event=False)
        assert analysis_selector.is_enabled(AnalysisType.AC) is True
