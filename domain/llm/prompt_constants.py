# Prompt Constants - Prompt Template Name Constants
"""
Prompt 模板名称常量定义

职责：
- 集中定义所有 Prompt 模板名称常量
- 避免字符串硬编码
- 作为 PromptTemplateManager 获取模板的键

设计原则：
- 纯常量定义，不依赖任何其他模块
- 任务级模板使用 PROMPT_ 前缀
- 输出格式模板使用 FORMAT_ 前缀
- 按功能模块分组组织

使用示例：
    from domain.llm.prompt_constants import PROMPT_EXTRACT_DESIGN_GOALS
    prompt = prompt_manager.get_template(PROMPT_EXTRACT_DESIGN_GOALS, variables)
"""

# ============================================================
# 任务级模板名称常量
# ============================================================

# 设计目标提取 - 从用户需求中提取结构化设计目标
# 使用节点：design_goals_node
PROMPT_EXTRACT_DESIGN_GOALS = "EXTRACT_DESIGN_GOALS"

# 初始设计 - 生成初始 SPICE 电路
# 使用节点：initial_design_node
PROMPT_INITIAL_DESIGN = "INITIAL_DESIGN"

# 仿真结果分析 - 分析仿真结果
# 使用节点：analysis_node
PROMPT_ANALYZE_SIMULATION = "ANALYZE_SIMULATION_RESULTS"

# 参数优化 - 生成参数优化建议
# 使用节点：OptimizeParametersAction
PROMPT_OPTIMIZE_PARAMETERS = "OPTIMIZE_PARAMETERS"

# 错误修复 - 修复仿真/语法错误
# 使用节点：FixErrorAction
PROMPT_FIX_ERROR = "FIX_ERROR"

# 执行用户指令 - 执行用户的具体指令
# 使用节点：ExecuteInstructionAction
PROMPT_EXECUTE_INSTRUCTION = "EXECUTE_USER_INSTRUCTION"

# 通用对话 - 通用对话回复
# 使用节点：GeneralConversationAction
PROMPT_GENERAL_CONVERSATION = "GENERAL_CONVERSATION"

# 对话摘要 - 生成对话摘要用于上下文压缩
# 使用模块：context_compressor
PROMPT_SUMMARIZE_CONVERSATION = "SUMMARIZE_CONVERSATION"

# 意图分析 - 分析用户意图
# 使用节点：intent_analysis_node
PROMPT_INTENT_ANALYSIS = "INTENT_ANALYSIS"


# ============================================================
# 输出格式模板名称常量
# ============================================================

# SPICE 代码输出格式规范
FORMAT_SPICE_OUTPUT = "SPICE_OUTPUT_FORMAT"

# 结构化 JSON 输出格式规范
FORMAT_JSON_OUTPUT = "JSON_OUTPUT_FORMAT"

# 分析报告输出格式规范
FORMAT_ANALYSIS_OUTPUT = "ANALYSIS_OUTPUT_FORMAT"


# ============================================================
# 模板与输出格式的映射关系
# ============================================================

# 定义哪些任务模板需要附加哪种输出格式
TEMPLATE_FORMAT_MAPPING = {
    PROMPT_EXTRACT_DESIGN_GOALS: FORMAT_JSON_OUTPUT,
    PROMPT_INITIAL_DESIGN: FORMAT_SPICE_OUTPUT,
    PROMPT_ANALYZE_SIMULATION: FORMAT_ANALYSIS_OUTPUT,
    PROMPT_OPTIMIZE_PARAMETERS: FORMAT_SPICE_OUTPUT,
    PROMPT_FIX_ERROR: FORMAT_SPICE_OUTPUT,
    PROMPT_EXECUTE_INSTRUCTION: FORMAT_SPICE_OUTPUT,
    PROMPT_GENERAL_CONVERSATION: None,  # 通用对话不需要特定格式
    PROMPT_SUMMARIZE_CONVERSATION: None,  # 摘要不需要特定格式
    PROMPT_INTENT_ANALYSIS: FORMAT_JSON_OUTPUT,
}


# ============================================================
# 节点与模板的映射关系
# ============================================================

# 节点名称常量（与 LangGraph 节点名称对应）
NODE_DESIGN_GOALS = "design_goals_node"
NODE_INITIAL_DESIGN = "initial_design_node"
NODE_ANALYSIS = "analysis_node"
NODE_INTENT_ANALYSIS = "intent_analysis_node"

# Action 名称常量
ACTION_OPTIMIZE_PARAMETERS = "OptimizeParametersAction"
ACTION_FIX_ERROR = "FixErrorAction"
ACTION_EXECUTE_INSTRUCTION = "ExecuteInstructionAction"
ACTION_GENERAL_CONVERSATION = "GeneralConversationAction"

# 节点/Action 与模板的映射
# 用于文档和调试，实际调用时节点直接使用模板常量
NODE_TEMPLATE_MAPPING = {
    # LangGraph 节点
    NODE_DESIGN_GOALS: PROMPT_EXTRACT_DESIGN_GOALS,
    NODE_INITIAL_DESIGN: PROMPT_INITIAL_DESIGN,
    NODE_ANALYSIS: PROMPT_ANALYZE_SIMULATION,
    NODE_INTENT_ANALYSIS: PROMPT_INTENT_ANALYSIS,
    # Action 类
    ACTION_OPTIMIZE_PARAMETERS: PROMPT_OPTIMIZE_PARAMETERS,
    ACTION_FIX_ERROR: PROMPT_FIX_ERROR,
    ACTION_EXECUTE_INSTRUCTION: PROMPT_EXECUTE_INSTRUCTION,
    ACTION_GENERAL_CONVERSATION: PROMPT_GENERAL_CONVERSATION,
}


def get_template_for_node(node_name: str) -> str:
    """
    根据节点名称获取对应的模板常量名
    
    Args:
        node_name: 节点或 Action 名称
        
    Returns:
        模板常量名
        
    Raises:
        KeyError: 节点名称未在映射中定义
        
    使用示例：
        template_name = get_template_for_node("design_goals_node")
        prompt = prompt_manager.get_template(template_name, variables)
    """
    if node_name not in NODE_TEMPLATE_MAPPING:
        raise KeyError(f"No template mapping found for node: {node_name}")
    return NODE_TEMPLATE_MAPPING[node_name]


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 任务级模板
    "PROMPT_EXTRACT_DESIGN_GOALS",
    "PROMPT_INITIAL_DESIGN",
    "PROMPT_ANALYZE_SIMULATION",
    "PROMPT_OPTIMIZE_PARAMETERS",
    "PROMPT_FIX_ERROR",
    "PROMPT_EXECUTE_INSTRUCTION",
    "PROMPT_GENERAL_CONVERSATION",
    "PROMPT_SUMMARIZE_CONVERSATION",
    "PROMPT_INTENT_ANALYSIS",
    # 输出格式模板
    "FORMAT_SPICE_OUTPUT",
    "FORMAT_JSON_OUTPUT",
    "FORMAT_ANALYSIS_OUTPUT",
    # 映射关系
    "TEMPLATE_FORMAT_MAPPING",
    "NODE_TEMPLATE_MAPPING",
    # 节点名称常量
    "NODE_DESIGN_GOALS",
    "NODE_INITIAL_DESIGN",
    "NODE_ANALYSIS",
    "NODE_INTENT_ANALYSIS",
    # Action 名称常量
    "ACTION_OPTIMIZE_PARAMETERS",
    "ACTION_FIX_ERROR",
    "ACTION_EXECUTE_INSTRUCTION",
    "ACTION_GENERAL_CONVERSATION",
    # 辅助函数
    "get_template_for_node",
]
