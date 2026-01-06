# WaveformMathService - Waveform Mathematical Operations Service
"""
波形数学运算服务

职责：
- 解析波形数学表达式
- 执行信号间的数学运算
- 支持微分、积分、dB 转换等常用运算
- 为 UI 层提供运算结果

设计原则：
- 表达式解析使用安全的 AST 方式，禁止 eval
- 支持常见的 SPICE 波形运算语法
- 运算结果返回 WaveformData 格式，可直接用于显示

支持的表达式：
- 信号引用：V(out), I(R1), V(in)
- 算术运算：+, -, *, /
- 数学函数：abs, sqrt, log, log10, exp, sin, cos, tan
- 微分：d(V(out))/dt 或 deriv(V(out))
- 积分：integ(V(out))
- dB 转换：db(V(out)) 等价于 20*log10(abs(V(out)))
- 相位：phase(V(out)) 或 arg(V(out))
- 实部/虚部：real(V(out)), imag(V(out))

使用示例：
    from domain.simulation.data.waveform_math_service import waveform_math_service
    
    # 计算增益
    result = waveform_math_service.evaluate(
        sim_result, "db(V(out)/V(in))"
    )
    
    # 计算微分
    result = waveform_math_service.evaluate(
        sim_result, "deriv(V(out))"
    )
    
    # 信号相减
    result = waveform_math_service.evaluate(
        sim_result, "V(out) - V(in)"
    )
"""

import ast
import logging
import math
import operator
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.data.waveform_data_service import WaveformData


# ============================================================
# 常量定义
# ============================================================

# 信号名称正则表达式：V(xxx), I(xxx), v(xxx), i(xxx)
SIGNAL_PATTERN = re.compile(r'([VvIi])\(([^)]+)\)')

# 微分表达式正则：d(xxx)/dt 或 deriv(xxx)
# 使用非贪婪匹配，但允许嵌套一层括号
DERIV_PATTERN = re.compile(r'd\(([^()]*(?:\([^)]*\)[^()]*)*)\)/dt|deriv\(([^()]*(?:\([^)]*\)[^()]*)*)\)')

# 积分表达式正则：integ(xxx)
INTEG_PATTERN = re.compile(r'integ\(([^()]*(?:\([^)]*\)[^()]*)*)\)')

# dB 转换正则：db(xxx)
DB_PATTERN = re.compile(r'db\(([^)]+)\)')

# 相位正则：phase(xxx) 或 arg(xxx)
PHASE_PATTERN = re.compile(r'(?:phase|arg)\(([^)]+)\)')

# 实部/虚部正则
REAL_PATTERN = re.compile(r'real\(([^)]+)\)')
IMAG_PATTERN = re.compile(r'imag\(([^)]+)\)')


# ============================================================
# 数据类定义
# ============================================================

class MathErrorCode(Enum):
    """数学运算错误码"""
    SUCCESS = "success"
    INVALID_EXPRESSION = "invalid_expression"
    SIGNAL_NOT_FOUND = "signal_not_found"
    DIVISION_BY_ZERO = "division_by_zero"
    INVALID_OPERATION = "invalid_operation"
    DATA_LENGTH_MISMATCH = "data_length_mismatch"
    NO_DATA = "no_data"
    UNKNOWN_FUNCTION = "unknown_function"


@dataclass
class MathResult:
    """
    数学运算结果
    
    Attributes:
        success: 是否成功
        data: 运算结果数据（成功时有值）
        error_code: 错误码（失败时有值）
        error_message: 错误消息（失败时有值）
        expression: 原始表达式
    """
    success: bool
    data: Optional[WaveformData] = None
    error_code: Optional[MathErrorCode] = None
    error_message: Optional[str] = None
    expression: str = ""
    
    @classmethod
    def ok(cls, data: WaveformData, expression: str) -> "MathResult":
        """创建成功结果"""
        return cls(success=True, data=data, expression=expression)
    
    @classmethod
    def error(
        cls, 
        code: MathErrorCode, 
        message: str, 
        expression: str
    ) -> "MathResult":
        """创建错误结果"""
        return cls(
            success=False, 
            error_code=code, 
            error_message=message,
            expression=expression
        )


@dataclass
class PresetOperation:
    """预设运算定义"""
    name: str
    display_name: str
    expression_template: str
    description: str
    requires_two_signals: bool = False


# ============================================================
# 预设运算列表
# ============================================================

PRESET_OPERATIONS: List[PresetOperation] = [
    PresetOperation(
        name="add",
        display_name="+",
        expression_template="{sig1} + {sig2}",
        description="信号相加",
        requires_two_signals=True
    ),
    PresetOperation(
        name="subtract",
        display_name="-",
        expression_template="{sig1} - {sig2}",
        description="信号相减",
        requires_two_signals=True
    ),
    PresetOperation(
        name="multiply",
        display_name="×",
        expression_template="{sig1} * {sig2}",
        description="信号相乘",
        requires_two_signals=True
    ),
    PresetOperation(
        name="divide",
        display_name="÷",
        expression_template="{sig1} / {sig2}",
        description="信号相除",
        requires_two_signals=True
    ),
    PresetOperation(
        name="deriv",
        display_name="d/dt",
        expression_template="deriv({sig1})",
        description="微分"
    ),
    PresetOperation(
        name="integ",
        display_name="∫dt",
        expression_template="integ({sig1})",
        description="积分"
    ),
    PresetOperation(
        name="db",
        display_name="dB",
        expression_template="db({sig1})",
        description="dB 转换 (20*log10|x|)"
    ),
    PresetOperation(
        name="abs",
        display_name="|x|",
        expression_template="abs({sig1})",
        description="绝对值"
    ),
    PresetOperation(
        name="phase",
        display_name="∠",
        expression_template="phase({sig1})",
        description="相位 (度)"
    ),
    PresetOperation(
        name="gain_db",
        display_name="Gain(dB)",
        expression_template="db({sig1}/{sig2})",
        description="增益 (dB)",
        requires_two_signals=True
    ),
]


# ============================================================
# 安全表达式求值器
# ============================================================

class SafeExpressionEvaluator:
    """
    安全的表达式求值器
    
    使用 AST 解析表达式，只允许白名单内的操作。
    """
    
    # 允许的二元运算符
    ALLOWED_BINOPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }
    
    # 允许的一元运算符
    ALLOWED_UNARYOPS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    
    # 允许的数学函数
    ALLOWED_FUNCTIONS = {
        'abs': np.abs,
        'sqrt': np.sqrt,
        'log': np.log,
        'log10': np.log10,
        'exp': np.exp,
        'sin': np.sin,
        'cos': np.cos,
        'tan': np.tan,
        'asin': np.arcsin,
        'acos': np.arccos,
        'atan': np.arctan,
        'sinh': np.sinh,
        'cosh': np.cosh,
        'tanh': np.tanh,
        'real': np.real,
        'imag': np.imag,
        'conj': np.conj,
        'angle': np.angle,
        'unwrap': np.unwrap,
    }
    
    # 允许的常量
    ALLOWED_CONSTANTS = {
        'pi': np.pi,
        'e': np.e,
    }
    
    def __init__(self, variables: Dict[str, np.ndarray]):
        """
        初始化求值器
        
        Args:
            variables: 变量字典，键为变量名，值为 numpy 数组
        """
        self._variables = variables
        self._logger = logging.getLogger(__name__)
    
    def evaluate(self, expression: str) -> np.ndarray:
        """
        求值表达式
        
        Args:
            expression: 数学表达式
            
        Returns:
            np.ndarray: 计算结果
            
        Raises:
            ValueError: 表达式无效或包含不允许的操作
        """
        try:
            tree = ast.parse(expression, mode='eval')
            return self._eval_node(tree.body)
        except SyntaxError as e:
            raise ValueError(f"表达式语法错误: {e}")
    
    def _eval_node(self, node: ast.AST) -> Union[np.ndarray, float]:
        """递归求值 AST 节点"""
        if isinstance(node, ast.Constant):
            return node.value
        
        elif isinstance(node, ast.Name):
            name = node.id
            if name in self._variables:
                return self._variables[name]
            elif name in self.ALLOWED_CONSTANTS:
                return self.ALLOWED_CONSTANTS[name]
            else:
                raise ValueError(f"未知变量: {name}")
        
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)
            if op_type in self.ALLOWED_BINOPS:
                return self.ALLOWED_BINOPS[op_type](left, right)
            else:
                raise ValueError(f"不支持的运算符: {op_type.__name__}")
        
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            if op_type in self.ALLOWED_UNARYOPS:
                return self.ALLOWED_UNARYOPS[op_type](operand)
            else:
                raise ValueError(f"不支持的一元运算符: {op_type.__name__}")
        
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("不支持的函数调用形式")
            
            func_name = node.func.id
            if func_name not in self.ALLOWED_FUNCTIONS:
                raise ValueError(f"不支持的函数: {func_name}")
            
            args = [self._eval_node(arg) for arg in node.args]
            return self.ALLOWED_FUNCTIONS[func_name](*args)
        
        else:
            raise ValueError(f"不支持的表达式类型: {type(node).__name__}")


# ============================================================
# WaveformMathService - 波形数学运算服务
# ============================================================

class WaveformMathService:
    """
    波形数学运算服务
    
    提供波形数学运算的统一入口，支持表达式解析和计算。
    """
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
    def evaluate(
        self,
        result: SimulationResult,
        expression: str,
        result_name: str = "Math Result"
    ) -> MathResult:
        """
        计算波形数学表达式
        
        Args:
            result: 仿真结果对象
            expression: 数学表达式
            result_name: 结果信号名称
            
        Returns:
            MathResult: 运算结果
        """
        if not result.success or result.data is None:
            return MathResult.error(
                MathErrorCode.NO_DATA,
                "仿真结果无数据",
                expression
            )
        
        try:
            # 预处理表达式
            processed_expr, variables = self._preprocess_expression(
                expression, result
            )
            
            if not variables:
                return MathResult.error(
                    MathErrorCode.SIGNAL_NOT_FOUND,
                    "表达式中未找到有效信号",
                    expression
                )
            
            # 获取 X 轴数据
            x_data = self._get_x_axis(result)
            if x_data is None:
                return MathResult.error(
                    MathErrorCode.NO_DATA,
                    "无法获取 X 轴数据",
                    expression
                )
            
            # 添加 X 轴变量（用于微分/积分）
            variables['_x'] = x_data
            
            # 执行计算
            evaluator = SafeExpressionEvaluator(variables)
            y_data = evaluator.evaluate(processed_expr)
            
            # 确保结果是数组
            if np.isscalar(y_data):
                y_data = np.full_like(x_data, y_data)
            
            # 创建结果
            waveform = WaveformData(
                signal_name=result_name,
                x_data=x_data.copy(),
                y_data=np.asarray(y_data),
                is_downsampled=False,
                original_points=len(x_data)
            )
            
            return MathResult.ok(waveform, expression)
            
        except ValueError as e:
            return MathResult.error(
                MathErrorCode.INVALID_EXPRESSION,
                str(e),
                expression
            )
        except ZeroDivisionError:
            return MathResult.error(
                MathErrorCode.DIVISION_BY_ZERO,
                "除零错误",
                expression
            )
        except Exception as e:
            self._logger.exception(f"表达式计算失败: {expression}")
            return MathResult.error(
                MathErrorCode.INVALID_OPERATION,
                f"计算错误: {str(e)}",
                expression
            )
    
    def get_available_signals(self, result: SimulationResult) -> List[str]:
        """
        获取可用信号列表
        
        Args:
            result: 仿真结果对象
            
        Returns:
            List[str]: 信号名称列表
        """
        if not result.success or result.data is None:
            return []
        return result.data.get_signal_names()
    
    def get_preset_operations(self) -> List[PresetOperation]:
        """
        获取预设运算列表
        
        Returns:
            List[PresetOperation]: 预设运算列表
        """
        return PRESET_OPERATIONS.copy()
    
    def build_expression(
        self,
        operation: PresetOperation,
        signal1: str,
        signal2: Optional[str] = None
    ) -> str:
        """
        根据预设运算构建表达式
        
        Args:
            operation: 预设运算
            signal1: 第一个信号
            signal2: 第二个信号（可选）
            
        Returns:
            str: 构建的表达式
        """
        if operation.requires_two_signals and signal2:
            return operation.expression_template.format(
                sig1=signal1, sig2=signal2
            )
        return operation.expression_template.format(sig1=signal1)
    
    def validate_expression(
        self, 
        result: SimulationResult, 
        expression: str
    ) -> Tuple[bool, str]:
        """
        验证表达式是否有效
        
        Args:
            result: 仿真结果对象
            expression: 数学表达式
            
        Returns:
            Tuple[bool, str]: (是否有效, 错误消息)
        """
        if not expression.strip():
            return False, "表达式不能为空"
        
        try:
            processed_expr, variables = self._preprocess_expression(
                expression, result
            )
            
            if not variables:
                return False, "表达式中未找到有效信号"
            
            # 尝试解析
            ast.parse(processed_expr, mode='eval')
            return True, ""
            
        except SyntaxError as e:
            return False, f"语法错误: {e}"
        except Exception as e:
            return False, str(e)
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _preprocess_expression(
        self,
        expression: str,
        result: SimulationResult
    ) -> Tuple[str, Dict[str, np.ndarray]]:
        """
        预处理表达式
        
        将信号引用替换为变量名，处理特殊函数。
        
        Args:
            expression: 原始表达式
            result: 仿真结果
            
        Returns:
            Tuple[str, Dict]: (处理后的表达式, 变量字典)
        """
        variables: Dict[str, np.ndarray] = {}
        processed = expression
        
        # 处理微分：d(xxx)/dt 或 deriv(xxx)
        processed = self._process_deriv(processed, result, variables)
        
        # 处理积分：integ(xxx)
        processed = self._process_integ(processed, result, variables)
        
        # 处理 dB 转换：db(xxx)
        processed = self._process_db(processed)
        
        # 处理相位：phase(xxx) 或 arg(xxx)
        processed = self._process_phase(processed)
        
        # 处理信号引用：V(xxx), I(xxx)
        processed = self._process_signals(processed, result, variables)
        
        return processed, variables
    
    def _process_signals(
        self,
        expression: str,
        result: SimulationResult,
        variables: Dict[str, np.ndarray]
    ) -> str:
        """处理信号引用"""
        def replace_signal(match):
            signal_type = match.group(1).upper()
            signal_node = match.group(2)
            signal_name = f"{signal_type}({signal_node})"
            
            # 尝试获取信号数据
            data = result.data.get_signal(signal_name)
            if data is None:
                # 尝试小写
                signal_name_lower = f"{signal_type.lower()}({signal_node})"
                data = result.data.get_signal(signal_name_lower)
                if data is None:
                    raise ValueError(f"信号不存在: {signal_name}")
            
            # 生成变量名
            var_name = f"_sig_{len(variables)}"
            variables[var_name] = data
            return var_name
        
        return SIGNAL_PATTERN.sub(replace_signal, expression)
    
    def _process_deriv(
        self,
        expression: str,
        result: SimulationResult,
        variables: Dict[str, np.ndarray]
    ) -> str:
        """处理微分运算"""
        def replace_deriv(match):
            inner = match.group(1) or match.group(2)
            
            # 先处理内部的信号引用
            inner_with_signals = self._process_signals(inner, result, variables)
            
            # 计算微分
            var_name = f"_deriv_{len(variables)}"
            
            # 获取 X 轴数据
            x_data = self._get_x_axis(result)
            if x_data is None:
                raise ValueError("无法获取 X 轴数据进行微分")
            
            # 计算内部表达式的值
            evaluator = SafeExpressionEvaluator(variables)
            y_data = evaluator.evaluate(inner_with_signals)
            
            # 数值微分
            dy = np.gradient(y_data, x_data)
            variables[var_name] = dy
            
            return var_name
        
        return DERIV_PATTERN.sub(replace_deriv, expression)
    
    def _process_integ(
        self,
        expression: str,
        result: SimulationResult,
        variables: Dict[str, np.ndarray]
    ) -> str:
        """处理积分运算"""
        def replace_integ(match):
            inner = match.group(1)
            
            # 先处理内部的信号引用
            inner_with_signals = self._process_signals(inner, result, variables)
            
            # 计算积分
            var_name = f"_integ_{len(variables)}"
            
            # 获取 X 轴数据
            x_data = self._get_x_axis(result)
            if x_data is None:
                raise ValueError("无法获取 X 轴数据进行积分")
            
            # 计算内部表达式的值
            evaluator = SafeExpressionEvaluator(variables)
            y_data = evaluator.evaluate(inner_with_signals)
            
            # 数值积分（累积梯形法）
            integral = np.zeros_like(y_data)
            for i in range(1, len(y_data)):
                dx = x_data[i] - x_data[i-1]
                integral[i] = integral[i-1] + 0.5 * (y_data[i] + y_data[i-1]) * dx
            
            variables[var_name] = integral
            return var_name
        
        return INTEG_PATTERN.sub(replace_integ, expression)
    
    def _process_db(self, expression: str) -> str:
        """处理 dB 转换"""
        def replace_db(match):
            inner = match.group(1)
            return f"(20 * log10(abs({inner})))"
        
        return DB_PATTERN.sub(replace_db, expression)
    
    def _process_phase(self, expression: str) -> str:
        """处理相位运算"""
        def replace_phase(match):
            inner = match.group(1)
            # 返回角度（度）
            return f"(angle({inner}) * 180 / pi)"
        
        return PHASE_PATTERN.sub(replace_phase, expression)
    
    def _get_x_axis(self, result: SimulationResult) -> Optional[np.ndarray]:
        """获取 X 轴数据"""
        if result.data is None:
            return None
        if result.data.time is not None:
            return result.data.time
        if result.data.frequency is not None:
            return result.data.frequency
        return None


# ============================================================
# 模块级单例
# ============================================================

waveform_math_service = WaveformMathService()
"""模块级单例实例"""


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 数据类
    "MathErrorCode",
    "MathResult",
    "PresetOperation",
    # 服务类
    "WaveformMathService",
    # 预设运算
    "PRESET_OPERATIONS",
    # 单例
    "waveform_math_service",
]
