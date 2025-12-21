# GraphState - LangGraph Workflow State Definition
"""
GraphState 定义 - LangGraph 工作流的状态结构

核心架构原则：Reference-Based Single Source of Truth
- GraphState 是目录：仅存储文件路径（指针）和轻量摘要，不存储重数据
- 文件系统是仓库：仿真结果、设计目标、对话历史等业务数据存储在文件中
- 领域服务是搬运工：无状态的纯函数式服务，输入 → 处理 → 输出到文件 → 返回路径
- LangGraph 管理版本：通过 SqliteSaver 持久化 GraphState，回滚时指针自动回退

数据分类原则：
- 存入 GraphState：流转控制、文件指针、轻量摘要、计数器
- 存入文件系统：仿真波形数据、设计目标详情、完整对话历史、电路文件
- 视图投影：迭代历史（从 SqliteSaver 检查点历史查询）
- 不存储：RAG 检索结果（按需获取）

状态修改规范：
- 图节点通过返回字典修改 GraphState
- 返回值只包含需要更新的字段
- 禁止直接修改传入的 state 参数
- 禁止在 GraphState 中存储大型数据
"""

from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Literal, Optional

from langgraph.graph.message import add_messages

# 尝试导入 LangChain 消息类型
try:
    from langchain_core.messages import AnyMessage
except ImportError:
    # 如果未安装 langchain，使用 Any 类型
    AnyMessage = Any


# ============================================================
# 工作模式枚举
# ============================================================

WorkMode = Literal["workflow", "free_chat"]
"""
工作模式：
- workflow: 工作流模式，执行设计优化迭代
- free_chat: 自由对话模式，纯对话不执行工作流
"""


# ============================================================
# GraphState 定义
# ============================================================

@dataclass
class GraphState:
    """
    LangGraph 工作流状态
    
    核心原则：存储指针和摘要，不存储重数据
    
    Attributes:
        # 会话与模式控制
        session_id: 会话标识，格式 YYYYMMDD_HHMMSS
        work_mode: 工作模式（workflow | free_chat）
        project_root: 项目根目录路径
        
        # 流转控制
        current_node: 当前执行的节点名称
        previous_node: 上一个执行的节点名称
        user_input: 用户最新输入消息
        user_intent: 用户意图类型
        is_completed: 是否完成
        termination_reason: 终止原因
        
        # 文件指针（核心：存路径不存内容）
        circuit_file_path: 主电路文件相对路径
        sim_result_path: 最新仿真结果文件相对路径
        design_goals_path: 设计目标文件相对路径
        
        # 轻量摘要（用于条件边判断和 UI 显示）
        design_goals_summary: 设计目标摘要
        last_metrics: 最新仿真指标摘要
        error_context: 错误上下文
        
        # 计数器
        iteration_count: 迭代次数
        checkpoint_count: 检查点计数
        stagnation_count: 停滞计数（连续未改善次数）
        
        # 消息聚合（LangGraph 内部使用）
        messages: 消息序列
    """
    
    # ============================================================
    # 会话与模式控制
    # ============================================================
    
    session_id: str = ""
    """会话标识，格式 YYYYMMDD_HHMMSS"""
    
    work_mode: WorkMode = "free_chat"
    """工作模式：workflow（工作流）| free_chat（自由对话）"""
    
    project_root: str = ""
    """项目根目录路径"""
    
    # ============================================================
    # 流转控制
    # ============================================================
    
    current_node: str = ""
    """当前执行的节点名称"""
    
    previous_node: str = ""
    """上一个执行的节点名称"""
    
    user_input: str = ""
    """用户最新输入消息"""
    
    user_intent: str = ""
    """
    用户意图类型：
    - design_request: 设计请求
    - simulation_request: 仿真请求
    - modification_request: 修改请求
    - question: 问题咨询
    - confirmation: 确认
    - rejection: 拒绝
    - stop: 停止
    - other: 其他
    """
    
    is_completed: bool = False
    """是否完成"""
    
    termination_reason: str = ""
    """
    终止原因：
    - user_accepted: 用户接受设计
    - goals_satisfied: 设计目标满足
    - max_iterations: 达到最大迭代次数
    - max_checkpoints: 达到最大检查点次数
    - stagnated: 优化停滞
    - user_stopped: 用户停止
    - error: 错误终止
    """
    
    # ============================================================
    # 文件指针（核心：存路径不存内容）
    # ============================================================
    
    circuit_file_path: str = ""
    """主电路文件相对路径（如 amplifier.cir）"""
    
    sim_result_path: str = ""
    """最新仿真结果文件相对路径（如 .circuit_ai/sim_results/run_001.json）"""
    
    design_goals_path: str = ".circuit_ai/design_goals.json"
    """设计目标文件相对路径"""
    
    # ============================================================
    # 轻量摘要（用于条件边判断和 UI 显示）
    # ============================================================
    
    design_goals_summary: Dict[str, Any] = field(default_factory=dict)
    """
    设计目标摘要，用于条件边判断
    示例：{
        "gain": {"target": "20dB", "tolerance": "±2dB"},
        "bandwidth": {"target": "10MHz", "tolerance": "±1MHz"}
    }
    """
    
    last_metrics: Dict[str, Any] = field(default_factory=dict)
    """
    最新仿真指标摘要，用于 UI 显示和条件边判断
    示例：{
        "gain": "18.5dB",
        "bandwidth": "9.2MHz",
        "phase_margin": "45°"
    }
    """
    
    error_context: str = ""
    """错误上下文（仿真失败时的错误信息）"""
    
    # ============================================================
    # 计数器
    # ============================================================
    
    iteration_count: int = 0
    """迭代次数"""
    
    checkpoint_count: int = 0
    """检查点计数（用户确认次数）"""
    
    stagnation_count: int = 0
    """停滞计数（连续未改善次数）"""
    
    consecutive_fix_attempts: int = 0
    """连续修复尝试次数（用于错误修复熔断机制）"""
    
    # ============================================================
    # 追踪上下文（支持 interrupt/resume 链路连续性）
    # ============================================================
    
    _trace_id: str = ""
    """追踪链路 ID（跨 interrupt/resume 保持）"""
    
    _last_span_id: str = ""
    """最后一个 Span ID（用于 resume 后恢复父子关系）"""
    
    # ============================================================
    # 消息聚合（LangGraph 内部使用）
    # ============================================================
    
    messages: Annotated[List[AnyMessage], add_messages] = field(default_factory=list)
    """
    消息序列，使用 LangGraph 的 add_messages reducer
    自动处理消息追加和去重
    """
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            # 会话与模式控制
            "session_id": self.session_id,
            "work_mode": self.work_mode,
            "project_root": self.project_root,
            # 流转控制
            "current_node": self.current_node,
            "previous_node": self.previous_node,
            "user_input": self.user_input,
            "user_intent": self.user_intent,
            "is_completed": self.is_completed,
            "termination_reason": self.termination_reason,
            # 文件指针
            "circuit_file_path": self.circuit_file_path,
            "sim_result_path": self.sim_result_path,
            "design_goals_path": self.design_goals_path,
            # 轻量摘要
            "design_goals_summary": self.design_goals_summary,
            "last_metrics": self.last_metrics,
            "error_context": self.error_context,
            # 计数器
            "iteration_count": self.iteration_count,
            "checkpoint_count": self.checkpoint_count,
            "stagnation_count": self.stagnation_count,
            "consecutive_fix_attempts": self.consecutive_fix_attempts,
            # 追踪上下文
            "_trace_id": self._trace_id,
            "_last_span_id": self._last_span_id,
            # 消息数量（不序列化完整消息）
            "message_count": len(self.messages) if self.messages else 0,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphState":
        """从字典创建（用于反序列化）"""
        return cls(
            session_id=data.get("session_id", ""),
            work_mode=data.get("work_mode", "free_chat"),
            project_root=data.get("project_root", ""),
            current_node=data.get("current_node", ""),
            previous_node=data.get("previous_node", ""),
            user_input=data.get("user_input", ""),
            user_intent=data.get("user_intent", ""),
            is_completed=data.get("is_completed", False),
            termination_reason=data.get("termination_reason", ""),
            circuit_file_path=data.get("circuit_file_path", ""),
            sim_result_path=data.get("sim_result_path", ""),
            design_goals_path=data.get("design_goals_path", ".circuit_ai/design_goals.json"),
            design_goals_summary=data.get("design_goals_summary", {}),
            last_metrics=data.get("last_metrics", {}),
            error_context=data.get("error_context", ""),
            iteration_count=data.get("iteration_count", 0),
            checkpoint_count=data.get("checkpoint_count", 0),
            stagnation_count=data.get("stagnation_count", 0),
            consecutive_fix_attempts=data.get("consecutive_fix_attempts", 0),
            _trace_id=data.get("_trace_id", ""),
            _last_span_id=data.get("_last_span_id", ""),
            messages=data.get("messages", []),
        )
    
    def get_status_summary(self) -> str:
        """获取状态摘要（用于日志和调试）"""
        return (
            f"GraphState(session={self.session_id}, mode={self.work_mode}, "
            f"node={self.current_node}, iter={self.iteration_count}, "
            f"completed={self.is_completed})"
        )


# ============================================================
# 状态更新辅助函数
# ============================================================

def create_initial_state(
    session_id: str,
    project_root: str,
    work_mode: WorkMode = "free_chat"
) -> GraphState:
    """
    创建初始状态
    
    Args:
        session_id: 会话标识
        project_root: 项目根目录
        work_mode: 工作模式
        
    Returns:
        GraphState: 初始状态
    """
    return GraphState(
        session_id=session_id,
        project_root=project_root,
        work_mode=work_mode,
        current_node="start",
        design_goals_path=".circuit_ai/design_goals.json",
    )


def merge_state_update(
    current: Dict[str, Any],
    update: Dict[str, Any]
) -> Dict[str, Any]:
    """
    合并状态更新（用于图节点返回值处理）
    
    Args:
        current: 当前状态字典
        update: 更新字典
        
    Returns:
        Dict: 合并后的状态字典
    """
    result = current.copy()
    result.update(update)
    return result


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "GraphState",
    "WorkMode",
    "create_initial_state",
    "merge_state_update",
]
