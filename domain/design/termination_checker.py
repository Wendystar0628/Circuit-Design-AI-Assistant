# TerminationChecker - Design Iteration Termination Checker
"""
停止判断器

职责：
- 决定设计迭代循环是否应该终止
- 综合判断多种终止条件
- 返回终止原因或继续信号

终止条件（任一满足即终止）：
1. 所有必需指标满足目标 → "success"
2. 达到最大检查点次数（默认20次）→ "max_checkpoints"
3. 连续N次无性能提升 → "stagnated"
4. 用户手动停止 → "user_stopped"

被调用方：
- edges.py（条件边 should_continue）

使用示例：
    from domain.design.termination_checker import TerminationChecker
    
    checker = TerminationChecker()
    result = checker.check_termination(
        state=graph_state,
        goals_manager=goals_manager,
        checkpointer=checkpointer,
        thread_id="session_123"
    )
    
    if result.should_terminate:
        print(f"终止原因: {result.reason.value}")
    else:
        print("继续迭代")
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union

from domain.design.design_goals import DesignGoalsManager
from domain.services.iteration_history_service import check_stagnation


class TerminationReason(Enum):
    """
    终止原因枚举
    
    定义设计迭代可能的终止原因
    """
    
    CONTINUE = "continue"
    """继续迭代（未终止）"""
    
    SUCCESS = "success"
    """所有必需指标满足目标"""
    
    MAX_CHECKPOINTS = "max_checkpoints"
    """达到最大检查点次数"""
    
    STAGNATED = "stagnated"
    """连续多次无性能提升"""
    
    USER_STOPPED = "user_stopped"
    """用户手动停止"""
    
    MAX_ITERATIONS = "max_iterations"
    """达到最大迭代次数"""
    
    ERROR = "error"
    """错误终止"""


@dataclass
class TerminationResult:
    """
    终止判断结果
    
    Attributes:
        should_terminate: 是否应该终止
        reason: 终止原因
        message: 详细消息
        details: 附加详情
    """
    
    should_terminate: bool
    """是否应该终止"""
    
    reason: TerminationReason
    """终止原因"""
    
    message: str = ""
    """详细消息（用于日志和 UI 显示）"""
    
    details: Optional[Dict[str, Any]] = None
    """附加详情"""
    
    @classmethod
    def continue_iteration(cls) -> "TerminationResult":
        """创建继续迭代的结果"""
        return cls(
            should_terminate=False,
            reason=TerminationReason.CONTINUE,
            message="继续迭代"
        )
    
    @classmethod
    def terminate(
        cls,
        reason: TerminationReason,
        message: str = "",
        details: Optional[Dict[str, Any]] = None
    ) -> "TerminationResult":
        """创建终止结果"""
        return cls(
            should_terminate=True,
            reason=reason,
            message=message or f"终止原因: {reason.value}",
            details=details
        )


class TerminationChecker:
    """
    停止判断器
    
    综合判断设计迭代是否应该终止
    
    Attributes:
        max_checkpoints: 最大检查点次数（默认 20）
        max_iterations: 最大迭代次数（默认 100）
        stagnation_window: 停滞检测窗口大小（默认 3）
        stagnation_threshold: 停滞检测阈值（默认 0.01，即 1%）
        stagnation_metric_key: 用于停滞检测的指标键名（默认 "score"）
    """
    
    def __init__(
        self,
        max_checkpoints: int = 20,
        max_iterations: int = 100,
        stagnation_window: int = 3,
        stagnation_threshold: float = 0.01,
        stagnation_metric_key: str = "score"
    ):
        """
        初始化停止判断器
        
        Args:
            max_checkpoints: 最大检查点次数
            max_iterations: 最大迭代次数
            stagnation_window: 停滞检测窗口大小
            stagnation_threshold: 停滞检测阈值
            stagnation_metric_key: 用于停滞检测的指标键名
        """
        self.max_checkpoints = max_checkpoints
        self.max_iterations = max_iterations
        self.stagnation_window = stagnation_window
        self.stagnation_threshold = stagnation_threshold
        self.stagnation_metric_key = stagnation_metric_key
    
    def check_termination(
        self,
        state: Any,
        goals_manager: Optional[DesignGoalsManager] = None,
        checkpointer: Optional[Any] = None,
        thread_id: str = ""
    ) -> TerminationResult:
        """
        综合判断是否应该终止
        
        按优先级检查各终止条件：
        1. 用户停止
        2. 目标满足
        3. 最大检查点
        4. 最大迭代次数
        5. 停滞检测
        
        Args:
            state: GraphState 实例或字典
            goals_manager: 设计目标管理器（可选）
            checkpointer: LangGraph Checkpointer（可选，用于停滞检测）
            thread_id: 线程 ID（用于停滞检测）
            
        Returns:
            TerminationResult: 终止判断结果
        """
        # 提取状态字段
        state_dict = self._extract_state_dict(state)
        
        # 1. 检查用户停止
        if self._is_user_stopped(state_dict):
            return TerminationResult.terminate(
                TerminationReason.USER_STOPPED,
                "用户手动停止迭代"
            )
        
        # 2. 检查目标是否满足
        if goals_manager is not None:
            metrics = state_dict.get("last_metrics", {})
            if self.is_goals_satisfied(metrics, goals_manager):
                met_goals = [g.identifier for g in goals_manager.get_met_goals()]
                return TerminationResult.terminate(
                    TerminationReason.SUCCESS,
                    "所有设计目标已满足",
                    details={"met_goals": met_goals}
                )
        
        # 3. 检查最大检查点次数
        checkpoint_count = state_dict.get("checkpoint_count", 0)
        if self.is_max_checkpoints_reached(checkpoint_count, self.max_checkpoints):
            return TerminationResult.terminate(
                TerminationReason.MAX_CHECKPOINTS,
                f"达到最大检查点次数 ({self.max_checkpoints})",
                details={"checkpoint_count": checkpoint_count}
            )
        
        # 4. 检查最大迭代次数
        iteration_count = state_dict.get("iteration_count", 0)
        if self.is_max_iterations_reached(iteration_count, self.max_iterations):
            return TerminationResult.terminate(
                TerminationReason.MAX_ITERATIONS,
                f"达到最大迭代次数 ({self.max_iterations})",
                details={"iteration_count": iteration_count}
            )
        
        # 5. 检查停滞（需要 checkpointer）
        if checkpointer is not None and thread_id:
            if self.is_stagnated(checkpointer, thread_id):
                stagnation_count = state_dict.get("stagnation_count", 0)
                return TerminationResult.terminate(
                    TerminationReason.STAGNATED,
                    f"优化停滞，连续 {self.stagnation_window} 次无显著改善",
                    details={"stagnation_count": stagnation_count}
                )
        
        # 未满足任何终止条件，继续迭代
        return TerminationResult.continue_iteration()
    
    def is_goals_satisfied(
        self,
        metrics: Dict[str, Any],
        goals_manager: DesignGoalsManager
    ) -> bool:
        """
        检查所有必需指标是否达标
        
        Args:
            metrics: 当前仿真指标字典
            goals_manager: 设计目标管理器
            
        Returns:
            bool: 是否所有目标都满足
        """
        if not goals_manager.collection.goals:
            return False  # 无目标时不视为满足
        
        # 提取数值
        actual_values = self._extract_numeric_values(metrics)
        
        # 更新目标的当前值
        goals_manager.update_current_values(actual_values)
        
        # 检查是否全部达标
        return goals_manager.all_goals_met()
    
    def is_max_checkpoints_reached(self, count: int, limit: int) -> bool:
        """
        检查是否达到最大检查点次数
        
        Args:
            count: 当前检查点计数
            limit: 最大检查点次数
            
        Returns:
            bool: 是否达到限制
        """
        return count >= limit
    
    def is_max_iterations_reached(self, count: int, limit: int) -> bool:
        """
        检查是否达到最大迭代次数
        
        Args:
            count: 当前迭代计数
            limit: 最大迭代次数
            
        Returns:
            bool: 是否达到限制
        """
        return count >= limit
    
    def is_stagnated(
        self,
        checkpointer: Any,
        thread_id: str,
        metric_key: Optional[str] = None
    ) -> bool:
        """
        检查是否连续N次无性能提升
        
        通过 iteration_history_service.check_stagnation() 实现
        
        Args:
            checkpointer: LangGraph Checkpointer 实例
            thread_id: 线程 ID
            metric_key: 用于判断的指标键名（默认使用实例配置）
            
        Returns:
            bool: 是否停滞
        """
        key = metric_key or self.stagnation_metric_key
        
        return check_stagnation(
            checkpointer=checkpointer,
            thread_id=thread_id,
            metric_key=key,
            window_size=self.stagnation_window,
            threshold=self.stagnation_threshold
        )
    
    def _is_user_stopped(self, state_dict: Dict[str, Any]) -> bool:
        """检查用户是否手动停止"""
        # 检查 user_intent 是否为 stop
        if state_dict.get("user_intent") == "stop":
            return True
        
        # 检查 termination_reason 是否已设置为 user_stopped
        if state_dict.get("termination_reason") == "user_stopped":
            return True
        
        return False
    
    def _extract_state_dict(self, state: Any) -> Dict[str, Any]:
        """从状态对象提取字典"""
        if isinstance(state, dict):
            return state
        
        if hasattr(state, "to_dict"):
            return state.to_dict()
        
        # 尝试直接访问属性
        result = {}
        for attr in [
            "checkpoint_count", "iteration_count", "stagnation_count",
            "last_metrics", "user_intent", "termination_reason",
            "is_completed"
        ]:
            if hasattr(state, attr):
                result[attr] = getattr(state, attr)
        
        return result
    
    def _extract_numeric_values(
        self,
        metrics: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        从指标字典提取数值
        
        处理带单位的字符串（如 "20dB"、"10MHz"）
        
        Args:
            metrics: 指标字典
            
        Returns:
            Dict[str, float]: 数值字典
        """
        result = {}
        
        for key, value in metrics.items():
            try:
                if isinstance(value, (int, float)):
                    result[key] = float(value)
                elif isinstance(value, str):
                    # 尝试提取数值部分
                    numeric_str = "".join(
                        c for c in value if c.isdigit() or c in ".-"
                    )
                    if numeric_str:
                        result[key] = float(numeric_str)
            except (ValueError, TypeError):
                pass
        
        return result


# ============================================================
# 便捷函数
# ============================================================

def check_termination(
    state: Any,
    goals_manager: Optional[DesignGoalsManager] = None,
    checkpointer: Optional[Any] = None,
    thread_id: str = "",
    **kwargs
) -> TerminationResult:
    """
    便捷函数：检查是否应该终止
    
    Args:
        state: GraphState 实例或字典
        goals_manager: 设计目标管理器
        checkpointer: LangGraph Checkpointer
        thread_id: 线程 ID
        **kwargs: 传递给 TerminationChecker 的参数
        
    Returns:
        TerminationResult: 终止判断结果
    """
    checker = TerminationChecker(**kwargs)
    return checker.check_termination(
        state=state,
        goals_manager=goals_manager,
        checkpointer=checkpointer,
        thread_id=thread_id
    )


def should_continue(
    state: Any,
    goals_manager: Optional[DesignGoalsManager] = None,
    checkpointer: Optional[Any] = None,
    thread_id: str = "",
    **kwargs
) -> bool:
    """
    便捷函数：判断是否应该继续迭代
    
    用于条件边判断
    
    Args:
        state: GraphState 实例或字典
        goals_manager: 设计目标管理器
        checkpointer: LangGraph Checkpointer
        thread_id: 线程 ID
        **kwargs: 传递给 TerminationChecker 的参数
        
    Returns:
        bool: 是否应该继续
    """
    result = check_termination(
        state=state,
        goals_manager=goals_manager,
        checkpointer=checkpointer,
        thread_id=thread_id,
        **kwargs
    )
    return not result.should_terminate


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "TerminationReason",
    "TerminationResult",
    "TerminationChecker",
    "check_termination",
    "should_continue",
]
