# Simulation Helpers Module
"""
仿真辅助模块

职责：
- 提供仿真收敛问题诊断和修复
- 提供仿真反馈生成

模块组成：
- convergence_helper.py - 收敛辅助工具
"""

from domain.simulation.helpers.convergence_helper import (
    ConvergenceHelper,
    convergence_helper,
)

__all__ = [
    "ConvergenceHelper",
    "convergence_helper",
]
