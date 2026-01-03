# Circuit File Collector - Collect Current Circuit File Content
"""
电路文件收集器 - 收集当前电路文件内容

职责：
- 收集当前电路文件内容
- 支持多种 SPICE 文件格式（.cir, .sp, .spice, .sub, .inc）
- 提取文件元数据（标题、描述、子电路列表）
- 添加行号标注便于 LLM 定位

实现协议：ContextSource
优先级：ContextPriority.HIGH（10）
被调用方：implicit_context_aggregator.py
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.context_retrieval.context_source_protocol import (
    CollectionContext,
    ContextPriority,
    ContextResult,
    ContextSource,
)


# ============================================================
# 常量定义
# ============================================================

# 支持的 SPICE 文件扩展名
SPICE_EXTENSIONS = {".cir", ".sp", ".spice", ".sub", ".inc"}

# 最大文件大小（字节）- 超过此大小的文件将被截断
MAX_FILE_SIZE = 50 * 1024  # 50KB

# 最大行数 - 超过此行数的文件将被截断
MAX_LINES = 500


class CircuitFileCollector:
    """
    电路文件收集器
    
    实现 ContextSource 协议，收集当前电路文件内容。
    """

    def __init__(self):
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
                self._logger = get_logger("circuit_file_collector")
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
        异步收集电路文件内容
        
        Args:
            context: 收集上下文
            
        Returns:
            ContextResult: 收集结果
        """
        source_name = self.get_source_name()
        
        # 检查是否有电路文件路径
        if not context.circuit_file_path:
            if self.logger:
                self.logger.debug("No circuit file path provided")
            return ContextResult.empty(source_name)
        
        # 构建绝对路径
        file_path = Path(context.project_path) / context.circuit_file_path
        
        # 检查文件是否存在
        if not file_path.exists():
            if self.logger:
                self.logger.warning(f"Circuit file not found: {file_path}")
            return ContextResult.empty(source_name)
        
        # 检查文件扩展名
        if file_path.suffix.lower() not in SPICE_EXTENSIONS:
            if self.logger:
                self.logger.debug(f"Not a SPICE file: {file_path}")
            return ContextResult.empty(source_name)
        
        try:
            # 异步加载文件内容
            content = await self._load_file_content_async(file_path)
            
            if not content:
                return ContextResult.empty(source_name)
            
            # 提取元数据
            metadata = self._extract_metadata(content, file_path)
            
            # 格式化内容（添加行号）
            formatted_content = self._format_content(
                content, context.circuit_file_path, metadata
            )
            
            # 估算 Token 数
            token_count = self._estimate_tokens(formatted_content)
            
            return ContextResult(
                content=formatted_content,
                token_count=token_count,
                source_name=source_name,
                priority=self.get_priority(),
                metadata=metadata,
            )
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to collect circuit file: {e}")
            return ContextResult.empty(source_name)

    def get_priority(self) -> ContextPriority:
        """获取优先级"""
        return ContextPriority.HIGH

    def get_source_name(self) -> str:
        """获取源名称"""
        return "circuit_file"

    # ============================================================
    # 内部方法
    # ============================================================

    async def _load_file_content_async(self, file_path: Path) -> str:
        """
        异步加载文件内容
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 文件内容
        """
        import asyncio
        
        # 检查文件大小
        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            if self.logger:
                self.logger.warning(
                    f"File too large ({file_size} bytes), will be truncated"
                )
        
        # 使用 AsyncFileOps 或回退到 to_thread
        if self.async_file_ops:
            try:
                return await self.async_file_ops.read_file_async(str(file_path))
            except Exception:
                pass
        
        # 回退：使用 to_thread 包装同步读取
        def read_sync():
            return file_path.read_text(encoding="utf-8", errors="ignore")
        
        return await asyncio.to_thread(read_sync)

    def _extract_metadata(
        self, content: str, file_path: Path
    ) -> Dict[str, Any]:
        """
        提取文件元数据
        
        Args:
            content: 文件内容
            file_path: 文件路径
            
        Returns:
            Dict: 元数据字典
        """
        metadata: Dict[str, Any] = {
            "file_name": file_path.name,
            "file_path": str(file_path),
            "file_size": file_path.stat().st_size,
            "modified_time": datetime.fromtimestamp(
                file_path.stat().st_mtime
            ).isoformat(),
        }
        
        lines = content.split("\n")
        
        # 提取标题行（第一行非空注释）
        for line in lines[:10]:
            line = line.strip()
            if line.startswith("*") and len(line) > 1:
                metadata["title"] = line[1:].strip()
                break
            elif line and not line.startswith("."):
                # SPICE 文件第一行通常是标题
                metadata["title"] = line
                break
        
        # 提取描述注释（标题后的连续注释行）
        description_lines = []
        in_description = False
        for line in lines[:30]:
            line = line.strip()
            if line.startswith("*"):
                if "title" in metadata and not in_description:
                    in_description = True
                if in_description:
                    description_lines.append(line[1:].strip())
            elif in_description and line:
                break
        
        if description_lines:
            metadata["description"] = "\n".join(description_lines[:5])
        
        # 提取子电路定义列表
        subcircuits = self._extract_subcircuits(content)
        if subcircuits:
            metadata["subcircuits"] = subcircuits
        
        # 统计行数
        metadata["line_count"] = len(lines)
        
        return metadata

    def _extract_subcircuits(self, content: str) -> List[str]:
        """
        提取子电路名称列表
        
        Args:
            content: 文件内容
            
        Returns:
            List[str]: 子电路名称列表
        """
        subcircuits = []
        
        # 匹配 .subckt 语句
        pattern = r"\.subckt\s+(\w+)"
        matches = re.findall(pattern, content, re.IGNORECASE)
        
        subcircuits.extend(matches)
        
        return subcircuits

    def _format_content(
        self,
        content: str,
        relative_path: str,
        metadata: Dict[str, Any],
    ) -> str:
        """
        格式化内容（添加行号和头部信息）
        
        Args:
            content: 原始内容
            relative_path: 相对路径
            metadata: 元数据
            
        Returns:
            str: 格式化后的内容
        """
        lines = content.split("\n")
        
        # 截断过长的文件
        truncated = False
        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES]
            truncated = True
        
        # 构建头部信息
        header_parts = [f"=== Circuit File: {relative_path} ==="]
        
        if "title" in metadata:
            header_parts.append(f"Title: {metadata['title']}")
        
        if "subcircuits" in metadata and metadata["subcircuits"]:
            header_parts.append(
                f"Subcircuits: {', '.join(metadata['subcircuits'][:5])}"
            )
        
        header_parts.append(f"Lines: {metadata.get('line_count', len(lines))}")
        header_parts.append("")
        
        # 添加行号
        numbered_lines = []
        for i, line in enumerate(lines, 1):
            numbered_lines.append(f"{i:4d} | {line}")
        
        # 添加截断提示
        if truncated:
            numbered_lines.append(f"... (truncated, showing first {MAX_LINES} lines)")
        
        # 组合结果
        result_parts = header_parts + numbered_lines
        return "\n".join(result_parts)

    def _estimate_tokens(self, text: str) -> int:
        """估算 Token 数"""
        if not text:
            return 0
        
        try:
            from domain.llm.token_counter import count_tokens
            return count_tokens(text)
        except ImportError:
            # 回退到简单估算
            return len(text) // 4


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "CircuitFileCollector",
    "SPICE_EXTENSIONS",
    "MAX_FILE_SIZE",
    "MAX_LINES",
]
