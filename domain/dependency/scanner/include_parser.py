# Include Parser
"""
.include/.lib 语句解析器

职责：
- 解析电路文件中的 .include 和 .lib 语句
- 提取引用路径和行号
- 支持多种路径格式
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ParsedInclude:
    """解析出的引用信息"""
    line_number: int
    statement_type: str  # "include" or "lib"
    raw_path: str
    is_quoted: bool = False


class IncludeParser:
    """
    .include/.lib 语句解析器
    
    解析 SPICE 电路文件中的引用语句
    """
    
    # .include 语句正则表达式
    # 支持格式：
    # .include "path/to/file.lib"
    # .include 'path/to/file.lib'
    # .include path/to/file.lib
    # .INCLUDE path/to/file.lib (大小写不敏感)
    INCLUDE_PATTERN = re.compile(
        r'^\s*\.include\s+["\']?([^"\']+)["\']?\s*$',
        re.IGNORECASE
    )
    
    # .lib 语句正则表达式
    # 支持格式：
    # .lib "path/to/file.lib"
    # .lib path/to/file.lib section_name
    # .LIB path/to/file.lib
    LIB_PATTERN = re.compile(
        r'^\s*\.lib\s+["\']?([^\s"\']+)["\']?(?:\s+\S+)?\s*$',
        re.IGNORECASE
    )
    
    def parse_file(self, file_path: str) -> List[ParsedInclude]:
        """
        解析文件中的所有引用语句
        
        Args:
            file_path: 电路文件路径
            
        Returns:
            List[ParsedInclude]: 解析出的引用列表
        """
        results = []
        
        try:
            path = Path(file_path)
            if not path.exists():
                return results
            
            content = path.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            
            for line_num, line in enumerate(lines, start=1):
                parsed = self.parse_line(line, line_num)
                if parsed:
                    results.append(parsed)
                    
        except Exception:
            # 解析失败时返回空列表，不抛出异常
            pass
        
        return results
    
    def parse_line(self, line: str, line_number: int) -> Optional[ParsedInclude]:
        """
        解析单行内容
        
        Args:
            line: 行内容
            line_number: 行号
            
        Returns:
            Optional[ParsedInclude]: 解析结果，若非引用语句则返回 None
        """
        # 跳过注释行
        stripped = line.strip()
        if stripped.startswith('*') or stripped.startswith(';'):
            return None
        
        # 尝试匹配 .include
        match = self.INCLUDE_PATTERN.match(stripped)
        if match:
            raw_path = match.group(1).strip()
            is_quoted = '"' in line or "'" in line
            return ParsedInclude(
                line_number=line_number,
                statement_type="include",
                raw_path=raw_path,
                is_quoted=is_quoted,
            )
        
        # 尝试匹配 .lib
        match = self.LIB_PATTERN.match(stripped)
        if match:
            raw_path = match.group(1).strip()
            is_quoted = '"' in line or "'" in line
            return ParsedInclude(
                line_number=line_number,
                statement_type="lib",
                raw_path=raw_path,
                is_quoted=is_quoted,
            )
        
        return None
    
    def parse_content(self, content: str) -> List[ParsedInclude]:
        """
        解析文件内容字符串
        
        Args:
            content: 文件内容
            
        Returns:
            List[ParsedInclude]: 解析出的引用列表
        """
        results = []
        lines = content.splitlines()
        
        for line_num, line in enumerate(lines, start=1):
            parsed = self.parse_line(line, line_num)
            if parsed:
                results.append(parsed)
        
        return results


__all__ = ["IncludeParser", "ParsedInclude"]
