# Content Searcher - File Content Search
"""
文件内容搜索器

职责：
- 在文件内容中搜索指定文本
- 支持单文件搜索和目录递归搜索
- 提供匹配上下文获取

被调用方：file_search_service.py
"""

import re
from pathlib import Path
from typing import List, Optional, Union

from infrastructure.file_intelligence.models.search_result import SearchMatch


class ContentSearchOptions:
    """内容搜索选项"""
    
    __slots__ = (
        'case_sensitive', 'use_regex', 'whole_word',
        'context_lines', 'max_matches_per_file', 'max_file_size',
        'include_binary'
    )
    
    def __init__(
        self,
        case_sensitive: bool = False,
        use_regex: bool = False,
        whole_word: bool = False,
        context_lines: int = 2,
        max_matches_per_file: int = 100,
        max_file_size: int = 1024 * 1024,  # 1MB
        include_binary: bool = False
    ):
        self.case_sensitive = case_sensitive
        self.use_regex = use_regex
        self.whole_word = whole_word
        self.context_lines = context_lines
        self.max_matches_per_file = max_matches_per_file
        self.max_file_size = max_file_size
        self.include_binary = include_binary


class ContentSearcher:
    """
    文件内容搜索器
    
    无状态工具类，专注于文件内容搜索逻辑。
    """
    
    # 二进制文件检测：前 8KB 中的 null 字节比例阈值
    BINARY_CHECK_SIZE = 8192
    BINARY_NULL_THRESHOLD = 0.1
    
    # 文本文件编码尝试顺序
    ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    
    def __init__(self, file_manager=None):
        """
        初始化内容搜索器
        
        Args:
            file_manager: 可选的文件管理器，用于读取文件
        """
        self._file_manager = file_manager
    
    def search_in_file(
        self,
        file_path: Union[str, Path],
        query: str,
        options: ContentSearchOptions = None
    ) -> List[SearchMatch]:
        """
        在单个文件中搜索
        
        Args:
            file_path: 文件路径
            query: 搜索查询
            options: 搜索选项
            
        Returns:
            List[SearchMatch]: 匹配列表
        """
        if options is None:
            options = ContentSearchOptions()
        
        file_path = Path(file_path)
        
        # 检查文件是否存在
        if not file_path.exists() or not file_path.is_file():
            return []
        
        # 检查文件大小
        try:
            if file_path.stat().st_size > options.max_file_size:
                return []
        except OSError:
            return []
        
        # 读取文件内容
        content = self._read_file(file_path, options.include_binary)
        if content is None:
            return []
        
        # 编译搜索模式
        pattern = self._compile_pattern(query, options)
        if pattern is None:
            return []
        
        # 执行搜索
        return self._search_content(content, pattern, options)

    def search_in_directory(
        self,
        dir_path: Union[str, Path],
        query: str,
        options: ContentSearchOptions = None,
        file_filter: callable = None,
        max_files: int = 1000
    ) -> dict:
        """
        在目录中递归搜索
        
        Args:
            dir_path: 目录路径
            query: 搜索查询
            options: 搜索选项
            file_filter: 文件过滤函数 (Path) -> bool
            max_files: 最大搜索文件数
            
        Returns:
            dict: {file_path: List[SearchMatch]}
        """
        if options is None:
            options = ContentSearchOptions()
        
        dir_path = Path(dir_path)
        if not dir_path.exists() or not dir_path.is_dir():
            return {}
        
        # 编译搜索模式（避免重复编译）
        pattern = self._compile_pattern(query, options)
        if pattern is None:
            return {}
        
        results = {}
        file_count = 0
        
        for file_path in dir_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            # 应用文件过滤器
            if file_filter and not file_filter(file_path):
                continue
            
            # 检查文件数量限制
            file_count += 1
            if file_count > max_files:
                break
            
            # 检查文件大小
            try:
                if file_path.stat().st_size > options.max_file_size:
                    continue
            except OSError:
                continue
            
            # 读取并搜索
            content = self._read_file(file_path, options.include_binary)
            if content is None:
                continue
            
            matches = self._search_content(content, pattern, options)
            if matches:
                results[str(file_path)] = matches
        
        return results
    
    def get_context(
        self,
        file_path: Union[str, Path],
        line_number: int,
        context_lines: int = 2
    ) -> Optional[dict]:
        """
        获取指定行的上下文
        
        Args:
            file_path: 文件路径
            line_number: 行号（从 1 开始）
            context_lines: 上下文行数
            
        Returns:
            dict: {
                'line': str,           # 目标行内容
                'before': List[str],   # 前面的行
                'after': List[str],    # 后面的行
                'start_line': int,     # 上下文起始行号
                'end_line': int        # 上下文结束行号
            }
        """
        file_path = Path(file_path)
        
        content = self._read_file(file_path, include_binary=False)
        if content is None:
            return None
        
        lines = content.split('\n')
        
        # 行号从 1 开始，转换为索引
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return None
        
        start_idx = max(0, idx - context_lines)
        end_idx = min(len(lines), idx + context_lines + 1)
        
        return {
            'line': lines[idx],
            'before': lines[start_idx:idx],
            'after': lines[idx + 1:end_idx],
            'start_line': start_idx + 1,
            'end_line': end_idx
        }
    
    # ============================================================
    # 内部方法
    # ============================================================
    
    def _read_file(
        self,
        file_path: Path,
        include_binary: bool = False
    ) -> Optional[str]:
        """读取文件内容"""
        # 优先使用 file_manager
        if self._file_manager is not None:
            try:
                return self._file_manager.read_file(str(file_path))
            except Exception:
                pass
        
        # 直接读取
        for encoding in self.ENCODINGS:
            try:
                content = file_path.read_text(encoding=encoding)
                
                # 二进制检测
                if not include_binary and self._is_binary_content(content):
                    return None
                
                return content
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception:
                return None
        
        return None
    
    def _is_binary_content(self, content: str) -> bool:
        """检测内容是否为二进制"""
        check_size = min(len(content), self.BINARY_CHECK_SIZE)
        if check_size == 0:
            return False
        
        null_count = content[:check_size].count('\x00')
        return (null_count / check_size) > self.BINARY_NULL_THRESHOLD
    
    def _compile_pattern(
        self,
        query: str,
        options: ContentSearchOptions
    ) -> Optional[re.Pattern]:
        """编译搜索模式"""
        if not query:
            return None
        
        try:
            # 构建模式字符串
            if options.use_regex:
                pattern_str = query
            else:
                pattern_str = re.escape(query)
            
            # 全词匹配
            if options.whole_word:
                pattern_str = rf'\b{pattern_str}\b'
            
            # 编译标志
            flags = 0 if options.case_sensitive else re.IGNORECASE
            
            return re.compile(pattern_str, flags)
        except re.error:
            return None
    
    def _search_content(
        self,
        content: str,
        pattern: re.Pattern,
        options: ContentSearchOptions
    ) -> List[SearchMatch]:
        """在内容中搜索"""
        matches = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            for match in pattern.finditer(line):
                # 获取上下文
                start_ctx = max(0, i - options.context_lines)
                end_ctx = min(len(lines), i + options.context_lines + 1)
                
                search_match = SearchMatch(
                    line_number=i + 1,
                    line_content=line,
                    match_start=match.start(),
                    match_end=match.end(),
                    context_before=lines[start_ctx:i],
                    context_after=lines[i + 1:end_ctx],
                )
                matches.append(search_match)
                
                # 限制每个文件的匹配数量
                if len(matches) >= options.max_matches_per_file:
                    return matches
        
        return matches


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    'ContentSearcher',
    'ContentSearchOptions',
]
