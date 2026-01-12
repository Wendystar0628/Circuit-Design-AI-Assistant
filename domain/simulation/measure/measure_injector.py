# Measure Injector
"""
.MEASURE 语句注入器

将 .MEASURE 语句注入到 SPICE 网表中。

使用示例：
    injector = MeasureInjector()
    
    measures = [
        ".MEASURE AC gain_db MAX VDB(out)",
        ".MEASURE AC f_3db WHEN VDB(out)=par('gain_db-3') FALL=1",
    ]
    
    # 先验证语法
    errors = injector.validate_measures(measures)
    if errors:
        for stmt, err in errors:
            print(f"语法错误: {err}")
            print(f"  语句: {stmt}")
    else:
        modified_netlist = injector.inject_measures(original_netlist, measures)
    
注意：
    - ngspice 中引用其他测量结果需要使用 par('expr') 语法
    - 不要使用引号直接包裹表达式，如 VDB(out)='gain_db-3' 是错误的
    - 幂运算使用 pwr(base, exp) 而不是 ^ 符号
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class MeasureValidationError:
    """MEASURE 语句验证错误"""
    statement: str
    error_type: str
    message: str
    suggestion: str


class MeasureInjector:
    """
    .MEASURE 语句注入器
    
    将 LLM 生成的 .MEASURE 语句注入到 SPICE 网表中。
    注入前必须通过验证，不会自动修正语法错误。
    """
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
    def inject_measures(
        self,
        netlist: str,
        measures: List[str],
        position: str = "before_end",
    ) -> Tuple[str, List[MeasureValidationError]]:
        """
        将 .MEASURE 语句注入到网表中
        
        注入前会进行语法验证，如果存在错误则不注入并返回错误列表。
        
        Args:
            netlist: 原始网表内容
            measures: .MEASURE 语句列表
            position: 注入位置
                - "before_end": 在 .END 语句之前（默认）
                - "after_analysis": 在分析语句之后
                
        Returns:
            Tuple[str, List[MeasureValidationError]]: 
                - 修改后的网表内容（如果有错误则返回原网表）
                - 验证错误列表（空列表表示无错误）
        """
        if not measures:
            return netlist, []
        
        # 过滤空语句和注释
        valid_measures = [
            m.strip() for m in measures
            if m.strip() and not m.strip().startswith("*")
        ]
        
        if not valid_measures:
            return netlist, []
        
        # 验证所有语句
        errors = self.validate_measures(valid_measures)
        if errors:
            # 存在错误，不注入，返回原网表和错误列表
            return netlist, errors
        
        # 处理每个语句
        normalized_measures = []
        for m in valid_measures:
            # 处理续行（+ 开头的行）
            m = self._join_continuation_lines(m)
            
            if not m.upper().startswith(".MEASURE"):
                continue
            
            normalized_measures.append(m)
        
        if not normalized_measures:
            return netlist, []
        
        # 构建注入块
        measure_block = "\n* === LLM Generated Measurements ===\n"
        measure_block += "\n".join(normalized_measures)
        measure_block += "\n* === End Measurements ===\n"
        
        # 根据位置注入
        if position == "before_end":
            return self._inject_before_end(netlist, measure_block), []
        elif position == "after_analysis":
            return self._inject_after_analysis(netlist, measure_block), []
        else:
            self._logger.warning(
                f"Unknown injection position: {position}, using before_end"
            )
            return self._inject_before_end(netlist, measure_block), []
    
    def validate_measures(
        self, measures: List[str]
    ) -> List[MeasureValidationError]:
        """
        验证多个 .MEASURE 语句的语法
        
        Args:
            measures: .MEASURE 语句列表
            
        Returns:
            List[MeasureValidationError]: 验证错误列表，空列表表示全部通过
        """
        errors = []
        for stmt in measures:
            stmt = stmt.strip()
            if not stmt or stmt.startswith("*"):
                continue
            
            # 处理续行
            stmt = self._join_continuation_lines(stmt)
            
            validation_errors = self._validate_single_measure(stmt)
            errors.extend(validation_errors)
        
        return errors
    
    def _validate_single_measure(
        self, statement: str
    ) -> List[MeasureValidationError]:
        """
        验证单个 .MEASURE 语句的语法
        
        Args:
            statement: .MEASURE 语句
            
        Returns:
            List[MeasureValidationError]: 验证错误列表
        """
        errors = []
        statement = statement.strip()
        
        # 检查是否以 .MEASURE 开头
        if not statement.upper().startswith(".MEASURE"):
            errors.append(MeasureValidationError(
                statement=statement,
                error_type="INVALID_PREFIX",
                message="语句必须以 .MEASURE 开头",
                suggestion="请确保语句格式为: .MEASURE <type> <name> <measurement>",
            ))
            return errors
        
        parts = statement.split()
        
        # 检查语句完整性
        if len(parts) < 4:
            errors.append(MeasureValidationError(
                statement=statement,
                error_type="INCOMPLETE_STATEMENT",
                message="语句格式不完整",
                suggestion="完整格式: .MEASURE <type> <name> <measurement>，"
                          "例如: .MEASURE AC gain_db MAX VDB(out)",
            ))
            return errors
        
        # 检查分析类型
        analysis_type = parts[1].upper()
        valid_types = {"AC", "DC", "TRAN", "OP", "NOISE"}
        if analysis_type not in valid_types:
            errors.append(MeasureValidationError(
                statement=statement,
                error_type="INVALID_ANALYSIS_TYPE",
                message=f"无效的分析类型 '{parts[1]}'",
                suggestion=f"有效的分析类型: {', '.join(sorted(valid_types))}",
            ))
        
        # 检查错误1：使用引号直接包裹表达式（应使用 par()）
        # 匹配 ='expr' 或 ="expr" 但不是 =par('expr')
        quote_pattern = re.compile(r"=\s*['\"]([^'\"]+)['\"](?!\s*\))")
        quote_matches = quote_pattern.findall(statement)
        if quote_matches:
            for expr in quote_matches:
                errors.append(MeasureValidationError(
                    statement=statement,
                    error_type="INVALID_EXPRESSION_SYNTAX",
                    message=f"错误的表达式语法: ='{expr}'",
                    suggestion=f"引用其他测量结果或使用表达式时，应使用 par() 函数，"
                              f"正确写法: =par('{expr}')",
                ))
        
        # 检查错误2：使用 ^ 进行幂运算（ngspice 使用 pwr() 或 **）
        if "^" in statement:
            # 排除注释中的 ^
            code_part = statement.split("*")[0] if "*" in statement else statement
            if "^" in code_part:
                errors.append(MeasureValidationError(
                    statement=statement,
                    error_type="INVALID_POWER_OPERATOR",
                    message="ngspice 不支持 ^ 作为幂运算符",
                    suggestion="请使用 pwr(base, exp) 函数，"
                              "例如: 10^3 应改为 pwr(10,3)",
                ))
        
        # 检查错误3：PARAM 表达式未使用引号包裹
        param_pattern = re.compile(r"PARAM\s*=\s*([^'\"\s][^\s]*)", re.IGNORECASE)
        param_match = param_pattern.search(statement)
        if param_match:
            expr = param_match.group(1)
            # 如果表达式包含运算符，应该用引号包裹
            if any(op in expr for op in ["+", "-", "*", "/", "(", ")"]):
                errors.append(MeasureValidationError(
                    statement=statement,
                    error_type="PARAM_EXPRESSION_NOT_QUOTED",
                    message=f"PARAM 表达式应使用引号包裹: {expr}",
                    suggestion=f"正确写法: PARAM='{expr}'",
                ))
        
        # 检查错误4：WHEN 条件中的表达式包含运算符但未使用 par()
        when_pattern = re.compile(
            r"WHEN\s+\S+\s*=\s*([^'\"\s][^\s]*?)(?:\s+|$)", re.IGNORECASE
        )
        when_match = when_pattern.search(statement)
        if when_match:
            expr = when_match.group(1)
            # 如果表达式包含运算符且不是纯数字，应该用 par() 包裹
            if any(op in expr for op in ["+", "-", "*", "/"]):
                # 排除纯负数
                if not re.match(r"^-?\d+\.?\d*(?:[eE][-+]?\d+)?$", expr):
                    errors.append(MeasureValidationError(
                        statement=statement,
                        error_type="WHEN_EXPRESSION_NOT_WRAPPED",
                        message=f"WHEN 条件中的表达式应使用 par() 包裹: {expr}",
                        suggestion=f"正确写法: WHEN ...=par('{expr}')",
                    ))
        
        return errors
    
    def _join_continuation_lines(self, statement: str) -> str:
        """
        合并续行（处理 + 开头的行）
        
        SPICE 网表中，+ 开头的行表示上一行的续行
        """
        lines = statement.split("\n")
        if len(lines) <= 1:
            return statement
        
        result = lines[0]
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("+"):
                # 续行，去掉 + 号并合并
                result += " " + stripped[1:].strip()
            else:
                # 不是续行，保持原样
                result += "\n" + line
        
        return result
    
    def _inject_before_end(self, netlist: str, measure_block: str) -> str:
        """在 .END 语句之前注入"""
        # 查找 .END 语句
        end_pattern = re.compile(r"^\.END\s*$", re.MULTILINE | re.IGNORECASE)
        match = end_pattern.search(netlist)
        
        if match:
            # 在 .END 之前插入
            insert_pos = match.start()
            return (
                netlist[:insert_pos] + measure_block + "\n" + netlist[insert_pos:]
            )
        else:
            # 没有 .END，追加到末尾
            self._logger.warning(
                "No .END statement found, appending measures to end"
            )
            return netlist + "\n" + measure_block + "\n.END\n"
    
    def _inject_after_analysis(self, netlist: str, measure_block: str) -> str:
        """在分析语句之后注入"""
        # 查找最后一个分析语句（.AC, .DC, .TRAN, .OP, .NOISE 等）
        analysis_pattern = re.compile(
            r"^\.(AC|DC|TRAN|OP|NOISE|TF|SENS)\s+.*$",
            re.MULTILINE | re.IGNORECASE,
        )
        
        matches = list(analysis_pattern.finditer(netlist))
        
        if matches:
            # 在最后一个分析语句之后插入
            last_match = matches[-1]
            insert_pos = last_match.end()
            return (
                netlist[:insert_pos] + "\n" + measure_block + netlist[insert_pos:]
            )
        else:
            # 没有分析语句，使用 before_end
            self._logger.warning(
                "No analysis statement found, using before_end"
            )
            return self._inject_before_end(netlist, measure_block)
    
    def remove_measures(self, netlist: str) -> str:
        """
        从网表中移除已注入的 .MEASURE 语句
        
        Args:
            netlist: 网表内容
            
        Returns:
            str: 移除 .MEASURE 后的网表
        """
        # 移除 LLM 生成的测量块
        block_pattern = re.compile(
            r"\n?\* === LLM Generated Measurements ===\n"
            r".*?\n\* === End Measurements ===\n?",
            re.DOTALL,
        )
        netlist = block_pattern.sub("", netlist)
        
        # 移除所有 .MEASURE 语句（包括续行）
        lines = netlist.split("\n")
        result_lines = []
        skip_continuation = False
        
        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith(".MEASURE"):
                skip_continuation = True
                continue
            elif skip_continuation and stripped.startswith("+"):
                # 跳过续行
                continue
            else:
                skip_continuation = False
                result_lines.append(line)
        
        return "\n".join(result_lines)
    
    def extract_measures(self, netlist: str) -> List[str]:
        """
        从网表中提取现有的 .MEASURE 语句（包括续行）
        
        Args:
            netlist: 网表内容
            
        Returns:
            List[str]: .MEASURE 语句列表
        """
        measures = []
        lines = netlist.split("\n")
        current_measure = None
        
        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith(".MEASURE"):
                # 保存之前的测量语句
                if current_measure:
                    measures.append(current_measure)
                current_measure = stripped
            elif current_measure and stripped.startswith("+"):
                # 续行
                current_measure += " " + stripped[1:].strip()
            else:
                # 非测量语句，保存当前测量
                if current_measure:
                    measures.append(current_measure)
                    current_measure = None
        
        # 保存最后一个测量语句
        if current_measure:
            measures.append(current_measure)
        
        return measures
    
    def format_validation_errors(
        self, errors: List[MeasureValidationError]
    ) -> str:
        """
        格式化验证错误为用户友好的字符串
        
        Args:
            errors: 验证错误列表
            
        Returns:
            str: 格式化的错误信息
        """
        if not errors:
            return ""
        
        lines = [f"发现 {len(errors)} 个 .MEASURE 语法错误:\n"]
        
        for i, err in enumerate(errors, 1):
            lines.append(f"{i}. [{err.error_type}] {err.message}")
            lines.append(f"   语句: {err.statement}")
            lines.append(f"   建议: {err.suggestion}")
            lines.append("")
        
        return "\n".join(lines)


# 模块级单例
measure_injector = MeasureInjector()
