# Symbol Locator - Symbol Definition Locator
"""
符号定位器

职责：
- 定位符号的定义位置
- 支持多级定位策略

定位策略优先级：
1. 当前文件查找
2. include 引用的文件中查找
3. 整个项目中查找
"""

from pathlib import Path
from typing import List, Optional

from infrastructure.file_intelligence.location.location_types import (
    LocationResult,
    LocationScope,
)
from infrastructure.file_intelligence.analysis.file_analyzer import FileAnalyzer


class SymbolLocator:
    """
    符号定位器
    
    实现多级定位策略，优先在近处查找。
    """
    
    def __init__(self, file_analyzer: FileAnalyzer = None):
        """
        初始化符号定位器
        
        Args:
            file_analyzer: 文件分析器实例，不传则延迟创建
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
    
    def locate_definition(
        self,
        symbol_name: str,
        context_file: str,
        include_files: List[str] = None
    ) -> Optional[LocationResult]:
        """
        定位符号定义（多级策略）
        
        Args:
            symbol_name: 符号名称
            context_file: 上下文文件路径（当前编辑的文件）
            include_files: include 引用的文件列表
            
        Returns:
            LocationResult: 定位结果，未找到返回 None
        """
        # 策略1：在当前文件查找
        result = self.locate_in_file(symbol_name, context_file)
        if result:
            result.scope = LocationScope.CURRENT_FILE
            return result
        
        # 策略2：在 include 文件中查找
        if include_files:
            for include_file in include_files:
                result = self.locate_in_file(symbol_name, include_file)
                if result:
                    result.scope = LocationScope.INCLUDE_FILES
                    return result
        
        # 策略2.5：自动解析当前文件的 include
        auto_includes = self._get_includes_from_file(context_file)
        for include_file in auto_includes:
            if include_file not in (include_files or []):
                result = self.locate_in_file(symbol_name, include_file)
                if result:
                    result.scope = LocationScope.INCLUDE_FILES
                    return result
        
        # 策略3：在整个项目中查找
        result = self.locate_in_project(symbol_name, context_file)
        if result:
            result.scope = LocationScope.PROJECT
            return result
        
        return None
    
    def locate_in_file(
        self,
        symbol_name: str,
        file_path: str
    ) -> Optional[LocationResult]:
        """
        在指定文件中定位符号
        
        Args:
            symbol_name: 符号名称
            file_path: 文件路径
            
        Returns:
            LocationResult: 定位结果，未找到返回 None
        """
        # 检查文件是否存在
        path = Path(file_path)
        if not path.exists():
            # 尝试相对路径
            if self.file_manager:
                abs_path = self.file_manager.to_absolute_path(file_path)
                if abs_path:
                    path = Path(abs_path)
            if not path.exists():
                return None
        
        # 检查是否支持该文件类型
        if not self.file_analyzer.supports(str(path)):
            return None
        
        # 查找符号
        symbol = self.file_analyzer.find_symbol(str(path), symbol_name)
        if not symbol:
            return None
        
        # 获取预览内容
        preview = self._get_line_content(str(path), symbol.line_start)
        
        # 计算相对路径
        relative_path = file_path
        if self.file_manager:
            relative_path = self.file_manager.to_relative_path(str(path)) or file_path
        
        return LocationResult(
            file_path=relative_path,
            absolute_path=str(path.absolute()),
            line=symbol.line_start,
            column=symbol.column_start,
            symbol_name=symbol.name,
            symbol_type=symbol.type.value,
            preview=preview,
            confidence=1.0,
        )
    
    def locate_in_project(
        self,
        symbol_name: str,
        exclude_file: str = None
    ) -> Optional[LocationResult]:
        """
        在整个项目中定位符号
        
        Args:
            symbol_name: 符号名称
            exclude_file: 排除的文件（通常是当前文件）
            
        Returns:
            LocationResult: 定位结果，未找到返回 None
        """
        # 获取项目文件列表
        try:
            from infrastructure.file_intelligence.search import FileSearchService
            search_service = FileSearchService()
            
            # 构建索引
            if self.file_manager:
                search_service.build_index(self.file_manager.get_work_dir())
            
            # 搜索符号
            results = search_service.search_symbols(
                symbol_name,
                fuzzy=False,  # 精确匹配
                max_results=10
            )
            
            for result in results:
                # 排除当前文件
                if exclude_file and result.absolute_path == exclude_file:
                    continue
                
                # 获取符号详情
                symbol = self.file_analyzer.find_symbol(
                    result.absolute_path,
                    symbol_name
                )
                if symbol:
                    preview = self._get_line_content(
                        result.absolute_path,
                        symbol.line_start
                    )
                    return LocationResult(
                        file_path=result.path,
                        absolute_path=result.absolute_path,
                        line=symbol.line_start,
                        column=symbol.column_start,
                        symbol_name=symbol.name,
                        symbol_type=symbol.type.value,
                        preview=preview,
                        confidence=0.8,  # 项目级搜索置信度稍低
                    )
        except Exception:
            pass
        
        return None
    
    def _get_includes_from_file(self, file_path: str) -> List[str]:
        """从文件中提取 include 引用"""
        try:
            structure = self.file_analyzer.get_structure(file_path)
            includes = structure.includes or []
            
            # 解析相对路径
            resolved = []
            base_dir = Path(file_path).parent
            
            for inc in includes:
                inc_path = base_dir / inc
                if inc_path.exists():
                    resolved.append(str(inc_path))
                elif self.file_manager:
                    # 尝试从工作目录解析
                    abs_path = self.file_manager.to_absolute_path(inc)
                    if abs_path and Path(abs_path).exists():
                        resolved.append(abs_path)
            
            return resolved
        except Exception:
            return []
    
    def _get_line_content(self, file_path: str, line_number: int) -> str:
        """获取指定行的内容"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if i == line_number:
                        return line.rstrip()
        except Exception:
            pass
        return ""


__all__ = ["SymbolLocator"]
