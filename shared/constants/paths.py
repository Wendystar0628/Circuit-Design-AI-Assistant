# Path Constants - 统一路径常量定义
"""
统一路径常量

所有系统生成的数据统一存储在 .circuit_ai/ 目录下。
本模块定义所有路径常量，确保路径一致性。

使用示例：
    from shared.constants.paths import SIM_RESULTS_DIR, SYSTEM_DIR
    
    # 构建仿真结果完整路径
    result_path = Path(project_root) / SIM_RESULTS_DIR / f"{uuid}.json"
"""

# ============================================================
# 系统目录
# ============================================================

# 系统隐藏目录名（相对于项目根目录）
SYSTEM_DIR = ".circuit_ai"

# ============================================================
# 仿真相关路径
# ============================================================

# 仿真结果目录（相对于项目根目录）
SIM_RESULTS_DIR = f"{SYSTEM_DIR}/sim_results"

# 仿真配置文件（相对于项目根目录）
SIM_CONFIG_FILE = f"{SYSTEM_DIR}/simulation_config.json"

# 分析选择配置文件（相对于项目根目录）
ANALYSIS_SELECTION_FILE = f"{SYSTEM_DIR}/analysis_selection.json"

# 图表选择配置文件（相对于项目根目录）
CHART_SELECTION_FILE = f"{SYSTEM_DIR}/chart_selection.json"

# ============================================================
# 设计相关路径
# ============================================================

# 设计目标文件（相对于项目根目录）
DESIGN_GOALS_FILE = f"{SYSTEM_DIR}/design_goals.json"

# 迭代历史文件（相对于项目根目录）
ITERATION_HISTORY_FILE = f"{SYSTEM_DIR}/iteration_history.json"

# ============================================================
# 快照相关路径
# ============================================================

# 撤回快照目录（相对于项目根目录）
UNDO_SNAPSHOTS_DIR = f"{SYSTEM_DIR}/undo_snapshots"

# 全量快照目录（相对于项目根目录）
SNAPSHOTS_DIR = f"{SYSTEM_DIR}/snapshots"

# ============================================================
# 对话相关路径
# ============================================================

# 对话历史目录（相对于项目根目录）
CONVERSATIONS_DIR = f"{SYSTEM_DIR}/conversations"

# ============================================================
# 临时文件路径
# ============================================================

# 临时文件目录（相对于项目根目录）
TEMP_DIR = f"{SYSTEM_DIR}/temp"

# ============================================================
# 检查点路径
# ============================================================

# LangGraph 检查点数据库（相对于项目根目录）
CHECKPOINTS_DB = f"{SYSTEM_DIR}/checkpoints.sqlite3"

# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SYSTEM_DIR",
    "SIM_RESULTS_DIR",
    "SIM_CONFIG_FILE",
    "ANALYSIS_SELECTION_FILE",
    "CHART_SELECTION_FILE",
    "DESIGN_GOALS_FILE",
    "ITERATION_HISTORY_FILE",
    "UNDO_SNAPSHOTS_DIR",
    "SNAPSHOTS_DIR",
    "CONVERSATIONS_DIR",
    "TEMP_DIR",
    "CHECKPOINTS_DB",
]
