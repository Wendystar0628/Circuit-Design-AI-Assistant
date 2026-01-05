# Design Management Domain
"""
设计管理域

包含：
- design_goals.py: 设计目标实体和管理器
- termination_checker.py: 终止条件判断
- undo_manager.py: 撤回快照管理（待实现）
"""

from domain.design.design_goals import (
    ConstraintType,
    DesignGoal,
    DesignGoalsCollection,
    DesignGoalsManager,
    SUPPORTED_METRICS,
    get_metric_info,
    get_supported_metric_identifiers,
)
from domain.design.termination_checker import (
    TerminationChecker,
    TerminationReason,
    TerminationResult,
    check_termination,
    should_continue,
)

__all__ = [
    # design_goals
    "ConstraintType",
    "DesignGoal",
    "DesignGoalsCollection",
    "DesignGoalsManager",
    "SUPPORTED_METRICS",
    "get_metric_info",
    "get_supported_metric_identifiers",
    # termination_checker
    "TerminationChecker",
    "TerminationReason",
    "TerminationResult",
    "check_termination",
    "should_continue",
]
