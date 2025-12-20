# Location Service - Unified Location Entry
"""
定位服务门面类

职责：
- 提供统一的符号定位和导航入口
- 整合 SymbolLocator 和 ReferenceFinder

使用示例：
    from infrastructure.file_intelligence.location import LocationService
    
    service = LocationService()
    
    # 跳转到定义
    result = service.go_to_definition("opamp", "circuit.cir", line=10)
    
    # 查找所有引用
    refs = service.find_references("opamp", "circuit.cir")
"""

from pathlib import Path
from typing import List, Optional

from infrastructure.file_intelligence.location.location_types import (
    LocationResult,
    ReferenceResult,
    LocationScope,
)
from infrastructure.file_intelligence.location.symbol_locator import SymbolLocator
from infrastructure.file_intelligence.location.reference_finder import ReferenceFinder
from infrastructure.file_intelligence.analysis.file_analyzer import FileAnalyzer


class LocationService:
    """
    定位服务门面类
    
    提供统一的符号定位和导航入口。
    """
    
    def __init__(self):
        """初始化定位服务"""
        self._file_analyzer = FileAnalyzer()
        self._symbol_locator = SymbolLocator(self._file_analyzer)
        self._reference_finder = ReferenceFinder(self._file_analyzer)
        self._file_manager = None
    
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
    
    def go_to_definition(
        self,
        symbol_name: str,
        file_path: str,
        line: int = 0,
        column: int = 0
    ) -> Optional[LocationResult]:
        """
        跳转到符号定义
        
        Args:
            symbol_name: 符号名称
            file_path: 当前文件路径
            line: 当前行号（用于上下文）
            column: 当前列号（用于上下文）
            
        Returns:
            LocationResult: 定位结果，未找到返回 None
        """
        # 解析绝对路径
        abs_path = self._resolve_path(file_path)
        if not abs_path:
            return None
        
        # 使用符号定位器
        return self._symbol_locator.locate_definition(
            symbol_name,
            abs_path
        )
    
    def find_references(
        self,
        symbol_name: str,
        file_path: str = None,
        include_definition: bool = True
    ) -> List[ReferenceResult]:
        """
        查找符号的所有引用
        
        Args:
            symbol_name: 符号名称
            file_path: 定义所在文件（可选，用于标记定义位置）
            include_definition: 是否包含定义位置
            
        Returns:
            List[ReferenceResult]: 引用结果列表
        """
        abs_path = None
        if file_path:
            abs_path = self._resolve_path(file_path)
        
        results = self._reference_finder.find_all_references(
            symbol_name,
            definition_file=abs_path
        )
        
        # 过滤定义位置
        if not include_definition:
            results = [r for r in results if not r.is_definition]
        
        return results
    
    def find_symbol(
        self,
        symbol_name: str,
        scope: LocationScope = LocationScope.PROJECT,
        context_file: str = None
    ) -> List[LocationResult]:
        """
        在指定范围查找符号
        
        Args:
            symbol_name: 符号名称
            scope: 查找范围
            context_file: 上下文文件（用于 CURRENT_FILE 和 INCLUDE_FILES 范围）
            
        Returns:
            List[LocationResult]: 定位结果列表
        """
        results = []
        
        if scope == LocationScope.CURRENT_FILE:
            if context_file:
                abs_path = self._resolve_path(context_file)
                if abs_path:
                    result = self._symbol_locator.locate_in_file(
                        symbol_name, abs_path
                    )
                    if result:
                        result.scope = LocationScope.CURRENT_FILE
                        results.append(result)
        
        elif scope == LocationScope.INCLUDE_FILES:
            if context_file:
                abs_path = self._resolve_path(context_file)
                if abs_path:
                    # 获取 include 文件
                    structure = self._file_analyzer.get_structure(abs_path)
                    for inc in structure.includes:
                        inc_path = self._resolve_include_path(inc, abs_path)
                        if inc_path:
                            result = self._symbol_locator.locate_in_file(
                                symbol_name, inc_path
                            )
                            if result:
                                result.scope = LocationScope.INCLUDE_FILES
                                results.append(result)
        
        elif scope == LocationScope.PROJECT:
            # 项目级搜索
            result = self._symbol_locator.locate_in_project(symbol_name)
            if result:
                result.scope = LocationScope.PROJECT
                results.append(result)
        
        return results
    
    def get_symbol_at_position(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> Optional[str]:
        """
        获取指定位置的符号名称
        
        Args:
            file_path: 文件路径
            line: 行号
            column: 列号
            
        Returns:
            str: 符号名称，未找到返回 None
        """
        abs_path = self._resolve_path(file_path)
        if not abs_path:
            return None
        
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                if line <= 0 or line > len(lines):
                    return None
                
                line_content = lines[line - 1]
                
                # 提取光标位置的单词
                return self._extract_word_at_position(line_content, column)
        except Exception:
            return None
    
    def _extract_word_at_position(self, line: str, column: int) -> Optional[str]:
        """从行中提取指定位置的单词"""
        if column < 0 or column >= len(line):
            return None
        
        # 向左扩展
        start = column
        while start > 0 and self._is_word_char(line[start - 1]):
            start -= 1
        
        # 向右扩展
        end = column
        while end < len(line) and self._is_word_char(line[end]):
            end += 1
        
        if start == end:
            return None
        
        return line[start:end]
    
    def _is_word_char(self, char: str) -> bool:
        """判断是否是单词字符"""
        return char.isalnum() or char == '_'
    
    def _resolve_path(self, file_path: str) -> Optional[str]:
        """解析文件路径为绝对路径"""
        path = Path(file_path)
        
        if path.is_absolute() and path.exists():
            return str(path)
        
        if self.file_manager:
            abs_path = self.file_manager.to_absolute_path(file_path)
            if abs_path and Path(abs_path).exists():
                return abs_path
        
        if path.exists():
            return str(path.absolute())
        
        return None
    
    def _resolve_include_path(
        self,
        include_path: str,
        context_file: str
    ) -> Optional[str]:
        """解析 include 路径"""
        # 相对于上下文文件
        base_dir = Path(context_file).parent
        resolved = base_dir / include_path
        if resolved.exists():
            return str(resolved)
        
        # 相对于工作目录
        if self.file_manager:
            abs_path = self.file_manager.to_absolute_path(include_path)
            if abs_path and Path(abs_path).exists():
                return abs_path
        
        return None


__all__ = ["LocationService"]
