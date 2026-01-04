# Analysis Types - Simulation Analysis Type Definitions
"""
仿真分析类型定义

职责：
- 定义支持的仿真分析类型枚举
- 提供分析类型的元数据（默认参数、描述等）
"""

from enum import Enum
from typing import Any, Dict


class AnalysisType(Enum):
    """仿真分析类型枚举"""
    
    OP = "op"
    """直流工作点分析"""
    
    DC = "dc"
    """直流扫描分析"""
    
    AC = "ac"
    """交流小信号分析"""
    
    TRAN = "tran"
    """瞬态分析"""
    
    NOISE = "noise"
    """噪声分析"""
    
    TF = "tf"
    """传递函数分析"""
    
    SENS = "sens"
    """灵敏度分析"""


# 分析类型默认参数
ANALYSIS_DEFAULTS: Dict[AnalysisType, Dict[str, Any]] = {
    AnalysisType.OP: {},
    AnalysisType.DC: {
        "source": "Vin",
        "start": 0,
        "stop": 5,
        "step": 0.1,
    },
    AnalysisType.AC: {
        "variation": "dec",  # dec | oct | lin
        "points": 10,
        "start_frequency": 1,      # Hz
        "stop_frequency": 1e9,     # Hz
    },
    AnalysisType.TRAN: {
        "step_time": 1e-6,         # 步长 (s)
        "end_time": 1e-3,          # 结束时间 (s)
        "start_time": 0,           # 开始时间 (s)
        "max_step": None,          # 最大步长
    },
    AnalysisType.NOISE: {
        "output": "out",
        "input_source": "Vin",
        "variation": "dec",
        "points": 10,
        "start_frequency": 1,
        "stop_frequency": 1e9,
    },
    AnalysisType.TF: {
        "output": "V(out)",
        "input_source": "Vin",
    },
    AnalysisType.SENS: {
        "output": "V(out)",
    },
}


def get_analysis_defaults(analysis_type: AnalysisType) -> Dict[str, Any]:
    """获取分析类型的默认参数"""
    return ANALYSIS_DEFAULTS.get(analysis_type, {}).copy()


__all__ = [
    "AnalysisType",
    "ANALYSIS_DEFAULTS",
    "get_analysis_defaults",
]
