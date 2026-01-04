# SimulationError - Simulation Error Data Class
"""
仿真错误数据类

职责：
- 定义标准化的仿真错误数据结构
- 提供错误信息的序列化和反序列化
- 支持错误恢复建议和用户友好消息

设计原则：
- 使用 dataclass 确保类型安全
- 使用枚举定义错误类型和严重级别
- 提供详细的错误上下文信息
- 支持错误恢复策略集成

使用示例：
    # 创建语法错误
    error = SimulationError(
        code="E001",
        type=SimulationErrorType.SYNTAX_ERROR,
        severity=ErrorSeverity.HIGH,
        message="Syntax error on line 15",
        file_path="amplifier.cir",
        line_number=15,
        context="R1 vcc out 10k",
        details={"expected": "3 nodes", "found": "2 nodes"},
        recovery_suggestion="Check resistor connection syntax"
    )
    
    # 序列化
    error_dict = error.to_dict()
    
    # 反序列化
    loaded_error = SimulationError.from_dict(error_dict)
    
    # 检查是否可恢复
    if error.is_recoverable():
        # 尝试自动恢复
        pass
    
    # 获取用户友好消息
    user_msg = error.get_user_message()
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ============================================================
# SimulationErrorType - 仿真错误类型枚举
# ============================================================

class SimulationErrorType(Enum):
    """
    仿真错误类型枚举
    
    定义了所有可能的仿真错误类型，每个类型对应一个唯一的错误码
    """
    
    SYNTAX_ERROR = "E001"
    """语法错误：网表文件语法不正确"""
    
    MODEL_MISSING = "E002"
    """模型缺失：引用的 SPICE 模型不存在"""
    
    NODE_FLOATING = "E003"
    """节点浮空：电路中存在浮空节点（无 DC 路径到地）"""
    
    CONVERGENCE_DC = "E004"
    """DC 收敛失败：直流工作点分析无法收敛"""
    
    CONVERGENCE_TRAN = "E005"
    """瞬态收敛失败：瞬态分析无法收敛"""
    
    TIMEOUT = "E006"
    """超时：仿真执行超过时间限制"""
    
    MEMORY_OVERFLOW = "E007"
    """内存溢出：仿真过程中内存不足"""
    
    NGSPICE_CRASH = "E008"
    """ngspice 崩溃：仿真引擎异常终止"""
    
    FILE_ACCESS = "E009"
    """文件访问错误：无法读取或写入文件"""
    
    PARAMETER_INVALID = "E010"
    """参数无效：仿真参数配置不正确"""


# ============================================================
# ErrorSeverity - 错误严重级别枚举
# ============================================================

class ErrorSeverity(Enum):
    """
    错误严重级别枚举
    
    定义了错误的严重程度，用于指导错误处理策略
    """
    
    LOW = "low"
    """低：不影响仿真结果，仅为警告信息"""
    
    MEDIUM = "medium"
    """中：影响部分仿真结果，但可继续执行"""
    
    HIGH = "high"
    """高：导致仿真失败，需要用户干预"""
    
    CRITICAL = "critical"
    """严重：系统级错误，可能影响软件稳定性"""


# ============================================================
# SimulationError - 仿真错误数据类
# ============================================================

@dataclass
class SimulationError:
    """
    仿真错误数据类
    
    Attributes:
        code: 错误码（如 "E001"）
        type: 错误类型（SimulationErrorType 枚举）
        severity: 严重级别（ErrorSeverity 枚举）
        message: 错误消息摘要
        file_path: 出错文件路径（可选）
        line_number: 出错行号（可选）
        context: 错误上下文代码（可选）
        details: 详细信息字典（可选）
        recovery_attempted: 是否已尝试恢复
        recovery_result: 恢复结果（可选）
        recovery_suggestion: 恢复建议（可选）
        raw_output: 原始输出（可选）
    """
    
    code: str
    """错误码（如 "E001"）"""
    
    type: SimulationErrorType
    """错误类型（SimulationErrorType 枚举）"""
    
    severity: ErrorSeverity
    """严重级别（ErrorSeverity 枚举）"""
    
    message: str
    """错误消息摘要"""
    
    file_path: Optional[str] = None
    """出错文件路径"""
    
    line_number: Optional[int] = None
    """出错行号"""
    
    context: Optional[str] = None
    """错误上下文代码（出错行及其前后几行）"""
    
    details: Optional[Dict[str, Any]] = field(default_factory=dict)
    """详细信息字典（如 {"expected": "3 nodes", "found": "2 nodes"}）"""
    
    recovery_attempted: bool = False
    """是否已尝试自动恢复"""
    
    recovery_result: Optional[str] = None
    """恢复结果（如 "success", "failed", "partial"）"""
    
    recovery_suggestion: Optional[str] = None
    """恢复建议（用户友好的修复建议）"""
    
    raw_output: Optional[str] = None
    """原始输出（完整的仿真器输出，用于调试）"""
    
    # ============================================================
    # 序列化方法
    # ============================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict: 序列化后的字典
        """
        return {
            "code": self.code,
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "context": self.context,
            "details": self.details,
            "recovery_attempted": self.recovery_attempted,
            "recovery_result": self.recovery_result,
            "recovery_suggestion": self.recovery_suggestion,
            "raw_output": self.raw_output,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationError":
        """
        从字典反序列化
        
        Args:
            data: 序列化的字典
            
        Returns:
            SimulationError: 反序列化后的对象
        """
        # 解析错误类型枚举
        error_type = SimulationErrorType(data["type"])
        
        # 解析严重级别枚举
        severity = ErrorSeverity(data["severity"])
        
        return cls(
            code=data["code"],
            type=error_type,
            severity=severity,
            message=data["message"],
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            context=data.get("context"),
            details=data.get("details", {}),
            recovery_attempted=data.get("recovery_attempted", False),
            recovery_result=data.get("recovery_result"),
            recovery_suggestion=data.get("recovery_suggestion"),
            raw_output=data.get("raw_output"),
        )
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def is_recoverable(self) -> bool:
        """
        判断是否可自动恢复
        
        根据错误类型判断是否支持自动恢复策略
        
        Returns:
            bool: 是否可自动恢复
        """
        # 可自动恢复的错误类型
        recoverable_types = {
            SimulationErrorType.CONVERGENCE_DC,
            SimulationErrorType.CONVERGENCE_TRAN,
            SimulationErrorType.NODE_FLOATING,
        }
        
        return self.type in recoverable_types
    
    def get_user_message(self) -> str:
        """
        获取用户友好的错误消息
        
        将技术性错误信息转换为用户易于理解的描述
        
        Returns:
            str: 用户友好的错误消息
        """
        # 构建基础消息
        user_msg = f"[{self.code}] {self.message}"
        
        # 添加文件位置信息
        if self.file_path:
            location = f"文件: {self.file_path}"
            if self.line_number:
                location += f", 行号: {self.line_number}"
            user_msg += f"\n{location}"
        
        # 添加错误上下文
        if self.context:
            user_msg += f"\n上下文:\n{self.context}"
        
        # 添加恢复建议
        if self.recovery_suggestion:
            user_msg += f"\n\n建议: {self.recovery_suggestion}"
        elif self.is_recoverable():
            user_msg += "\n\n提示: 此错误可能支持自动恢复，系统将尝试调整参数后重新仿真"
        
        # 添加恢复结果
        if self.recovery_attempted:
            if self.recovery_result == "success":
                user_msg += "\n\n✓ 自动恢复成功"
            elif self.recovery_result == "failed":
                user_msg += "\n\n✗ 自动恢复失败，请手动修复"
            elif self.recovery_result == "partial":
                user_msg += "\n\n⚠ 部分恢复成功，建议检查结果"
        
        return user_msg
    
    def get_short_message(self) -> str:
        """
        获取简短的错误消息（用于状态栏显示）
        
        Returns:
            str: 简短的错误消息
        """
        return f"[{self.code}] {self.message}"
    
    def is_critical(self) -> bool:
        """
        判断是否为严重错误
        
        Returns:
            bool: 是否为严重错误
        """
        return self.severity == ErrorSeverity.CRITICAL
    
    def is_high_severity(self) -> bool:
        """
        判断是否为高严重级别错误
        
        Returns:
            bool: 是否为高严重级别错误
        """
        return self.severity in {ErrorSeverity.HIGH, ErrorSeverity.CRITICAL}
    
    def get_error_category(self) -> str:
        """
        获取错误类别（用于分类统计）
        
        Returns:
            str: 错误类别
        """
        category_map = {
            SimulationErrorType.SYNTAX_ERROR: "语法错误",
            SimulationErrorType.MODEL_MISSING: "模型问题",
            SimulationErrorType.NODE_FLOATING: "电路拓扑",
            SimulationErrorType.CONVERGENCE_DC: "收敛问题",
            SimulationErrorType.CONVERGENCE_TRAN: "收敛问题",
            SimulationErrorType.TIMEOUT: "性能问题",
            SimulationErrorType.MEMORY_OVERFLOW: "资源问题",
            SimulationErrorType.NGSPICE_CRASH: "系统错误",
            SimulationErrorType.FILE_ACCESS: "文件问题",
            SimulationErrorType.PARAMETER_INVALID: "配置问题",
        }
        
        return category_map.get(self.type, "未知错误")


# ============================================================
# 工厂方法
# ============================================================

def create_syntax_error(
    message: str,
    file_path: Optional[str] = None,
    line_number: Optional[int] = None,
    context: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    recovery_suggestion: Optional[str] = None
) -> SimulationError:
    """
    创建语法错误
    
    Args:
        message: 错误消息
        file_path: 出错文件路径
        line_number: 出错行号
        context: 错误上下文代码
        details: 详细信息
        recovery_suggestion: 恢复建议
        
    Returns:
        SimulationError: 语法错误对象
    """
    return SimulationError(
        code="E001",
        type=SimulationErrorType.SYNTAX_ERROR,
        severity=ErrorSeverity.HIGH,
        message=message,
        file_path=file_path,
        line_number=line_number,
        context=context,
        details=details or {},
        recovery_suggestion=recovery_suggestion or "请检查网表文件语法是否正确",
    )


def create_model_missing_error(
    message: str,
    file_path: Optional[str] = None,
    missing_models: Optional[list[str]] = None,
    recovery_suggestion: Optional[str] = None
) -> SimulationError:
    """
    创建模型缺失错误
    
    Args:
        message: 错误消息
        file_path: 出错文件路径
        missing_models: 缺失的模型列表
        recovery_suggestion: 恢复建议
        
    Returns:
        SimulationError: 模型缺失错误对象
    """
    details = {}
    if missing_models:
        details["missing_models"] = missing_models
    
    return SimulationError(
        code="E002",
        type=SimulationErrorType.MODEL_MISSING,
        severity=ErrorSeverity.HIGH,
        message=message,
        file_path=file_path,
        details=details,
        recovery_suggestion=recovery_suggestion or "请检查模型文件路径或安装缺失的模型库",
    )


def create_convergence_error(
    message: str,
    is_dc: bool = True,
    file_path: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    recovery_suggestion: Optional[str] = None
) -> SimulationError:
    """
    创建收敛失败错误
    
    Args:
        message: 错误消息
        is_dc: 是否为 DC 收敛失败（True）或瞬态收敛失败（False）
        file_path: 出错文件路径
        details: 详细信息
        recovery_suggestion: 恢复建议
        
    Returns:
        SimulationError: 收敛失败错误对象
    """
    if is_dc:
        error_type = SimulationErrorType.CONVERGENCE_DC
        code = "E004"
        default_suggestion = "尝试调整收敛参数（gmin、reltol）或添加初始条件"
    else:
        error_type = SimulationErrorType.CONVERGENCE_TRAN
        code = "E005"
        default_suggestion = "尝试减小时间步长或调整收敛参数"
    
    return SimulationError(
        code=code,
        type=error_type,
        severity=ErrorSeverity.MEDIUM,
        message=message,
        file_path=file_path,
        details=details or {},
        recovery_suggestion=recovery_suggestion or default_suggestion,
    )


def create_timeout_error(
    message: str,
    file_path: Optional[str] = None,
    timeout_seconds: Optional[float] = None
) -> SimulationError:
    """
    创建超时错误
    
    Args:
        message: 错误消息
        file_path: 出错文件路径
        timeout_seconds: 超时时间（秒）
        
    Returns:
        SimulationError: 超时错误对象
    """
    details = {}
    if timeout_seconds:
        details["timeout_seconds"] = timeout_seconds
    
    return SimulationError(
        code="E006",
        type=SimulationErrorType.TIMEOUT,
        severity=ErrorSeverity.MEDIUM,
        message=message,
        file_path=file_path,
        details=details,
        recovery_suggestion="尝试增加超时时间或简化电路复杂度",
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SimulationError",
    "SimulationErrorType",
    "ErrorSeverity",
    "create_syntax_error",
    "create_model_missing_error",
    "create_convergence_error",
    "create_timeout_error",
]
