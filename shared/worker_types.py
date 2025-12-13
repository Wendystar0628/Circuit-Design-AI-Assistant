# Worker Type Constants
"""
Worker 类型常量定义

职责：
- 集中定义所有 Worker 类型常量
- 定义 Worker 状态枚举
- 定义任务优先级枚举

设计原则：
- 纯常量和枚举定义，不依赖任何其他模块
- 所有 Worker 类型使用 WORKER_ 前缀
"""

from enum import Enum, auto


# ============================================================
# Worker 类型常量
# ============================================================

WORKER_LLM = "llm_worker"
WORKER_SIMULATION = "simulation_worker"
WORKER_RAG = "rag_worker"
WORKER_FILE_WATCHER = "file_watcher_worker"


# ============================================================
# Worker 状态枚举
# ============================================================

class WorkerStatus(Enum):
    """Worker 运行状态"""
    
    # 空闲，可接受任务
    IDLE = auto()
    
    # 正在执行任务
    RUNNING = auto()
    
    # 已停止
    STOPPED = auto()
    
    # 错误状态
    ERROR = auto()


# ============================================================
# 任务优先级枚举
# ============================================================

class TaskPriority(Enum):
    """任务优先级"""
    
    # 低优先级（自动触发的后台任务）
    LOW = 0
    
    # 普通优先级（默认）
    NORMAL = 1
    
    # 高优先级（用户触发的任务）
    HIGH = 2


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # Worker 类型常量
    "WORKER_LLM",
    "WORKER_SIMULATION",
    "WORKER_RAG",
    "WORKER_FILE_WATCHER",
    # 枚举
    "WorkerStatus",
    "TaskPriority",
]
