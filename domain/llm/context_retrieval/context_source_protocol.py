# Context Source Protocol - Unified Interface for Context Collectors
"""
上下文源协议 - 定义所有上下文收集器的统一接口

职责：
- 定义 ContextSource 协议（Protocol 类）
- 定义 CollectionContext 数据类（收集上下文）
- 定义 ContextResult 数据类（收集结果）
- 定义 ContextPriority 优先级枚举

设计说明：
- 使用路径参数而非 GraphState 对象，保持领域层独立
- 调用方（context_retriever）负责从 GraphState 提取路径构建 CollectionContext
- 收集器只关心路径和文件内容，不感知 GraphState 的存在

被调用方：所有上下文收集器
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ============================================================
# 优先级枚举
# ============================================================

class ContextPriority(IntEnum):
    """
    上下文优先级枚举
    
    数值越小优先级越高，用于决定上下文在 Prompt 中的排列顺序。
    """
    CRITICAL = 0   # 关键信息（诊断错误、仿真失败）
    HIGH = 10      # 高优先级（当前电路文件、仿真结果）
    MEDIUM = 20    # 中等优先级（设计目标、依赖文件）
    LOW = 30       # 低优先级（搜索结果、历史记录）


# ============================================================
# 收集上下文数据类
# ============================================================

@dataclass
class CollectionContext:
    """
    收集上下文 - 传递给收集器的路径信息
    
    设计说明：
    - 只包含路径信息，不包含 GraphState 对象
    - 调用方负责从 GraphState 提取路径构建此对象
    - 收集器根据路径异步加载文件内容
    
    Attributes:
        project_path: 项目根目录（绝对路径）
        circuit_file_path: 当前电路文件相对路径（如 "amplifier.cir"）
        sim_result_path: 仿真结果文件相对路径（如 ".circuit_ai/sim_results/run_001.json"）
        design_goals_path: 设计目标文件相对路径（默认 ".circuit_ai/design_goals.json"）
        error_context: 错误上下文（轻量摘要字符串，已在 GraphState 中）
        active_editor_file: 当前编辑器打开的文件（绝对路径）
        last_metrics: 最新仿真指标摘要（用于计算目标达成进度）
    """
    project_path: str
    circuit_file_path: Optional[str] = None
    sim_result_path: Optional[str] = None
    design_goals_path: Optional[str] = ".circuit_ai/design_goals.json"
    error_context: Optional[str] = None
    active_editor_file: Optional[str] = None
    last_metrics: Dict[str, Any] = field(default_factory=dict)
    
    def get_absolute_path(self, relative_path: str) -> str:
        """将相对路径转换为绝对路径"""
        from pathlib import Path
        return str(Path(self.project_path) / relative_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "project_path": self.project_path,
            "circuit_file_path": self.circuit_file_path,
            "sim_result_path": self.sim_result_path,
            "design_goals_path": self.design_goals_path,
            "error_context": self.error_context,
            "active_editor_file": self.active_editor_file,
            "last_metrics": self.last_metrics,
        }


# ============================================================
# 收集结果数据类
# ============================================================

@dataclass
class ContextResult:
    """
    收集结果 - 收集器返回的上下文内容
    
    Attributes:
        content: 收集到的内容（格式化后的文本）
        token_count: 内容的 Token 数量
        source_name: 来源名称（用于日志和调试）
        priority: 优先级
        metadata: 额外元数据（如文件路径、时间戳等）
        is_empty: 是否为空结果
    """
    content: str
    token_count: int
    source_name: str
    priority: ContextPriority = ContextPriority.MEDIUM
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_empty(self) -> bool:
        """检查是否为空结果"""
        return not self.content or self.token_count == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "content": self.content,
            "token_count": self.token_count,
            "source_name": self.source_name,
            "priority": self.priority.value,
            "metadata": self.metadata,
            "is_empty": self.is_empty,
        }
    
    @classmethod
    def empty(cls, source_name: str) -> "ContextResult":
        """创建空结果"""
        return cls(
            content="",
            token_count=0,
            source_name=source_name,
            priority=ContextPriority.LOW,
        )


# ============================================================
# 上下文源协议
# ============================================================

@runtime_checkable
class ContextSource(Protocol):
    """
    上下文源协议 - 所有收集器必须实现的接口
    
    使用 Protocol 而非 ABC，支持结构化子类型（鸭子类型）。
    """
    
    async def collect_async(self, context: CollectionContext) -> ContextResult:
        """
        异步收集上下文
        
        Args:
            context: 收集上下文（包含路径信息）
            
        Returns:
            ContextResult: 收集结果
        """
        ...
    
    def get_priority(self) -> ContextPriority:
        """
        获取优先级
        
        Returns:
            ContextPriority: 优先级枚举值
        """
        ...
    
    def get_source_name(self) -> str:
        """
        获取源名称
        
        Returns:
            str: 源名称（用于日志和调试）
        """
        ...


# ============================================================
# 辅助函数
# ============================================================

def build_collection_context(
    project_path: str,
    state_context: Dict[str, Any],
) -> CollectionContext:
    """
    从状态上下文字典构建 CollectionContext
    
    调用方从 GraphState 提取路径信息，传入字典形式。
    此函数负责构建 CollectionContext 对象。
    
    Args:
        project_path: 项目根目录
        state_context: 状态上下文字典，包含：
            - circuit_file_path: 电路文件相对路径
            - sim_result_path: 仿真结果文件相对路径
            - design_goals_path: 设计目标文件相对路径
            - error_context: 错误上下文
            - last_metrics: 最新仿真指标
            
    Returns:
        CollectionContext: 收集上下文对象
    """
    return CollectionContext(
        project_path=project_path,
        circuit_file_path=state_context.get("circuit_file_path"),
        sim_result_path=state_context.get("sim_result_path"),
        design_goals_path=state_context.get(
            "design_goals_path", ".circuit_ai/design_goals.json"
        ),
        error_context=state_context.get("error_context"),
        active_editor_file=state_context.get("active_editor_file"),
        last_metrics=state_context.get("last_metrics", {}),
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ContextPriority",
    "CollectionContext",
    "ContextResult",
    "ContextSource",
    "build_collection_context",
]
