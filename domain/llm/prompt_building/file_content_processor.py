# File Content Processor - File Content Handling
"""
文件内容处理器 - 处理文件内容的截断、摘要生成

职责：
- 根据文件大小选择处理策略
- 截断内容以符合 Token 预算
- 为大文件生成结构摘要

使用示例：
    from domain.llm.prompt_building.file_content_processor import FileContentProcessor
    
    processor = FileContentProcessor()
    content = processor.process_file(file_content, "circuit.cir", budget=2000)
"""

import logging
from typing import List, Optional

from domain.llm.token_counter import count_tokens


# ============================================================
# 常量定义
# ============================================================

# 文件大小阈值（tokens）
SMALL_FILE_THRESHOLD = 2000      # 小文件：<2K tokens
MEDIUM_FILE_THRESHOLD = 8000     # 中文件：2K-8K tokens


# ============================================================
# FileContentProcessor 类
# ============================================================

class FileContentProcessor:
    """
    文件内容处理器
    
    职责：
    - 根据文件大小选择处理策略
    - 截断内容以符合 Token 预算
    - 为大文件生成结构摘要
    """
    
    def __init__(self):
        """初始化处理器"""
        self._logger = logging.getLogger(__name__)
    
    def process_file(
        self,
        content: str,
        path: str,
        budget: int
    ) -> str:
        """
        处理文件内容
        
        根据文件大小选择处理策略：
        - 小文件（<2K tokens）：直接返回完整内容
        - 中文件（2K-8K tokens）：截断到预算
        - 大文件（>8K tokens）：生成结构摘要 + 关键片段
        
        Args:
            content: 文件内容
            path: 文件路径
            budget: Token 预算
            
        Returns:
            处理后的内容
        """
        if not content:
            return content
        
        token_count = count_tokens(content)
        
        # 小文件：直接返回
        if token_count <= SMALL_FILE_THRESHOLD and token_count <= budget:
            return content
        
        # 中文件：截断到预算
        if token_count <= MEDIUM_FILE_THRESHOLD:
            return self.truncate_to_budget(content, budget)
        
        # 大文件：生成摘要
        return self.generate_file_summary(content, path, budget)
    
    def truncate_to_budget(
        self,
        content: str,
        budget: int
    ) -> str:
        """
        截断内容以符合 Token 预算
        
        Args:
            content: 原始内容
            budget: Token 预算
            
        Returns:
            截断后的内容
        """
        if not content:
            return content
        
        current_tokens = count_tokens(content)
        if current_tokens <= budget:
            return content
        
        # 估算需要保留的字符数
        # 假设平均 1 token ≈ 3 字符（中英文混合）
        estimated_chars = int(budget * 3)
        
        if estimated_chars >= len(content):
            return content
        
        # 截断并添加省略标记
        truncated = content[:estimated_chars]
        
        # 尝试在句子边界截断
        last_period = max(
            truncated.rfind('.'),
            truncated.rfind('。'),
            truncated.rfind('\n')
        )
        if last_period > estimated_chars * 0.7:
            truncated = truncated[:last_period + 1]
        
        return truncated + "\n\n[Content truncated due to token budget]"
    
    def generate_file_summary(
        self,
        content: str,
        path: str,
        budget: Optional[int] = None
    ) -> str:
        """
        为大文件生成结构摘要
        
        Args:
            content: 文件内容
            path: 文件路径
            budget: Token 预算（可选）
            
        Returns:
            结构摘要
        """
        lines = content.split('\n')
        total_lines = len(lines)
        
        summary_parts = [f"File: {path} ({total_lines} lines)"]
        
        # 根据文件类型选择处理策略
        if path.endswith(('.cir', '.sp', '.spice')):
            summary_parts.extend(self._summarize_spice_file(lines))
        else:
            summary_parts.extend(self._summarize_generic_file(lines, total_lines))
        
        result = '\n'.join(summary_parts)
        
        # 如果有预算限制，截断摘要
        if budget and count_tokens(result) > budget:
            result = self.truncate_to_budget(result, budget)
        
        return result
    
    def _summarize_spice_file(self, lines: List[str]) -> List[str]:
        """
        为 SPICE 文件生成摘要
        
        提取：
        - 子电路定义列表
        - 组件数量统计
        - 文件开头和结尾
        """
        summary_parts = []
        
        # 提取子电路和统计组件
        subcircuits = []
        components = {"R": 0, "C": 0, "L": 0, "Q": 0, "M": 0, "D": 0, "V": 0, "I": 0}
        
        for line in lines:
            line_stripped = line.strip()
            line_upper = line_stripped.upper()
            
            if line_upper.startswith('.SUBCKT'):
                parts = line_stripped.split()
                if len(parts) >= 2:
                    subcircuits.append(parts[1])
            elif line_upper and line_upper[0] in components:
                components[line_upper[0]] += 1
        
        if subcircuits:
            summary_parts.append(f"Subcircuits: {', '.join(subcircuits)}")
        
        comp_summary = [f"{k}:{v}" for k, v in components.items() if v > 0]
        if comp_summary:
            summary_parts.append(f"Components: {', '.join(comp_summary)}")
        
        # 添加文件开头和结尾
        summary_parts.append("\n--- First 20 lines ---")
        summary_parts.extend(lines[:20])
        summary_parts.append("\n--- Last 10 lines ---")
        summary_parts.extend(lines[-10:])
        
        return summary_parts
    
    def _summarize_generic_file(
        self,
        lines: List[str],
        total_lines: int
    ) -> List[str]:
        """为通用文件生成摘要"""
        summary_parts = []
        
        summary_parts.append("\n--- First 30 lines ---")
        summary_parts.extend(lines[:30])
        
        if total_lines > 30:
            summary_parts.append(f"\n... ({total_lines - 30} more lines)")
        
        return summary_parts
    
    def extract_key_sections(
        self,
        content: str,
        path: str
    ) -> List[str]:
        """
        提取关键片段
        
        Args:
            content: 文件内容
            path: 文件路径
            
        Returns:
            关键片段列表
        """
        sections = []
        lines = content.split('\n')
        
        if path.endswith(('.cir', '.sp', '.spice')):
            # SPICE 文件：提取子电路定义
            in_subckt = False
            current_subckt = []
            
            for line in lines:
                line_upper = line.strip().upper()
                
                if line_upper.startswith('.SUBCKT'):
                    in_subckt = True
                    current_subckt = [line]
                elif line_upper.startswith('.ENDS') and in_subckt:
                    current_subckt.append(line)
                    sections.append('\n'.join(current_subckt))
                    in_subckt = False
                    current_subckt = []
                elif in_subckt:
                    current_subckt.append(line)
        
        return sections


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "FileContentProcessor",
    "SMALL_FILE_THRESHOLD",
    "MEDIUM_FILE_THRESHOLD",
]
