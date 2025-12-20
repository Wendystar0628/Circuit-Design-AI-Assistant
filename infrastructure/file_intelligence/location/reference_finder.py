# Reference Finder - Symbol Reference Finder
"""
引用查找器

职责：
- 查找符号的所有引用位置
- 排除注释中的匹配
- 区分定义和使用
"""

import re
from pathlib import Path
from typing import List, Optional, Set

from infrastructure.file_intelligence.location.location_types import ReferenceResult
from infrastructure.file_intelligence.analysis.file_analyzer import FileAnalyzer


class ReferenceFinder:
    """
    引用查找器
    
    使用正则表达式搜索符号引用，智能排除注释。
    """
    
    # SPICE 注释模式（* 开头或 ; 后面）
    SPICE_COMMENT_PATTERN = re.compile(r'^\s*\*|;.*$')
    
    # Python 注释模式（# 后面）
    PYTHON_COMMENT_PATTERN = re.compile(r'#.*$')
    
    def __init__(self, file_analyzer: FileAnalyzer = None):
        """
        初始化引用查找器
        
        Args:
            file_analyzer: 文件分析器实例
        """
        self._file_analyzer = file_analyzer
        self._file_manager = None
    
    @property
    def file_analyzer(self) -> FileAnalyzer:
        """延迟获取文件分析器"""
        if self._file_analyzer is None:
            self._file_analyzer = FileAnalyzer()
        return self._file_analyzer
    
    @property
    def file_manager(self):
        """延迟获取文件管理器"""
        if self._file_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_FILE_MANAGER
                self._file_manager = ServiceLocator.get_optional(SVC_FILE_MANAGER)
            except Exception:
                pass
        return self._file_manager
    
    def find_all_references(
        self,
        symbol_name: str,
        definition_file: str = None,
        search_files: List[str] = None
    ) -> List[ReferenceResult]:
        """
        查找符号的所有引用
        
        Args:
            symbol_name: 符号名称
            definition_file: 定义所在文件（用于标记定义位置）
            search_files: 要搜索的文件列表，不传则搜索整个项目
            
        Returns:
            List[ReferenceResult]: 引用结果列表
        """
        results = []
        definition_line = None
        
        # 获取定义位置
        if definition_file:
            symbol = self.file_analyzer.find_symbol(definition_file, symbol_name)
            if symbol:
                definition_line = symbol.line_start
        
        # 确定搜索范围
        if search_files is None:
            search_files = self._get_project_files()
        
        # 在每个文件中搜索
        for file_path in search_files:
            file_results = self.find_references_in_file(
                symbol_name,
                file_path,
                is_definition_file=(file_path == definition_file),
                definition_line=definition_line
            )
            results.extend(file_results)
        
        return results
    
    def find_references_in_file(
        self,
        symbol_name: str,
        file_path: str,
        is_definition_file: bool = False,
        definition_line: int = None
    ) -> List[ReferenceResult]:
        """
        在指定文件中查找符号引用
        
        Args:
            symbol_name: 符号名称
            file_path: 文件路径
            is_definition_file: 是否是定义所在文件
            definition_line: 定义所在行号
            
        Returns:
            List[ReferenceResult]: 引用结果列表
        """
        results = []
        path = Path(file_path)
        
        if not path.exists():
            return results
        
        # 确定文件类型和注释模式
        ext = path.suffix.lower()
        is_spice = ext in {'.cir', '.sp', '.spice', '.net', '.ckt'}
        is_python = ext in {'.py', '.pyw'}
        
        # 构建匹配模式（单词边界）
        pattern = re.compile(rf'\b{re.escape(symbol_name)}\b', re.IGNORECASE)
        
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
            lines = content.splitlines()
            
            for line_num, line in enumerate(lines, 1):
                # 检查是否在注释中
                context_type = self._get_context_type(
                    line, is_spice, is_python
                )
                
                # 查找所有匹配
                for match in pattern.finditer(line):
                    # 检查匹配位置是否在注释中
                    if self._is_in_comment(
                        line, match.start(), is_spice, is_python
                    ):
                        context_type = "comment"
                    
                    # 判断是否是定义
                    is_def = (
                        is_definition_file and 
                        definition_line is not None and 
                        line_num == definition_line
                    )
                    
                    # 计算相对路径
                    relative_path = file_path
                    if self.file_manager:
                        relative_path = self.file_manager.to_relative_path(
                            str(path)
                        ) or file_path
                    
                    results.append(ReferenceResult(
                        file_path=relative_path,
                        absolute_path=str(path.absolute()),
                        line=line_num,
                        column=match.start(),
                        line_content=line.strip(),
                        is_definition=is_def,
                        context_type="definition" if is_def else context_type,
                    ))
        except Exception:
            pass
        
        return results
    
    def _get_context_type(
        self,
        line: str,
        is_spice: bool,
        is_python: bool
    ) -> str:
        """判断行的上下文类型"""
        line_stripped = line.strip()
        
        if is_spice:
            # SPICE 注释行
            if line_stripped.startswith('*'):
                return "comment"
        
        if is_python:
            # Python 注释行
            if line_stripped.startswith('#'):
                return "comment"
            # 文档字符串（简化判断）
            if line_stripped.startswith('"""') or line_stripped.startswith("'''"):
                return "comment"
        
        return "usage"
    
    def _is_in_comment(
        self,
        line: str,
        position: int,
        is_spice: bool,
        is_python: bool
    ) -> bool:
        """检查位置是否在注释中"""
        if is_spice:
            # SPICE: * 开头的整行是注释
            if line.strip().startswith('*'):
                return True
            # ; 后面是注释
            semicolon_pos = line.find(';')
            if semicolon_pos >= 0 and position > semicolon_pos:
                return True
        
        if is_python:
            # Python: # 后面是注释
            hash_pos = line.find('#')
            if hash_pos >= 0 and position > hash_pos:
                return True
        
        return False
    
    def _get_project_files(self) -> List[str]:
        """获取项目中的所有相关文件"""
        files = []
        
        try:
            from infrastructure.file_intelligence.search import FileSearchService
            search_service = FileSearchService()
            
            if self.file_manager:
                search_service.build_index(self.file_manager.get_work_dir())
            
            # 获取所有支持的文件
            all_files = search_service._file_index.get_all_files()
            
            for relative_path, absolute_path in all_files.items():
                if self.file_analyzer.supports(absolute_path):
                    files.append(absolute_path)
        except Exception:
            pass
        
        return files


__all__ = ["ReferenceFinder"]
