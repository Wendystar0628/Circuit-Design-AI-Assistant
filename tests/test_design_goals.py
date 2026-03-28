# test_design_goals.py - Design Goals Tests
"""
设计目标模块测试

测试内容：
- DesignGoal 数据类
- DesignGoalsCollection 数据类
- DesignGoalsManager 管理器
- 约束类型判断
- 评分计算
- 序列化/反序列化
- LLM 输出解析
"""

import json
import tempfile
from pathlib import Path

import pytest

from domain.design.design_goals import (
    ConstraintType,
    DesignGoal,
    DesignGoalsCollection,
    DesignGoalsManager,
    SUPPORTED_METRICS,
    get_metric_info,
    get_supported_metric_identifiers,
)


class TestConstraintType:
    """约束类型枚举测试"""
    
    def test_constraint_values(self):
        """测试约束类型值"""
        assert ConstraintType.MINIMUM.value == "minimum"
        assert ConstraintType.MAXIMUM.value == "maximum"
        assert ConstraintType.EXACT.value == "exact"
        assert ConstraintType.RANGE.value == "range"
        assert ConstraintType.MINIMIZE.value == "minimize"
        assert ConstraintType.MAXIMIZE.value == "maximize"
    
    def test_constraint_from_string(self):
        """测试从字符串创建约束类型"""
        assert ConstraintType("minimum") == ConstraintType.MINIMUM
        assert ConstraintType("maximum") == ConstraintType.MAXIMUM


class TestDesignGoal:
    """设计目标数据类测试"""
    
    def test_create_basic_goal(self):
        """测试创建基本目标"""
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            unit="dB"
        )
        assert goal.identifier == "gain"
        assert goal.name == "增益"
        assert goal.target_value == 20.0
        assert goal.unit == "dB"
        assert goal.constraint_type == ConstraintType.MINIMUM
        assert goal.weight == 1.0
    
    def test_is_satisfied_minimum(self):
        """测试最小值约束判断"""
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        )
        assert goal.is_satisfied(25.0) is True
        assert goal.is_satisfied(20.0) is True
        assert goal.is_satisfied(15.0) is False
    
    def test_is_satisfied_maximum(self):
        """测试最大值约束判断"""
        goal = DesignGoal(
            identifier="thd",
            name="总谐波失真",
            target_value=1.0,
            constraint_type=ConstraintType.MAXIMUM
        )
        assert goal.is_satisfied(0.5) is True
        assert goal.is_satisfied(1.0) is True
        assert goal.is_satisfied(1.5) is False
    
    def test_is_satisfied_exact(self):
        """测试精确值约束判断"""
        goal = DesignGoal(
            identifier="frequency",
            name="频率",
            target_value=1000.0,
            constraint_type=ConstraintType.EXACT,
            tolerance_percent=5.0
        )
        # 5% 容差 = 50 Hz
        assert goal.is_satisfied(1000.0) is True
        assert goal.is_satisfied(1040.0) is True
        assert goal.is_satisfied(960.0) is True
        assert goal.is_satisfied(1100.0) is False
        assert goal.is_satisfied(900.0) is False
    
    def test_is_satisfied_range(self):
        """测试范围约束判断"""
        goal = DesignGoal(
            identifier="duty_cycle",
            name="占空比",
            target_value=40.0,
            range_max=60.0,
            constraint_type=ConstraintType.RANGE
        )
        assert goal.is_satisfied(50.0) is True
        assert goal.is_satisfied(40.0) is True
        assert goal.is_satisfied(60.0) is True
        assert goal.is_satisfied(30.0) is False
        assert goal.is_satisfied(70.0) is False
    
    def test_is_satisfied_optimize(self):
        """测试优化约束（无硬性约束）"""
        goal_min = DesignGoal(
            identifier="power",
            name="功耗",
            target_value=1.0,
            constraint_type=ConstraintType.MINIMIZE
        )
        goal_max = DesignGoal(
            identifier="efficiency",
            name="效率",
            target_value=90.0,
            constraint_type=ConstraintType.MAXIMIZE
        )
        # 优化目标总是返回 True
        assert goal_min.is_satisfied(0.5) is True
        assert goal_min.is_satisfied(2.0) is True
        assert goal_max.is_satisfied(95.0) is True
        assert goal_max.is_satisfied(80.0) is True
    
    def test_calculate_score_minimum(self):
        """测试最小值约束评分"""
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        )
        assert goal.calculate_score(25.0) == 1.0
        assert goal.calculate_score(20.0) == 1.0
        assert goal.calculate_score(10.0) == 0.5
        assert goal.calculate_score(0.0) == 0.0
    
    def test_calculate_score_maximum(self):
        """测试最大值约束评分"""
        goal = DesignGoal(
            identifier="thd",
            name="总谐波失真",
            target_value=1.0,
            constraint_type=ConstraintType.MAXIMUM
        )
        assert goal.calculate_score(0.5) == 1.0
        assert goal.calculate_score(1.0) == 1.0
        assert goal.calculate_score(2.0) == 0.5
    
    def test_serialization(self):
        """测试序列化/反序列化"""
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            unit="dB",
            constraint_type=ConstraintType.MINIMUM,
            weight=0.8,
            tolerance_percent=3.0,
            description="放大器增益目标"
        )
        
        # 序列化
        data = goal.to_dict()
        assert data["identifier"] == "gain"
        assert data["target_value"] == 20.0
        assert data["constraint_type"] == "minimum"
        
        # 反序列化
        restored = DesignGoal.from_dict(data)
        assert restored.identifier == goal.identifier
        assert restored.target_value == goal.target_value
        assert restored.constraint_type == goal.constraint_type
        assert restored.weight == goal.weight


class TestDesignGoalsCollection:
    """设计目标集合测试"""
    
    def test_create_collection(self):
        """测试创建集合"""
        collection = DesignGoalsCollection(
            circuit_type="amplifier",
            description="运算放大器设计"
        )
        assert collection.circuit_type == "amplifier"
        assert collection.description == "运算放大器设计"
        assert len(collection.goals) == 0
        assert collection.created_at != ""
    
    def test_collection_serialization(self):
        """测试集合序列化"""
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0
        )
        collection = DesignGoalsCollection(
            goals=[goal],
            circuit_type="amplifier"
        )
        
        data = collection.to_dict()
        assert len(data["goals"]) == 1
        assert data["circuit_type"] == "amplifier"
        
        restored = DesignGoalsCollection.from_dict(data)
        assert len(restored.goals) == 1
        assert restored.goals[0].identifier == "gain"


class TestDesignGoalsManager:
    """设计目标管理器测试"""
    
    @pytest.fixture
    def temp_project(self):
        """创建临时项目目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".circuit_ai").mkdir()
            yield project_root
    
    def test_create_manager(self, temp_project):
        """测试创建管理器"""
        manager = DesignGoalsManager(temp_project)
        assert len(manager) == 0
    
    def test_add_goal(self, temp_project):
        """测试添加目标"""
        manager = DesignGoalsManager(temp_project)
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0
        )
        manager.add_goal(goal)
        assert len(manager) == 1
        assert manager.get_goal("gain") is not None
    
    def test_update_goal(self, temp_project):
        """测试更新目标"""
        manager = DesignGoalsManager(temp_project)
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0
        )
        manager.add_goal(goal)
        
        manager.update_goal("gain", {"target_value": 25.0})
        updated = manager.get_goal("gain")
        assert updated.target_value == 25.0
    
    def test_remove_goal(self, temp_project):
        """测试删除目标"""
        manager = DesignGoalsManager(temp_project)
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0
        )
        manager.add_goal(goal)
        assert len(manager) == 1
        
        manager.remove_goal("gain")
        assert len(manager) == 0
    
    def test_save_and_load(self, temp_project):
        """测试保存和加载"""
        manager = DesignGoalsManager(temp_project)
        goal = DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            unit="dB"
        )
        manager.add_goal(goal)
        manager.collection.circuit_type = "amplifier"
        manager.save()
        
        # 创建新管理器加载
        manager2 = DesignGoalsManager(temp_project)
        assert len(manager2) == 1
        assert manager2.get_goal("gain").target_value == 20.0
        assert manager2.collection.circuit_type == "amplifier"
    
    def test_validate(self, temp_project):
        """测试校验"""
        manager = DesignGoalsManager(temp_project)
        
        # 空集合应该通过
        errors = manager.validate()
        assert len(errors) == 0
        
        # 添加无效目标
        goal = DesignGoal(
            identifier="",  # 空标识符
            name="测试",
            target_value=10.0
        )
        manager.add_goal(goal)
        errors = manager.validate()
        assert len(errors) > 0
    
    def test_calculate_score(self, temp_project):
        """测试综合评分"""
        manager = DesignGoalsManager(temp_project)
        
        # 添加两个目标，权重各 0.5
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            weight=0.5,
            constraint_type=ConstraintType.MINIMUM
        ))
        manager.add_goal(DesignGoal(
            identifier="thd",
            name="THD",
            target_value=1.0,
            weight=0.5,
            constraint_type=ConstraintType.MAXIMUM
        ))
        
        # 两个都满足
        score = manager.calculate_score({"gain": 25.0, "thd": 0.5})
        assert score == 1.0
        
        # 一个满足一个不满足
        score = manager.calculate_score({"gain": 10.0, "thd": 0.5})
        assert 0.0 < score < 1.0
    
    def test_update_current_values(self, temp_project):
        """测试更新当前值"""
        manager = DesignGoalsManager(temp_project)
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        ))
        
        manager.update_current_values({"gain": 25.0})
        goal = manager.get_goal("gain")
        assert goal.current_value == 25.0
        assert goal.is_met is True
    
    def test_get_met_unmet_goals(self, temp_project):
        """测试获取达标/未达标目标"""
        manager = DesignGoalsManager(temp_project)
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        ))
        manager.add_goal(DesignGoal(
            identifier="thd",
            name="THD",
            target_value=1.0,
            constraint_type=ConstraintType.MAXIMUM
        ))
        
        manager.update_current_values({"gain": 25.0, "thd": 2.0})
        
        met = manager.get_met_goals()
        unmet = manager.get_unmet_goals()
        
        assert len(met) == 1
        assert met[0].identifier == "gain"
        assert len(unmet) == 1
        assert unmet[0].identifier == "thd"
    
    def test_from_llm_output(self, temp_project):
        """测试从 LLM 输出创建"""
        llm_json = {
            "circuit_type": "amplifier",
            "description": "设计一个增益20dB的放大器",
            "goals": [
                {
                    "name": "gain",
                    "display_name": "增益",
                    "value": 20,
                    "unit": "dB",
                    "type": "minimum"
                },
                {
                    "name": "bandwidth",
                    "display_name": "带宽",
                    "value": 1000000,
                    "unit": "Hz",
                    "type": "minimum"
                }
            ]
        }
        
        manager = DesignGoalsManager.from_llm_output(temp_project, llm_json)
        
        assert manager.collection.circuit_type == "amplifier"
        assert manager.collection.source == "llm"
        assert len(manager) == 2
        
        gain = manager.get_goal("gain")
        assert gain.name == "增益"
        assert gain.target_value == 20.0
        assert gain.constraint_type == ConstraintType.MINIMUM


class TestSupportedMetrics:
    """支持的指标测试"""
    
    def test_supported_metrics_exist(self):
        """测试支持的指标存在"""
        assert "gain" in SUPPORTED_METRICS
        assert "bandwidth" in SUPPORTED_METRICS
        assert "thd" in SUPPORTED_METRICS
    
    def test_get_metric_info(self):
        """测试获取指标信息"""
        info = get_metric_info("gain")
        assert info is not None
        assert info["name"] == "增益"
        assert info["unit"] == "dB"
        
        info = get_metric_info("nonexistent")
        assert info is None
    
    def test_get_supported_identifiers(self):
        """测试获取支持的标识符列表"""
        identifiers = get_supported_metric_identifiers()
        assert "gain" in identifiers
        assert "bandwidth" in identifiers
        assert len(identifiers) > 20  # 应该有很多指标
