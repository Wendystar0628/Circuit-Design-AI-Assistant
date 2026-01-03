# Diagnostics Collector - Collect Circuit Diagnostics Information
"""
诊断信息收集器 - 收集电路文件的诊断信息

职责：
- 收集电路文件的诊断信息（语法错误、仿真错误、警告）
- 让 LLM 了解当前问题状态
- 维护错误历史记录

诊断信息来源（遵循 Reference-Based 原则）：
- 语法检查：在用户发送消息前，对当前电路文件运行轻量语法检查
- 仿真错误：从 CollectionContext.error_context 读取（轻量摘要）
- 历史错误关联：如果当前电路之前仿真失败过，注入历史错误摘要
- 警告信息：浮空节点、未使用的子电路等非致命问题

实现协议：ContextSource
优先级：ContextPriority.CRITICAL（0）- 诊断信息优先级最高
被调用方：implicit_context_aggregator.py
"""

import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.llm.context_retrieval.context_source_protocol import (
    CollectionContext,
    ContextPriority,
    ContextResult,
)


# ============================================================
# 常量定义
# ============================================================

# 语法缓存最大条目数
MAX_SYNTAX_CACHE_ENTRIES = 100

# 错误历史最大条目数（每个文件）
MAX_ERROR_HISTORY_PER_FILE = 10

# 错误上下文行数（±N 行）
ERROR_CONTEXT_LINES = 5

# 错误消息最大长度
MAX_ERROR_MESSAGE_LENGTH = 200


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class ErrorRecord:
    """错误记录"""
    timestamp: float
    error_type: str  # "syntax" | "simulation" | "warning"
    message: str
    command: Optional[str] = None


@dataclass
class DiagnosticItem:
    """单条诊断项"""
    type: str  # "syntax" | "simulation" | "warning"
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    context_lines: Optional[str] = None


# ============================================================
# 诊断信息收集器
# ============================================================

class DiagnosticsCollector:
    """
    诊断信息收集器
    
    实现 ContextSource 协议，收集电路文件的诊断信息。
    """

    def __init__(self):
        # 语法检查缓存：{file_path: (mtime, List[DiagnosticItem])}
        self._syntax_cache: OrderedDict[str, Tuple[float, List[DiagnosticItem]]] = (
            OrderedDict()
        )
        
        # 错误历史：{circuit_file_path: List[ErrorRecord]}
        self._error_history: Dict[str, List[ErrorRecord]] = {}
        
        # 延迟获取的服务
        self._logger = None
        self._async_file_ops = None

    # ============================================================
    # 服务获取
    # ============================================================

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

    @property
    def async_file_ops(self):
        """延迟获取异步文件操作服务"""
        if self._async_file_ops is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_ASYNC_FILE_OPS
                self._async_file_ops = ServiceLocator.get_optional(SVC_ASYNC_FILE_OPS)
            except Exception:
                pass
        return self._async_file_ops

    # ============================================================
    # ContextSource 协议实现
    # ============================================================

    async def collect_async(self, context: CollectionContext) -> ContextResult:
        """
        异步收集所有诊断信息
        
        Args:
            context: 收集上下文
            
        Returns:
            ContextResult: 收集结果
        """
        source_name = self.get_source_name()
        diagnostics: List[DiagnosticItem] = []
        
        # 1. 语法检查
        if context.circuit_file_path:
            file_path = Path(context.project_path) / context.circuit_file_path
            if file_path.exists():
                syntax_errors = await self._check_syntax_async(file_path)
                diagnostics.extend(syntax_errors)
        
        # 2. 仿真错误（从 error_context 读取）
        if context.error_context:
            sim_error = DiagnosticItem(
                type="simulation",
                message=context.error_context,
            )
            diagnostics.append(sim_error)
        
        # 3. 获取历史错误
        history: List[ErrorRecord] = []
        if context.circuit_file_path:
            history = self._get_error_history(context.circuit_file_path)
        
        # 如果没有任何诊断信息，返回空结果
        if not diagnostics and not history:
            return ContextResult.empty(source_name)
        
        # 格式化为 Prompt 文本
        formatted_content = self._format_diagnostics_for_prompt(diagnostics, history)
        
        # 估算 Token 数
        token_count = self._estimate_tokens(formatted_content)
        
        # 构建元数据
        metadata = {
            "syntax_error_count": sum(1 for d in diagnostics if d.type == "syntax"),
            "simulation_error_count": sum(1 for d in diagnostics if d.type == "simulation"),
            "warning_count": sum(1 for d in diagnostics if d.type == "warning"),
            "history_count": len(history),
        }
        
        return ContextResult(
            content=formatted_content,
            token_count=token_count,
            source_name=source_name,
            priority=self.get_priority(),
            metadata=metadata,
        )

    def get_priority(self) -> ContextPriority:
        """获取优先级 - 诊断信息优先级最高"""
        return ContextPriority.CRITICAL

    def get_source_name(self) -> str:
        """获取源名称"""
        return "diagnostics"

    # ============================================================
    # 语法检查
    # ============================================================

    async def _check_syntax_async(self, file_path: Path) -> List[DiagnosticItem]:
        """
        异步执行语法检查
        
        Args:
            file_path: 电路文件路径
            
        Returns:
            List[DiagnosticItem]: 语法错误列表
        """
        import asyncio
        
        # 检查缓存
        cache_key = str(file_path)
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            return []
        
        cached = self._syntax_cache.get(cache_key)
        if cached and cached[0] == mtime:
            # 移动到末尾（LRU）
            self._syntax_cache.move_to_end(cache_key)
            return cached[1]
        
        # 异步读取文件内容
        try:
            if self.async_file_ops:
                content = await self.async_file_ops.read_file_async(str(file_path))
            else:
                content = await asyncio.to_thread(
                    lambda: file_path.read_text(encoding="utf-8", errors="ignore")
                )
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to read file for syntax check: {e}")
            return []
        
        # 执行语法检查
        errors = self._perform_syntax_check(content, str(file_path))
        
        # 异步加载错误上下文
        for error in errors:
            if error.line and not error.context_lines:
                error.context_lines = await self._load_error_context_async(
                    file_path, error.line
                )
        
        # 更新缓存
        self._syntax_cache[cache_key] = (mtime, errors)
        self._syntax_cache.move_to_end(cache_key)
        
        # LRU 淘汰
        while len(self._syntax_cache) > MAX_SYNTAX_CACHE_ENTRIES:
            self._syntax_cache.popitem(last=False)
        
        return errors

    def _perform_syntax_check(
        self, content: str, file_path: str
    ) -> List[DiagnosticItem]:
        """
        执行语法检查
        
        Args:
            content: 文件内容
            file_path: 文件路径
            
        Returns:
            List[DiagnosticItem]: 语法错误列表
        """
        errors: List[DiagnosticItem] = []
        lines = content.split("\n")
        subckt_stack: List[Tuple[str, int]] = []  # (name, line_number)
        
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
                    message="Unclosed quote detected",
                    file=file_path,
                    line=i,
                ))
            
            # 检查 .subckt 开始
            if line_lower.startswith(".subckt"):
                match = re.match(r"\.subckt\s+(\w+)", line_lower)
                if match:
                    subckt_stack.append((match.group(1), i))
            
            # 检查 .ends 结束
            elif line_lower.startswith(".ends"):
                if not subckt_stack:
                    errors.append(DiagnosticItem(
                        type="syntax",
                        message=".ends without matching .subckt",
                        file=file_path,
                        line=i,
                    ))
                else:
                    subckt_stack.pop()
            
            # 检查节点名格式（数字开头警告）
            if line_lower.startswith(("r", "c", "l", "v", "i", "e", "f", "g", "h")):
                # 器件行，检查节点名
                parts = line_stripped.split()
                if len(parts) >= 3:
                    for node in parts[1:3]:
                        if node and node[0].isdigit() and node != "0":
                            errors.append(DiagnosticItem(
                                type="warning",
                                message=f"Node name '{node}' starts with digit (may cause issues)",
                                file=file_path,
                                line=i,
                            ))
                            break
        
        # 检查未闭合的 .subckt
        for name, line_num in subckt_stack:
            errors.append(DiagnosticItem(
                type="syntax",
                message=f".subckt {name} without matching .ends",
                file=file_path,
                line=line_num,
            ))
        
        return errors


    async def _load_error_context_async(
        self, file_path: Path, line: int
    ) -> str:
        """
        异步加载错误行上下文（±5行）
        
        Args:
            file_path: 文件路径
            line: 错误行号
            
        Returns:
            str: 上下文代码片段
        """
        import asyncio
        
        try:
            if self.async_file_ops:
                content = await self.async_file_ops.read_file_async(str(file_path))
            else:
                content = await asyncio.to_thread(
                    lambda: file_path.read_text(encoding="utf-8", errors="ignore")
                )
            
            lines = content.split("\n")
            total_lines = len(lines)
            
            # 计算上下文范围
            start = max(0, line - ERROR_CONTEXT_LINES - 1)
            end = min(total_lines, line + ERROR_CONTEXT_LINES)
            
            # 构建带行号的上下文
            context_parts = []
            for i in range(start, end):
                line_num = i + 1
                marker = ">>>" if line_num == line else "   "
                context_parts.append(f"{marker} {line_num:4d} | {lines[i]}")
            
            return "\n".join(context_parts)
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Failed to load error context: {e}")
            return ""

    # ============================================================
    # 格式化输出
    # ============================================================

    def _format_diagnostics_for_prompt(
        self,
        diagnostics: List[DiagnosticItem],
        history: List[ErrorRecord],
    ) -> str:
        """
        格式化诊断信息为 Prompt 友好的文本
        
        Args:
            diagnostics: 诊断项列表
            history: 历史错误记录
            
        Returns:
            str: 格式化的文本
        """
        lines = ["=== Circuit Diagnostics ==="]
        
        # 分类诊断项
        syntax_errors = [d for d in diagnostics if d.type == "syntax"]
        sim_errors = [d for d in diagnostics if d.type == "simulation"]
        warnings = [d for d in diagnostics if d.type == "warning"]
        
        # 语法错误（最高优先级）
        if syntax_errors:
            lines.append("")
            lines.append("SYNTAX ERRORS (must fix before simulation):")
            for error in syntax_errors:
                lines.append(self._format_diagnostic_item(error))
        
        # 仿真错误
        if sim_errors:
            lines.append("")
            lines.append("SIMULATION ERRORS:")
            for error in sim_errors:
                lines.append(self._format_diagnostic_item(error))
        
        # 警告
        if warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for warning in warnings:
                lines.append(self._format_diagnostic_item(warning))
        
        # 历史错误
        if history:
            lines.append("")
            lines.append("RECENT ERROR HISTORY (for context):")
            for record in history[-3:]:  # 最近 3 条
                timestamp_str = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(record.timestamp)
                )
                lines.append(f"  [{timestamp_str}] {record.error_type}: {record.message}")
                if record.command:
                    lines.append(f"    Command: {record.command}")
        
        # 添加总结
        total_errors = len(syntax_errors) + len(sim_errors)
        if total_errors > 0:
            lines.append("")
            lines.append(f"Total: {total_errors} error(s), {len(warnings)} warning(s)")
            lines.append("Please address these issues before proceeding.")
        
        return "\n".join(lines)

    def _format_diagnostic_item(self, item: DiagnosticItem) -> str:
        """格式化单个诊断项"""
        parts = [f"  - {item.message}"]
        
        if item.file and item.line:
            file_name = Path(item.file).name
            parts.append(f"    Location: {file_name}:{item.line}")
        elif item.file:
            file_name = Path(item.file).name
            parts.append(f"    File: {file_name}")
        
        if item.context_lines:
            parts.append("    Context:")
            for ctx_line in item.context_lines.split("\n"):
                parts.append(f"      {ctx_line}")
        
        return "\n".join(parts)

    # ============================================================
    # 错误历史管理
    # ============================================================

    def _get_error_history(self, circuit_file: str) -> List[ErrorRecord]:
        """
        获取历史错误记录
        
        Args:
            circuit_file: 电路文件路径
            
        Returns:
            List[ErrorRecord]: 历史错误记录（最近 3 条）
        """
        history = self._error_history.get(circuit_file, [])
        return history[-3:]

    def record_error(
        self,
        circuit_file: str,
        error_type: str,
        message: str,
        command: Optional[str] = None,
    ) -> None:
        """
        记录错误到历史
        
        Args:
            circuit_file: 电路文件路径
            error_type: 错误类型
            message: 错误消息
            command: 失败的仿真命令（可选）
        """
        record = ErrorRecord(
            timestamp=time.time(),
            error_type=error_type,
            message=message[:MAX_ERROR_MESSAGE_LENGTH],
            command=command,
        )
        
        if circuit_file not in self._error_history:
            self._error_history[circuit_file] = []
        
        self._error_history[circuit_file].append(record)
        
        # 限制历史记录数量
        if len(self._error_history[circuit_file]) > MAX_ERROR_HISTORY_PER_FILE:
            self._error_history[circuit_file] = (
                self._error_history[circuit_file][-MAX_ERROR_HISTORY_PER_FILE:]
            )
        
        if self.logger:
            self.logger.debug(f"Recorded error for {circuit_file}: {error_type}")

    def clear_error_history(self, circuit_file: str) -> None:
        """
        仿真成功后清除历史
        
        Args:
            circuit_file: 电路文件路径
        """
        if circuit_file in self._error_history:
            del self._error_history[circuit_file]
            if self.logger:
                self.logger.debug(f"Cleared error history for {circuit_file}")

    # ============================================================
    # 辅助方法
    # ============================================================

    def _estimate_tokens(self, text: str) -> int:
        """估算 Token 数"""
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            return len(text) // 4

    def invalidate_syntax_cache(self, file_path: str) -> None:
        """
        使语法缓存失效
        
        Args:
            file_path: 文件路径
        """
        if file_path in self._syntax_cache:
            del self._syntax_cache[file_path]

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "syntax_cache_size": len(self._syntax_cache),
            "error_history_files": len(self._error_history),
            "total_history_records": sum(
                len(records) for records in self._error_history.values()
            ),
        }


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "DiagnosticsCollector",
    "DiagnosticItem",
    "ErrorRecord",
    "MAX_SYNTAX_CACHE_ENTRIES",
    "MAX_ERROR_HISTORY_PER_FILE",
    "ERROR_CONTEXT_LINES",
]
