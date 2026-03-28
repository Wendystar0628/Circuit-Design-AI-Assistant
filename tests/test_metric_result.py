# Test MetricResult - Performance Metric Result Data Class Tests
"""
指标结果数据类测试

测试内容：
- MetricResult 创建和属性访问
- 目标达标判断逻辑
- 序列化和反序列化
- 工厂方法
- 格式化输出
"""

import pytest

from domain.simulation.metrics.metric_result import (
    MetricCategory,
    MetricResult,
    create_metric_result,
    create_error_metric,
)


class TestMetricCategory:
    """测试指标类别枚举"""
    
    def test_category_values(self):
        """测试类别枚举值"""
        assert MetricCategory.AMPLIFIER.value == "amplifier"
        assert MetricCategory.NOISE.value == "noise"
        assert MetricCategory.DISTORTION.value == "distortion"
        assert MetricCategory.POWER.value == "power"
        assert MetricCategory.TRANSIENT.value == "transient"
        assert MetricCategory.GENERAL.value == "general"


class TestMetricResult:
    """测试指标结果数据类"""
    
    def test_basic_creation(self):
        """测试基本创建"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=20.5,
            unit="dB",
            category=MetricCategory.AMPLIFIER,
        )
        
        assert result.name == "gain"
        assert result.display_name == "增益"
        assert result.value == 20.5
        assert result.unit == "dB"
        assert result.category == MetricCategory.AMPLIFIER
        assert result.is_valid
        assert result.error_message is None
    
    def test_target_min_met(self):
        """测试最小值目标达标"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=25.0,
            unit="dB",
            target=20.0,
            target_type="min",
        )
        
        assert result.is_met is True
        assert result.status_icon == "✓"
    
    def test_target_min_not_met(self):
        """测试最小值目标未达标"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=15.0,
            unit="dB",
            target=20.0,
            target_type="min",
        )
        
        assert result.is_met is False
        assert result.status_icon == "✗"
    
    def test_target_max_met(self):
        """测试最大值目标达标"""
        result = MetricResult(
            name="noise",
            display_name="噪声",
            value=5.0,
            unit="nV/√Hz",
            target=10.0,
            target_type="max",
        )
        
        assert result.is_met is True
    
    def test_target_max_not_met(self):
        """测试最大值目标未达标"""
        result = MetricResult(
            name="noise",
            display_name="噪声",
            value=15.0,
            unit="nV/√Hz",
            target=10.0,
            target_type="max",
        )
        
        assert result.is_met is False
    
    def test_target_range_met(self):
        """测试范围目标达标"""
        result = MetricResult(
            name="bandwidth",
            display_name="带宽",
            value=15e6,
            unit="Hz",
            target=10e6,
            target_type="range",
            target_max=20e6,
        )
        
        assert result.is_met is True
    
    def test_target_range_not_met(self):
        """测试范围目标未达标"""
        result = MetricResult(
            name="bandwidth",
            display_name="带宽",
            value=25e6,
            unit="Hz",
            target=10e6,
            target_type="range",
            target_max=20e6,
        )
        
        assert result.is_met is False
    
    def test_no_target(self):
        """测试无目标时的状态"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=20.0,
            unit="dB",
        )
        
        assert result.is_met is None
        assert result.status_icon == "-"

    def test_formatted_value_db(self):
        """测试 dB 值格式化"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=20.5,
            unit="dB",
        )
        
        assert result.formatted_value == "20.50 dB"
    
    def test_formatted_value_mega(self):
        """测试兆级值格式化"""
        result = MetricResult(
            name="bandwidth",
            display_name="带宽",
            value=10e6,
            unit="Hz",
        )
        
        assert result.formatted_value == "10.00M Hz"
    
    def test_formatted_value_kilo(self):
        """测试千级值格式化"""
        result = MetricResult(
            name="frequency",
            display_name="频率",
            value=5000,
            unit="Hz",
        )
        
        assert result.formatted_value == "5.00k Hz"
    
    def test_formatted_value_milli(self):
        """测试毫级值格式化"""
        result = MetricResult(
            name="current",
            display_name="电流",
            value=0.005,
            unit="A",
        )
        
        assert result.formatted_value == "5.00m A"
    
    def test_formatted_value_micro(self):
        """测试微级值格式化"""
        result = MetricResult(
            name="voltage",
            display_name="电压",
            value=0.000005,
            unit="V",
        )
        
        assert result.formatted_value == "5.00μ V"
    
    def test_formatted_value_nano(self):
        """测试纳级值格式化"""
        result = MetricResult(
            name="noise",
            display_name="噪声",
            value=5e-9,
            unit="V/√Hz",
        )
        
        assert result.formatted_value == "5.00n V/√Hz"
    
    def test_formatted_value_none(self):
        """测试空值格式化"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=None,
            unit="dB",
        )
        
        assert result.formatted_value == "N/A"
    
    def test_is_valid_true(self):
        """测试有效指标"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=20.0,
            unit="dB",
        )
        
        assert result.is_valid is True
    
    def test_is_valid_false_no_value(self):
        """测试无值时无效"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=None,
            unit="dB",
        )
        
        assert result.is_valid is False
    
    def test_is_valid_false_with_error(self):
        """测试有错误时无效"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=20.0,
            unit="dB",
            error_message="计算失败",
        )
        
        assert result.is_valid is False


class TestMetricResultSerialization:
    """测试序列化和反序列化"""
    
    def test_to_dict(self):
        """测试序列化为字典"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=20.5,
            unit="dB",
            target=20.0,
            target_type="min",
            category=MetricCategory.AMPLIFIER,
            confidence=0.95,
            measurement_condition="f=1kHz",
            metadata={"method": "interpolation"},
        )
        
        data = result.to_dict()
        
        assert data["name"] == "gain"
        assert data["display_name"] == "增益"
        assert data["value"] == 20.5
        assert data["unit"] == "dB"
        assert data["target"] == 20.0
        assert data["target_type"] == "min"
        assert data["category"] == "amplifier"
        assert data["confidence"] == 0.95
        assert data["measurement_condition"] == "f=1kHz"
        assert data["metadata"]["method"] == "interpolation"
        assert data["is_met"] is True
    
    def test_from_dict(self):
        """测试从字典反序列化"""
        data = {
            "name": "bandwidth",
            "display_name": "带宽",
            "value": 10e6,
            "unit": "Hz",
            "target": 5e6,
            "target_type": "min",
            "category": "amplifier",
            "confidence": 1.0,
            "measurement_condition": "Vdd=3.3V",
            "is_met": True,
        }
        
        result = MetricResult.from_dict(data)
        
        assert result.name == "bandwidth"
        assert result.display_name == "带宽"
        assert result.value == 10e6
        assert result.unit == "Hz"
        assert result.target == 5e6
        assert result.category == MetricCategory.AMPLIFIER
        assert result.is_met is True
    
    def test_roundtrip(self):
        """测试序列化往返"""
        original = MetricResult(
            name="phase_margin",
            display_name="相位裕度",
            value=65.0,
            unit="°",
            target=45.0,
            target_type="min",
            category=MetricCategory.AMPLIFIER,
            confidence=0.98,
            measurement_condition="unity gain",
            metadata={"frequency": 1e6},
        )
        
        data = original.to_dict()
        restored = MetricResult.from_dict(data)
        
        assert restored.name == original.name
        assert restored.display_name == original.display_name
        assert restored.value == original.value
        assert restored.unit == original.unit
        assert restored.target == original.target
        assert restored.target_type == original.target_type
        assert restored.category == original.category
        assert restored.confidence == original.confidence
        assert restored.measurement_condition == original.measurement_condition
        assert restored.is_met == original.is_met


class TestFactoryMethods:
    """测试工厂方法"""
    
    def test_create_metric_result(self):
        """测试创建成功的指标结果"""
        result = create_metric_result(
            name="gain",
            display_name="增益",
            value=20.0,
            unit="dB",
            category=MetricCategory.AMPLIFIER,
            target=15.0,
            measurement_condition="f=1kHz",
        )
        
        assert result.name == "gain"
        assert result.value == 20.0
        assert result.is_valid
        assert result.is_met is True
    
    def test_create_error_metric(self):
        """测试创建失败的指标结果"""
        result = create_error_metric(
            name="bandwidth",
            display_name="带宽",
            error_message="AC 分析数据不足",
            category=MetricCategory.AMPLIFIER,
        )
        
        assert result.name == "bandwidth"
        assert result.value is None
        assert result.is_valid is False
        assert result.error_message == "AC 分析数据不足"
        assert result.confidence == 0.0


class TestWithTarget:
    """测试 with_target 方法"""
    
    def test_with_target_creates_new_instance(self):
        """测试 with_target 创建新实例"""
        original = MetricResult(
            name="gain",
            display_name="增益",
            value=20.0,
            unit="dB",
        )
        
        with_target = original.with_target(15.0, "min")
        
        # 原对象不变
        assert original.target is None
        assert original.is_met is None
        
        # 新对象有目标
        assert with_target.target == 15.0
        assert with_target.target_type == "min"
        assert with_target.is_met is True
        assert with_target.value == original.value
    
    def test_with_target_range(self):
        """测试 with_target 范围目标"""
        original = MetricResult(
            name="bandwidth",
            display_name="带宽",
            value=15e6,
            unit="Hz",
        )
        
        with_target = original.with_target(10e6, "range", 20e6)
        
        assert with_target.target == 10e6
        assert with_target.target_max == 20e6
        assert with_target.is_met is True


class TestGetSummary:
    """测试摘要生成"""
    
    def test_summary_with_target_met(self):
        """测试达标时的摘要"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=25.0,
            unit="dB",
            target=20.0,
            target_type="min",
        )
        
        summary = result.get_summary()
        
        assert "增益" in summary
        assert "25.00 dB" in summary
        assert "✓" in summary
    
    def test_summary_without_target(self):
        """测试无目标时的摘要"""
        result = MetricResult(
            name="gain",
            display_name="增益",
            value=25.0,
            unit="dB",
        )
        
        summary = result.get_summary()
        
        assert "增益" in summary
        assert "25.00 dB" in summary
        assert "-" in summary
