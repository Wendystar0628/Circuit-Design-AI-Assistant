# Context Formatter - Context Data Formatting
"""
上下文格式化器 - 将各种上下文数据格式化为 Prompt 可用的文本

职责：
- 格式化诊断信息
- 格式化隐式上下文
- 格式化依赖文件
- 格式化对话历史等

使用示例：
    from domain.llm.prompt_building.context_formatter import ContextFormatter
    
    formatter = ContextFormatter()
    text = formatter.format_diagnostics(diagnostics)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from domain.llm.prompt_building.file_content_processor import FileContentProcessor


# ============================================================
# ContextFormatter 类
# ============================================================

class ContextFormatter:
    """
    上下文格式化器
    
    职责：
    - 将各种上下文数据格式化为 Prompt 可用的文本
    - 使用统一的 Markdown 格式
    """
    
    def __init__(self):
        """初始化格式化器"""
        self._logger = logging.getLogger(__name__)
        self._file_processor = FileContentProcessor()
    
    def format_diagnostics(self, diagnostics: Any) -> str:
        """
        格式化诊断信息
        
        Args:
            diagnostics: 诊断信息对象
            
        Returns:
            格式化后的文本
        """
        if not diagnostics:
            return ""
        
        parts = ["## Diagnostics"]
        
        # 语法错误
        if hasattr(diagnostics, 'syntax_errors') and diagnostics.syntax_errors:
            parts.append("\n### Syntax Errors")
            for err in diagnostics.syntax_errors:
                if hasattr(err, 'message'):
                    parts.append(f"- {err.message}")
                    if hasattr(err, 'line') and err.line:
                        context = err.context if hasattr(err, 'context') else ''
                        parts.append(f"  Line {err.line}: {context}")
                else:
                    parts.append(f"- {err}")
        
        # 仿真错误
        if hasattr(diagnostics, 'simulation_errors') and diagnostics.simulation_errors:
            parts.append("\n### Simulation Errors")
            for err in diagnostics.simulation_errors:
                if hasattr(err, 'message'):
                    parts.append(f"- {err.message}")
                else:
                    parts.append(f"- {err}")
        
        # 警告
        if hasattr(diagnostics, 'warnings') and diagnostics.warnings:
            parts.append("\n### Warnings")
            for warn in diagnostics.warnings:
                if hasattr(warn, 'message'):
                    parts.append(f"- {warn.message}")
                else:
                    parts.append(f"- {warn}")
        
        # 历史错误摘要
        if hasattr(diagnostics, 'error_history') and diagnostics.error_history:
            parts.append("\n### Error History")
            for hist in diagnostics.error_history[:3]:  # 最多3条
                parts.append(f"- {hist}")
        
        return "\n".join(parts)
    
    def format_implicit_context(self, implicit: Any) -> str:
        """
        格式化隐式上下文
        
        Args:
            implicit: 隐式上下文对象
            
        Returns:
            格式化后的文本
        """
        if not implicit:
            return ""
        
        parts = ["## Current Context"]
        
        # 当前电路文件
        if hasattr(implicit, 'current_circuit_content') and implicit.current_circuit_content:
            parts.append("\n### Current Circuit")
            if hasattr(implicit, 'current_circuit_file'):
                parts.append(f"File: {implicit.current_circuit_file}")
            parts.append("```spice")
            parts.append(implicit.current_circuit_content)
            parts.append("```")
        
        # 仿真结果
        if hasattr(implicit, 'simulation_result') and implicit.simulation_result:
            parts.append("\n### Latest Simulation Result")
            if isinstance(implicit.simulation_result, dict):
                parts.append(json.dumps(implicit.simulation_result, indent=2, ensure_ascii=False))
            else:
                parts.append(str(implicit.simulation_result))
        
        # 设计目标
        if hasattr(implicit, 'design_goals') and implicit.design_goals:
            parts.append("\n### Design Goals")
            if isinstance(implicit.design_goals, dict):
                parts.append(json.dumps(implicit.design_goals, indent=2, ensure_ascii=False))
            else:
                parts.append(str(implicit.design_goals))
        
        return "\n".join(parts)
    
    def format_dependencies(self, dependencies: List[Dict[str, Any]]) -> str:
        """
        格式化依赖文件
        
        Args:
            dependencies: 依赖文件列表
            
        Returns:
            格式化后的文本
        """
        if not dependencies:
            return ""
        
        parts = ["## Dependency Files"]
        
        for dep in dependencies:
            path = dep.get("path", "unknown")
            content = dep.get("content", "")
            depth = dep.get("depth", 1)
            
            parts.append(f"\n### {path} (depth: {depth})")
            if content:
                parts.append("```spice")
                parts.append(content)
                parts.append("```")
        
        return "\n".join(parts)
    
    def format_summary(self, summary: Any) -> str:
        """
        格式化结构化摘要
        
        Args:
            summary: 结构化摘要
            
        Returns:
            格式化后的文本
        """
        if not summary:
            return ""
        
        parts = ["## Conversation Summary"]
        
        if isinstance(summary, dict):
            for key, value in summary.items():
                if value:
                    parts.append(f"\n### {key.replace('_', ' ').title()}")
                    if isinstance(value, (dict, list)):
                        parts.append(json.dumps(value, indent=2, ensure_ascii=False))
                    else:
                        parts.append(str(value))
        else:
            parts.append(str(summary))
        
        return "\n".join(parts)
    
    def format_rag_results(self, results: List[Dict[str, Any]]) -> str:
        """
        格式化 RAG 检索结果
        
        Args:
            results: RAG 检索结果列表
            
        Returns:
            格式化后的文本
        """
        if not results:
            return ""
        
        parts = ["## Related Context"]
        
        for result in results:
            path = result.get("path", "")
            content = result.get("content", "")
            source = result.get("source", "")
            relevance = result.get("relevance", 0)
            
            parts.append(f"\n### {path}")
            parts.append(f"Source: {source}, Relevance: {relevance:.2f}")
            if content:
                parts.append(content)
        
        return "\n".join(parts)
    
    def format_web_search(self, results: List[Dict[str, Any]]) -> str:
        """
        格式化联网搜索结果
        
        Args:
            results: 搜索结果列表
            
        Returns:
            格式化后的文本
        """
        if not results:
            return ""
        
        parts = ["## Web Search Results"]
        
        for i, result in enumerate(results[:5], 1):  # 最多5条
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            url = result.get("url", "")
            
            parts.append(f"\n### {i}. {title}")
            if snippet:
                parts.append(snippet)
            if url:
                parts.append(f"Source: {url}")
        
        return "\n".join(parts)
    
    def format_conversation(self, messages: List[Any]) -> str:
        """
        格式化对话历史
        
        Args:
            messages: 消息列表
            
        Returns:
            格式化后的文本
        """
        if not messages:
            return ""
        
        parts = ["## Conversation History"]
        
        for msg in messages:
            if hasattr(msg, 'role'):
                role = msg.role.upper()
                content = msg.content if hasattr(msg, 'content') else str(msg)
            elif isinstance(msg, dict):
                role = msg.get("role", "unknown").upper()
                content = msg.get("content", "")
            else:
                continue
            
            parts.append(f"\n**{role}**: {content}")
        
        return "\n".join(parts)
    
    def format_user_files(
        self,
        files: List[Dict[str, Any]],
        budget: int
    ) -> str:
        """
        格式化用户手动选择的文件
        
        Args:
            files: 文件列表
            budget: Token 预算
            
        Returns:
            格式化后的文本
        """
        if not files:
            return ""
        
        parts = ["## User Selected Files"]
        remaining_budget = budget
        
        for file_info in files:
            path = file_info.get("path", "")
            content = file_info.get("content", "")
            
            # 使用文件处理器处理内容
            processed_content = self._file_processor.process_file(
                content, path, remaining_budget // max(1, len(files))
            )
            
            parts.append(f"\n### {path}")
            parts.append("```")
            parts.append(processed_content)
            parts.append("```")
            
            from domain.llm.token_counter import count_tokens
            remaining_budget -= count_tokens(processed_content)
            
            if remaining_budget <= 0:
                parts.append("\n(Additional files truncated due to budget)")
                break
        
        return "\n".join(parts)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ContextFormatter",
]
