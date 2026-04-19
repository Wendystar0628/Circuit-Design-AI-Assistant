# Agent Types - Agent 工具调用基础类型体系
"""
Agent 工具调用基础类型定义

职责：
- 定义工具执行结果（ToolResult）
- 定义工具 JSON Schema（ToolSchema）
- 定义工具执行上下文（ToolContext）
- 定义工具调用信息（ToolCallInfo）
- 定义工具抽象基类（BaseTool）

设计原则：
- 类型对齐 OpenAI Function Calling 协议格式，智谱 API 直接兼容
- BaseTool 自包含 schema 和 execute，新增工具只需创建一个文件并注册
- ToolResult.content 为字符串（智谱 role:tool 消息只接受字符串）
- ToolResult.details 仅供 UI 使用，不会发送给 LLM
- ToolContext 通过依赖注入，避免工具直接依赖全局服务

参考来源：
- pi-mono: packages/agent/src/types.ts (AgentTool, AgentToolResult)
- pi-mono: packages/coding-agent/src/core/extensions/types.ts (ToolDefinition)

使用示例：
    from domain.llm.agent.types import BaseTool, ToolResult, ToolContext

    class ReadFileTool(BaseTool):
        @property
        def name(self) -> str:
            return "read_file"

        @property
        def description(self) -> str:
            return "读取文件内容"

        @property
        def parameters(self) -> Dict[str, Any]:
            return {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"]
            }

        async def execute(self, tool_call_id, params, context):
            # 实现文件读取逻辑
            return ToolResult(content="文件内容...")
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # 仅静态分析导入：避免 domain 层在运行时反向依赖
    # application 层（PendingWorkspaceEditService）与具体服务实现，
    # 同时保留字段的显式类型注解。
    from application.pending_workspace_edit_service import (
        PendingWorkspaceEditService,
    )
    from domain.rag.rag_manager import RAGManager
    from domain.services.simulation_job_manager import SimulationJobManager


# ============================================================
# 工具执行结果
# ============================================================

@dataclass
class ToolResult:
    """
    工具执行结果
    
    对应 pi-mono 的 AgentToolResult。
    
    Attributes:
        content: 返回给 LLM 的纯文本内容
            - 智谱 API 的 role:tool 消息只接受字符串
            - 成功时为结果描述，失败时为错误消息
        is_error: 标记是否为错误结果
            - True 时 LLM 会收到错误信息并自行决策下一步
            - 对应 pi-mono 的 isError 字段
        details: 供 UI 展示的结构化详情（可选）
            - 不会发送给 LLM，仅供前端渲染
            - 例如：diff 信息、行号、文件统计等
    """
    content: str
    is_error: bool = False
    details: Optional[Dict[str, Any]] = None


# ============================================================
# 工具 Schema 定义
# ============================================================

@dataclass
class ToolSchema:
    """
    工具的 JSON Schema 定义，用于 LLM API 的 tools 参数
    
    生成的格式遵循 OpenAI Function Calling 标准：
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": { ... JSON Schema ... }
        }
    }
    
    Attributes:
        name: 工具名称（LLM 调用时使用的标识符）
        description: 工具描述（告诉 LLM 该工具的功能和使用场景）
        parameters: JSON Schema 格式的参数定义
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    
    def to_openai_format(self) -> Dict[str, Any]:
        """
        转换为 OpenAI Function Calling 格式
        
        Returns:
            符合 OpenAI tools 参数规范的字典，智谱 API 直接兼容
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


# ============================================================
# 工具执行上下文
# ============================================================

@dataclass
class ToolContext:
    """工具执行时的上下文环境。

    通过依赖注入传递给工具的 ``execute()`` 方法——工具**唯一**的
    外部依赖入口。禁止工具内部直接访问 ``ServiceLocator`` 或任何
    全局服务：要么 context 提供，要么工具把"调用方没提供"当成
    is_error 返回，绝不做"context 没有就回落到 ServiceLocator"的
    双路径。

    对应 pi-mono 中 ``createCodingToolDefinitions(cwd)`` 传入 cwd
    的模式，但扩展为更完整的依赖注入容器。

    Attributes:
        project_root: 当前项目根目录（绝对路径）
            - 所有文件操作的基准目录
            - 安全校验：禁止操作此目录之外的文件
        current_file: 当前编辑器活动电路文件的绝对路径（可选）
            - agent 不显式传 ``file_path`` 时的回落项
            - 同时写入系统提示词供 LLM 感知当前上下文
        allowed_extensions: 允许操作的文件扩展名列表（可选）
            - 不设置时允许所有扩展名
        max_file_size_bytes: 读取文件的最大字节数限制（默认 200KB）
        max_read_lines: 单次读取的最大行数（默认 2000，与 pi-mono
            truncate.ts 一致）
        rag_query_service: RAG 检索服务（RAGSearchTool 依赖）
        sim_job_manager: 仿真 Job 管理器（仿真系列 tool 依赖，
            SimulationJobManager 是并发 job 提交与生命周期的唯一
            权威入口）
        pending_workspace_edit_service: 待写工作区编辑服务
            （PatchFileTool / RewriteFileTool 依赖，落盘前先写入
            pending 队列由用户审核）
    """
    project_root: str
    current_file: Optional[str] = None
    allowed_extensions: Optional[List[str]] = None
    max_file_size_bytes: int = 200 * 1024  # 200KB
    max_read_lines: int = 2000
    rag_query_service: Optional["RAGManager"] = None
    sim_job_manager: Optional["SimulationJobManager"] = None
    pending_workspace_edit_service: Optional["PendingWorkspaceEditService"] = None


# ============================================================
# 工具调用信息（从 LLM 响应解析）
# ============================================================

@dataclass
class ToolCallInfo:
    """
    描述一次工具调用的信息，从 LLM 响应中解析得到
    
    对应 ChatResponse.tool_calls 中的单个元素，
    以及 StreamChunk.tool_calls 累积完成后的单个元素。
    
    LLM API 返回的原始格式：
    {
        "id": "call_xxx",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": {"path": "test.cir"}  # 或 JSON 字符串
        }
    }
    
    本类将其展平为更易用的结构。
    
    Attributes:
        id: 工具调用 ID（由 LLM API 生成，回传 role:tool 消息时必须携带）
        name: 工具名称
        arguments: 已解析的参数字典
    """
    id: str
    name: str
    arguments: Dict[str, Any]
    
    @classmethod
    def from_api_format(cls, raw: Dict[str, Any]) -> "ToolCallInfo":
        """
        从 LLM API 返回的原始格式创建 ToolCallInfo
        
        处理 arguments 可能是字符串或已解析字典两种情况。
        
        Args:
            raw: API 返回的工具调用字典
            
        Returns:
            ToolCallInfo 实例
            
        Raises:
            ValueError: 如果必要字段缺失
        """
        import json
        
        call_id = raw.get("id", "")
        if not call_id:
            raise ValueError("Tool call missing 'id' field")
        
        function = raw.get("function", {})
        name = function.get("name", "")
        if not name:
            raise ValueError("Tool call missing 'function.name' field")
        
        # arguments 可能是 JSON 字符串（非流式）或已解析的字典（流式累积后）
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                raise ValueError(
                    f"Tool call '{name}' has invalid JSON arguments: "
                    f"{arguments[:100]}"
                )
        
        return cls(id=call_id, name=name, arguments=arguments)
    
    @classmethod
    def from_api_list(cls, raw_list: List[Dict[str, Any]]) -> List["ToolCallInfo"]:
        """
        从 LLM API 返回的工具调用列表批量创建 ToolCallInfo
        
        Args:
            raw_list: API 返回的工具调用字典列表
            
        Returns:
            ToolCallInfo 实例列表
        """
        return [cls.from_api_format(raw) for raw in raw_list]


# ============================================================
# 工具抽象基类
# ============================================================

class BaseTool(ABC):
    """
    工具抽象基类
    
    对应 pi-mono 的 AgentTool 接口。
    每个工具是一个自包含的对象，同时携带 Schema 定义和执行逻辑。
    
    新增工具只需：
    1. 继承 BaseTool
    2. 实现 name、description、parameters 属性
    3. 实现 execute() 方法
    4. 在 ToolRegistry 中注册
    
    设计要点：
    - get_schema() 返回 OpenAI Function Calling 标准格式
    - execute() 接收已解析的参数字典（不是 JSON 字符串）
    - execute() 通过抛异常表示失败，循环层自动包装为 ToolResult(is_error=True)
    - prompt_snippet 和 prompt_guidelines 供系统提示词构建器使用
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        工具名称（LLM 调用时使用的唯一标识符）
        
        命名规范：小写字母 + 下划线，如 "read_file"、"patch_file"
        """
        ...
    
    @property
    def label(self) -> str:
        """
        工具的 UI 显示名称
        
        默认返回 name，子类可覆盖以提供更友好的显示名。
        对应 pi-mono AgentTool.label。
        """
        return self.name
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        工具描述（供 LLM 理解工具功能）
        
        应简洁明确地说明工具的功能、使用场景和限制。
        此描述会出现在 LLM API 的 tools 参数中。
        """
        ...
    
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        参数定义（JSON Schema 格式）
        
        必须是合法的 JSON Schema 对象，例如：
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，相对于项目根目录或绝对路径"
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（1-indexed）"
                }
            },
            "required": ["path"]
        }
        """
        ...
    
    @property
    def prompt_snippet(self) -> Optional[str]:
        """
        系统提示词中的一句话工具描述（可选）
        
        用于在系统提示词的"可用工具列表"中展示。
        格式如："读取文件内容，支持行号范围和截断"
        
        对应 pi-mono ToolDefinition.promptSnippet。
        不设置时系统提示词中使用 description 的前 50 个字符。
        """
        return None
    
    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        """
        系统提示词中的使用指南列表（可选）
        
        每个元素是一条使用建议，会追加到系统提示词的 Guidelines 部分。
        例如：["修改文件前先用 read_file 查看当前内容"]
        
        对应 pi-mono ToolDefinition.promptGuidelines。
        """
        return None
    
    def get_schema(self) -> ToolSchema:
        """
        获取工具的 Schema 定义
        
        Returns:
            ToolSchema 实例
        """
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
    
    def get_openai_schema(self) -> Dict[str, Any]:
        """
        获取 OpenAI Function Calling 格式的工具定义
        
        返回的字典可直接放入 LLM API 的 tools 列表中。
        智谱 API 兼容此格式。
        
        Returns:
            {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        """
        return self.get_schema().to_openai_format()
    
    @abstractmethod
    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """
        执行工具
        
        Args:
            tool_call_id: 工具调用 ID（由 LLM API 生成）
            params: 已解析的参数字典（从 ToolCallInfo.arguments 传入）
            context: 工具执行上下文
            
        Returns:
            ToolResult: 执行结果
            
        Raises:
            Exception: 执行失败时可直接抛异常，
                       AgentLoop 会捕获并包装为 ToolResult(is_error=True)
            
        Note:
            - 对应 pi-mono AgentTool.execute(toolCallId, params, signal, onUpdate)
            - 本项目暂不支持 signal（取消）和 onUpdate（增量更新）参数
            - 后续可按需扩展
        """
        ...
    
    def validate_params(self, params: Dict[str, Any]) -> Optional[str]:
        """
        校验参数合法性（可选覆盖）
        
        在 execute() 之前由 AgentLoop 的 prepare 阶段调用。
        默认实现检查 required 字段是否存在。
        
        Args:
            params: 待校验的参数字典
            
        Returns:
            None: 参数合法
            str: 错误描述（参数不合法时）
        """
        schema = self.parameters
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        
        # 检查必填字段
        for field_name in required:
            if field_name not in params:
                return f"Missing required parameter: '{field_name}'"
            if params[field_name] is None:
                return f"Parameter '{field_name}' cannot be null"
        
        # 检查未知字段（警告级别，不阻止执行）
        known_fields = set(properties.keys())
        unknown_fields = set(params.keys()) - known_fields
        if unknown_fields:
            # 不阻止执行，仅记录。LLM 偶尔会传多余字段。
            pass
        
        return None
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"


# ============================================================
# 工具执行结果的工厂函数
# ============================================================

def create_error_result(
    error_message: str,
    details: Optional[Dict[str, Any]] = None,
) -> ToolResult:
    """
    创建错误工具结果的工厂函数
    
    对应 pi-mono agent-loop.ts 中的 createErrorToolResult()。
    用于 AgentLoop 在工具执行异常时统一包装错误。
    
    Args:
        error_message: 错误描述（返回给 LLM）
        details: 额外的错误详情（供 UI 展示）
        
    Returns:
        ToolResult(is_error=True)
    """
    return ToolResult(
        content=error_message,
        is_error=True,
        details=details,
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 核心类型
    "ToolResult",
    "ToolSchema",
    "ToolContext",
    "ToolCallInfo",
    "BaseTool",
    # 工厂函数
    "create_error_result",
]
