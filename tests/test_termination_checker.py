# test_termination_checker.py - Termination Checker Tests
"""
停止判断器测试

测试内容：
- TerminationReason 枚举
- TerminationResult 数据类
- TerminationChecker 类
- 各终止条件判断
- 便捷函数
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from domain.design.design_goals import (
    ConstraintType,
    DesignGoal,
    DesignGoalsManager,
)
from domain.design.termination_checker import (
    TerminationChecker,
    TerminationReason,
    TerminationResult,
    check_termination,
    should_continue,
)


class TestTerminationReason:
    """终止原因枚举测试"""
    
    def test_reason_values(self):
        """测试终止原因值"""
        assert TerminationReason.CONTINUE.value == "continue"
        assert TerminationReason.SUCCESS.value == "success"
        assert TerminationReason.MAX_CHECKPOINTS.value == "max_checkpoints"
        assert TerminationReason.STAGNATED.value == "stagnated"
        assert TerminationReason.USER_STOPPED.value == "user_stopped"
        assert TerminationReason.MAX_ITERATIONS.value == "max_iterations"
        assert TerminationReason.ERROR.value == "error"


class TestTerminationResult:
    """终止结果数据类测试"""
    
    def test_continue_iteration(self):
        """测试创建继续迭代结果"""
        result = TerminationResult.continue_iteration()
        assert result.should_terminate is False
        assert result.reason == TerminationReason.CONTINUE
        assert result.message == "继续迭代"
    
    def test_terminate(self):
        """测试创建终止结果"""
        result = TerminationResult.terminate(
            TerminationReason.SUCCESS,
            "所有目标已满足",
            details={"met_goals": ["gain", "bandwidth"]}
        )
        assert result.should_terminate is True
        assert result.reason == TerminationReason.SUCCESS
        assert result.message == "所有目标已满足"
        assert result.details == {"met_goals": ["gain", "bandwidth"]}
    
    def test_terminate_default_message(self):
        """测试终止结果默认消息"""
        result = TerminationResult.terminate(TerminationReason.STAGNATED)
        assert "stagnated" in result.message


class TestTerminationChecker:
    """停止判断器测试"""
    
    @pytest.fixture
    def checker(self):
        """创建默认配置的判断器"""
        return TerminationChecker(
            max_checkpoints=20,
            max_iterations=100,
            stagnation_window=3,
            stagnation_threshold=0.01
        )
    
    @pytest.fixture
    def temp_project(self):
        """创建临时项目目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".circuit_ai").mkdir()
            yield project_root
    
    def test_is_max_checkpoints_reached(self, checker):
        """测试最大检查点判断"""
        assert checker.is_max_checkpoints_reached(20, 20) is True
        assert checker.is_max_checkpoints_reached(21, 20) is True
        assert checker.is_max_checkpoints_reached(19, 20) is False
        assert checker.is_max_checkpoints_reached(0, 20) is False
    
    def test_is_max_iterations_reached(self, checker):
        """测试最大迭代次数判断"""
        assert checker.is_max_iterations_reached(100, 100) is True
        assert checker.is_max_iterations_reached(101, 100) is True
        assert checker.is_max_iterations_reached(99, 100) is False
    
    def test_is_goals_satisfied_all_met(self, checker, temp_project):
        """测试目标全部满足"""
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
        
        metrics = {"gain": 25.0, "thd": 0.5}
        assert checker.is_goals_satisfied(metrics, manager) is True
    
    def test_is_goals_satisfied_partial(self, checker, temp_project):
        """测试目标部分满足"""
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
        
        metrics = {"gain": 25.0, "thd": 2.0}  # THD 不满足
        assert checker.is_goals_satisfied(metrics, manager) is False
    
    def test_is_goals_satisfied_empty(self, checker, temp_project):
        """测试无目标时"""
        manager = DesignGoalsManager(temp_project)
        metrics = {"gain": 25.0}
        assert checker.is_goals_satisfied(metrics, manager) is False
    
    def test_is_goals_satisfied_with_string_values(self, checker, temp_project):
        """测试带单位的字符串值"""
        manager = DesignGoalsManager(temp_project)
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        ))
        
        metrics = {"gain": "25dB"}  # 带单位的字符串
        assert checker.is_goals_satisfied(metrics, manager) is True
    
    def test_check_termination_user_stopped(self, checker):
        """测试用户停止终止"""
        state = {"user_intent": "stop"}
        result = checker.check_termination(state)
        
        assert result.should_terminate is True
        assert result.reason == TerminationReason.USER_STOPPED
    
    def test_check_termination_goals_satisfied(self, checker, temp_project):
        """测试目标满足终止"""
        manager = DesignGoalsManager(temp_project)
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        ))
        
        state = {"last_metrics": {"gain": 25.0}}
        result = checker.check_termination(state, goals_manager=manager)
        
        assert result.should_terminate is True
        assert result.reason == TerminationReason.SUCCESS
    
    def test_check_termination_max_checkpoints(self, checker):
        """测试最大检查点终止"""
        state = {"checkpoint_count": 20}
        result = checker.check_termination(state)
        
        assert result.should_terminate is True
        assert result.reason == TerminationReason.MAX_CHECKPOINTS
    
    def test_check_termination_max_iterations(self, checker):
        """测试最大迭代次数终止"""
        state = {"iteration_count": 100}
        result = checker.check_termination(state)
        
        assert result.should_terminate is True
        assert result.reason == TerminationReason.MAX_ITERATIONS
    
    @patch("domain.design.termination_checker.check_stagnation")
    def test_check_termination_stagnated(self, mock_check_stagnation, checker):
        """测试停滞终止"""
        mock_check_stagnation.return_value = True
        mock_checkpointer = MagicMock()
        
        state = {"iteration_count": 10}
        result = checker.check_termination(
            state,
            checkpointer=mock_checkpointer,
            thread_id="test_thread"
        )
        
        assert result.should_terminate is True
        assert result.reason == TerminationReason.STAGNATED
        mock_check_stagnation.assert_called_once()
    
    def test_check_termination_continue(self, checker, temp_project):
        """测试继续迭代"""
        manager = DesignGoalsManager(temp_project)
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        ))
        
        state = {
            "checkpoint_count": 5,
            "iteration_count": 10,
            "last_metrics": {"gain": 15.0}  # 未达标
        }
        result = checker.check_termination(state, goals_manager=manager)
        
        assert result.should_terminate is False
        assert result.reason == TerminationReason.CONTINUE
    
    def test_check_termination_priority(self, checker, temp_project):
        """测试终止条件优先级：用户停止 > 目标满足"""
        manager = DesignGoalsManager(temp_project)
        manager.add_goal(DesignGoal(
            identifier="gain",
            name="增益",
            target_value=20.0,
            constraint_type=ConstraintType.MINIMUM
        ))
        
        # 同时满足用户停止和目标满足
        state = {
            "user_intent": "stop",
            "last_metrics": {"gain": 25.0}
        }
        result = checker.check_termination(state, goals_manager=manager)
        
        # 用户停止优先
        assert result.reason == TerminationReason.USER_STOPPED
    
    def test_extract_numeric_values(self, checker):
        """测试数值提取"""
        metrics = {
            "gain": 20.0,
            "bandwidth": "10MHz",
            "phase_margin": "45°",
            "invalid": "abc",
            "negative": "-3.5dB"
        }
        
        result = checker._extract_numeric_values(metrics)
        
        assert result["gain"] == 20.0
        assert result["bandwidth"] == 10.0
        assert result["phase_margin"] == 45.0
        assert "invalid" not in result
        assert result["negative"] == -3.5
    
    def test_custom_limits(self):
        """测试自定义限制"""
        checker = TerminationChecker(
            max_checkpoints=5,
            max_iterations=10
        )
        
        state = {"checkpoint_count": 5}
        result = checker.check_termination(state)
        assert result.reason == TerminationReason.MAX_CHECKPOINTS
        
        state = {"checkpoint_count": 3, "iteration_count": 10}
        result = checker.check_termination(state)
        assert result.reason == TerminationReason.MAX_ITERATIONS


class TestConvenienceFunctions:
    """便捷函数测试"""
    
    def test_check_termination_function(self):
        """测试 check_termination 便捷函数"""
        state = {"checkpoint_count": 20}
        result = check_termination(state, max_checkpoints=20)
        
        assert result.should_terminate is True
        assert result.reason == TerminationReason.MAX_CHECKPOINTS
    
    def test_should_continue_function(self):
        """测试 should_continue 便捷函数"""
        state = {"checkpoint_count": 5, "iteration_count": 10}
        assert should_continue(state, max_checkpoints=20) is True
        
        state = {"checkpoint_count": 20}
        assert should_continue(state, max_checkpoints=20) is False
    
    def test_should_continue_with_goals(self):
        """测试 should_continue 与目标管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".circuit_ai").mkdir()
            
            manager = DesignGoalsManager(project_root)
            manager.add_goal(DesignGoal(
                identifier="gain",
                name="增益",
                target_value=20.0,
                constraint_type=ConstraintType.MINIMUM
            ))
            
            # 未达标，应继续
            state = {"last_metrics": {"gain": 15.0}}
            assert should_continue(state, goals_manager=manager) is True
            
            # 达标，应终止
            state = {"last_metrics": {"gain": 25.0}}
            assert should_continue(state, goals_manager=manager) is False


class TestStateExtraction:
    """状态提取测试"""
    
    def test_extract_from_dict(self):
        """测试从字典提取状态"""
        checker = TerminationChecker()
        state = {
            "checkpoint_count": 10,
            "iteration_count": 20,
            "last_metrics": {"gain": 15.0}
        }
        
        result = checker._extract_state_dict(state)
        assert result["checkpoint_count"] == 10
        assert result["iteration_count"] == 20
    
    def test_extract_from_object_with_to_dict(self):
        """测试从带 to_dict 方法的对象提取状态"""
        checker = TerminationChecker()
        
        class MockState:
            def to_dict(self):
                return {"checkpoint_count": 5}
        
        result = checker._extract_state_dict(MockState())
        assert result["checkpoint_count"] == 5
    
    def test_extract_from_object_with_attributes(self):
        """测试从带属性的对象提取状态"""
        checker = TerminationChecker()
        
        class MockState:
            checkpoint_count = 15
            iteration_count = 30
        
        result = checker._extract_state_dict(MockState())
        assert result["checkpoint_count"] == 15
        assert result["iteration_count"] == 30
