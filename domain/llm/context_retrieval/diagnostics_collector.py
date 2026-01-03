# Diagnostics Collector
"""
诊断信息收集器 - 收集电路文件的诊断信息

职责：
- 收集电路文件的诊断信息（语法错误、仿真错误、警告）
- 让 LLM 了解当前问题状态
- 维护错误历史记录

诊断信息来源：
- 语法检查：在用户发送消息前，对当前电路文件运行轻量语法检查
- 仿真错误：GraphState.last_simulation_error 存在且非空时注入
- 历史错误关联：如果当前电路之前仿真失败过，注入历史错误摘要
- 警告信息：浮空节点、未使用的子电路等非致命问题

优先级：诊断信息优先级最高，确保 LLM 能看到完整问题描述
被调用方：context_retriever.py
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DiagnosticItem:
    """诊断项"""
    type: str           # "syntax" | "simulation" | "warning"
    message: str        # 错误/警告消息
    file: Optional[str] = None
    line: Optional[int] = None
    context: Optional[str] = None  # 错误行附近的代码片段


@dataclass
class Diagnostics:
    """诊断信息集合"""
    syntax_errors: List[DiagnosticItem] = field(default_factory=list)
    simulation_errors: List[DiagnosticItem] = field(default_factory=list)
    warnings: List[DiagnosticItem] = field(default_factory=list)
    error_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def is_empty(self) -> bool:
        """检查是否没有任何诊断信息"""
        return (
            not self.syntax_errors and 
            not self.simulation_errors and 
            not self.warnings and 
            not self.error_history
        )



class DiagnosticsCollector:
    """
    诊断信息收集器
    
    收集电路文件的诊断信息，让 LLM 了解当前问题状态。
    """

    # 错误历史：{circuit_file_path: [error_records]}
    _error_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    # 语法检查缓存：{file_path: (mtime, errors)}
    _syntax_cache: Dict[str, tuple] = {}

    def __init__(self):
        self._session_state = None
        self._logger = None

    # ============================================================
    # 服务获取
    # ============================================================

    @property
    def session_state(self):
        """延迟获取会话状态（只读）"""
        if self._session_state is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE
                self._session_state = ServiceLocator.get_optional(SVC_SESSION_STATE)
            except Exception:
                pass
        return self._session_state

    @property
    def logger(self):
        """延迟获取日志器"""
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("diagnostics_collector")
            except Exception:
                pass
        return self._logger

    # ============================================================
    # 主入口
    # ============================================================

    def collect(
        self,
        project_path: str,
        circuit_file: Optional[str] = None,
    ) -> Diagnostics:
        """
        收集所有诊断信息
        
        Args:
            project_path: 项目路径
            circuit_file: 当前电路文件路径（可选）
            
        Returns:
            Diagnostics: 诊断信息集合
        """
        diagnostics = Diagnostics()
        project_dir = Path(project_path)
        
        # 获取语法错误
        if circuit_file:
            syntax_errors = self.get_syntax_errors(circuit_file)
            diagnostics.syntax_errors = syntax_errors
        
        # 获取仿真错误
        sim_errors = self.get_simulation_errors()
        diagnostics.simulation_errors = sim_errors
        
        # 获取警告信息
        warnings = self.get_warning_messages()
        diagnostics.warnings = warnings
        
        # 获取历史错误关联
        if circuit_file:
            error_history = self.get_error_history(circuit_file)
            diagnostics.error_history = error_history
        
        return diagnostics


    # ============================================================
    # 语法检查
    # ============================================================

    def get_syntax_errors(self, circuit_file: str) -> List[DiagnosticItem]:
        """
        获取语法检查结果
        
        触发时机：
        - 用户发送消息时自动执行（异步，不阻塞 UI）
        - 文件保存后 500ms 延迟执行（防抖）
        - 检查结果缓存，文件未修改时复用
        """
        errors = []
        file_path = Path(circuit_file)
        
        if not file_path.exists():
            return errors
        
        # 检查缓存
        mtime = file_path.stat().st_mtime
        cached = self._syntax_cache.get(circuit_file)
        if cached and cached[0] == mtime:
            return cached[1]
        
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            
            # 基础语法检查
            errors = self._check_basic_syntax(lines, circuit_file)
            
            # 缓存结果
            self._syntax_cache[circuit_file] = (mtime, errors)
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Syntax check failed: {e}")
        
        return errors

    def _check_basic_syntax(
        self, lines: List[str], file_path: str
    ) -> List[DiagnosticItem]:
        """基础语法检查"""
        errors = []
        subckt_stack = []  # 跟踪 .subckt/.ends 配对
        
        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()
            
            # 跳过空行和注释
            if not line_stripped or line_stripped.startswith("*"):
                continue
            
            line_lower = line_stripped.lower()
            
            # 检查未闭合的引号
            if line_stripped.count('"') % 2 != 0:
                errors.append(DiagnosticItem(
                    type="syntax",
                    message="未闭合的引号",
                    file=file_path,
                    line=i,
                    context=line_stripped[:60],
                ))
            
            # 检查 .subckt 开始
            if line_lower.startswith(".subckt"):
                match = re.match(r'\.subckt\s+(\w+)', line_lower)
                if match:
                    subckt_stack.append((match.group(1), i))
            
            # 检查 .ends 结束
            elif line_lower.startswith(".ends"):
                if not subckt_stack:
                    errors.append(DiagnosticItem(
                        type="syntax",
                        message=".ends 没有匹配的 .subckt",
                        file=file_path,
                        line=i,
                        context=line_stripped[:60],
                    ))
                else:
                    subckt_stack.pop()
        
        # 检查未闭合的 .subckt
        for name, line_num in subckt_stack:
            errors.append(DiagnosticItem(
                type="syntax",
                message=f".subckt {name} 没有对应的 .ends",
                file=file_path,
                line=line_num,
            ))
        
        return errors


    # ============================================================
    # 仿真错误
    # ============================================================

    def get_simulation_errors(self) -> List[DiagnosticItem]:
        """
        获取仿真错误信息
        
        仿真错误注入内容：
        - PySpice 错误堆栈信息
        - 失败的仿真命令
        - 相关的电路文件片段（错误行附近 ±5 行）
        - ngspice 原始输出（如有）
        """
        errors = []
        
        if self.session_state:
            last_error = self.session_state.error_context
            if last_error:
                errors.append(DiagnosticItem(
                    type="simulation",
                    message=str(last_error),
                ))
        
        return errors

    def get_warning_messages(self) -> List[DiagnosticItem]:
        """
        获取警告信息
        
        警告类型：浮空节点、未使用的子电路等非致命问题
        """
        # TODO: 警告信息收集待实现
        # 目前返回空列表，待后续从 GraphState 或日志中收集
        return []

    # ============================================================
    # 错误历史管理
    # ============================================================

    def get_error_history(self, circuit_file: str) -> List[Dict[str, Any]]:
        """
        获取历史错误关联
        
        维护 error_history 字典，记录最近 3 次仿真失败的错误类型和简要描述。
        当同一电路再次讨论时，注入历史错误摘要。
        """
        history = self._error_history.get(circuit_file, [])
        return history[-3:]  # 最近 3 次

    def record_error(self, circuit_file: str, error: str):
        """
        记录错误到历史
        
        Args:
            circuit_file: 电路文件路径
            error: 错误信息
        """
        import time
        
        record = {
            "timestamp": time.time(),
            "error": error[:200],  # 截断过长的错误信息
        }
        
        self._error_history[circuit_file].append(record)
        
        # 只保留最近 10 条
        if len(self._error_history[circuit_file]) > 10:
            self._error_history[circuit_file] = self._error_history[circuit_file][-10:]

    def clear_error_history(self, circuit_file: str):
        """
        仿真成功后清除历史
        
        Args:
            circuit_file: 电路文件路径
        """
        if circuit_file in self._error_history:
            del self._error_history[circuit_file]

    # ============================================================
    # 辅助方法
    # ============================================================

    def to_dict(self, diagnostics: Diagnostics) -> Dict[str, Any]:
        """将 Diagnostics 转换为字典"""
        return {
            "syntax_errors": [
                {"type": e.type, "message": e.message, "file": e.file, 
                 "line": e.line, "context": e.context}
                for e in diagnostics.syntax_errors
            ],
            "simulation_errors": [
                {"type": e.type, "message": e.message}
                for e in diagnostics.simulation_errors
            ],
            "warnings": [
                {"type": e.type, "message": e.message}
                for e in diagnostics.warnings
            ],
            "error_history": diagnostics.error_history,
        }

    def has_errors(self, diagnostics: Diagnostics) -> bool:
        """检查是否有错误"""
        return bool(diagnostics.syntax_errors or diagnostics.simulation_errors)


__all__ = ["DiagnosticsCollector", "Diagnostics", "DiagnosticItem"]
