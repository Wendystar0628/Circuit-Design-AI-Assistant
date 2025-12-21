# File Analyzer - Unified File Analysis Entry
"""
文件分析器门面类

职责：
- 提供统一的文件分析入口
- 根据文件类型选择合适的符号提取器
- 支持跳转定义、查找引用、结构大纲
- 大文件保护：超过阈值时拒绝分析

文件类型路由：
- .cir/.sp/.spice/.net/.ckt → SpiceSymbolExtractor
- .py/.pyw → PythonSymbolExtractor
- 其他 → 返回空结果

被调用方：
- FileSearchService.search_symbols()
- LocationService
- tool_dispatcher.py（阶段六 analyze_file 工具）
"""

from pathlib import Path
from typing import List, Optional, Tuple

from shared.constants.file_limits import ANALYZE_FILE_MAX_BYTES
from infrastructure.file_intelligence.analysis.symbol_types import (
    SymbolType,
    SymbolInfo,
    FileStructure,
)
from infrastructure.file_intelligence.analysis.spice_symbol_extractor import (
    SpiceSymbolExtractor,
)
from infrastructure.file_intelligence.analysis.python_symbol_extractor import (
    PythonSymbolExtractor,
)


class FileAnalyzer:
    """
    文件分析器门面类
    
    提供统一的文件分析入口，根据文件类型自动选择合适的提取器。
    """
    
    def __init__(self):
        """初始化文件分析器"""
        self._spice_extractor = SpiceSymbolExtractor()
        self._python_extractor = PythonSymbolExtractor()
    
    def get_symbols(self, file_path: str) -> List[SymbolInfo]:
        """
        提取文件中的符号定义
        
        Args:
            file_path: 文件路径
            
        Returns:
            List[SymbolInfo]: 符号列表
        """
        structure = self.get_structure(file_path)
        
        # 展平符号列表（包括嵌套的子符号）
        symbols = []
        for symbol in structure.symbols:
            symbols.append(symbol)
            symbols.extend(symbol.children)
        
        return symbols
    
    def get_structure(self, file_path: str) -> FileStructure:
        """
        获取文件结构大纲（用于 UI 显示）
        
        包含大文件保护：超过 ANALYZE_FILE_MAX_BYTES 时拒绝分析。
        
        Args:
            file_path: 文件路径
            
        Returns:
            FileStructure: 文件结构信息，大文件时 error 字段包含错误信息
        """
        file_path_obj = Path(file_path)
        
        # 大文件保护检查
        try:
            file_size = file_path_obj.stat().st_size
            if file_size > ANALYZE_FILE_MAX_BYTES:
                size_mb = file_size / (1024 * 1024)
                structure = FileStructure(file_path=str(file_path))
                structure.error = (
                    f"文件过大（{size_mb:.1f}MB），无法分析。"
                    f"建议使用 read_file(start_line, end_line) 分段读取"
                )
                return structure
        except OSError:
            # 文件不存在或无法访问，让后续逻辑处理
            pass
        
        extractor = self._get_extractor(file_path)
        
        if extractor is None:
            return FileStructure(file_path=str(file_path))
        
        return extractor.extract_symbols(file_path)
    
    def find_symbol(
        self,
        file_path: str,
        symbol_name: str
    ) -> Optional[SymbolInfo]:
        """
        查找符号定义位置
        
        Args:
            file_path: 文件路径
            symbol_name: 符号名称
            
        Returns:
            SymbolInfo: 符号信息，未找到返回 None
        """
        extractor = self._get_extractor(file_path)
        
        if extractor is None:
            return None
        
        return extractor.find_symbol(file_path, symbol_name)
    
    def find_symbol_in_files(
        self,
        symbol_name: str,
        file_paths: List[str]
    ) -> List[Tuple[str, SymbolInfo]]:
        """
        在多个文件中查找符号定义
        
        Args:
            symbol_name: 符号名称
            file_paths: 文件路径列表
            
        Returns:
            List[Tuple[str, SymbolInfo]]: [(文件路径, 符号信息), ...]
        """
        results = []
        
        for file_path in file_paths:
            symbol = self.find_symbol(file_path, symbol_name)
            if symbol:
                results.append((file_path, symbol))
        
        return results
    
    def get_includes(self, file_path: str) -> List[str]:
        """
        获取文件引用列表
        
        对于 SPICE 文件返回 .include/.lib 引用
        对于 Python 文件返回 import 列表
        
        Args:
            file_path: 文件路径
            
        Returns:
            List[str]: 引用列表
        """
        structure = self.get_structure(file_path)
        return structure.includes or structure.imports
    
    def get_symbols_by_type(
        self,
        file_path: str,
        symbol_type: SymbolType
    ) -> List[SymbolInfo]:
        """
        按类型获取符号
        
        Args:
            file_path: 文件路径
            symbol_type: 符号类型
            
        Returns:
            List[SymbolInfo]: 符号列表
        """
        structure = self.get_structure(file_path)
        return structure.get_symbols_by_type(symbol_type)
    
    def supports(self, file_path: str) -> bool:
        """
        检查是否支持该文件类型
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否支持
        """
        return self._get_extractor(file_path) is not None
    
    def _get_extractor(self, file_path: str):
        """
        根据文件类型获取提取器
        
        Args:
            file_path: 文件路径
            
        Returns:
            提取器实例，不支持的类型返回 None
        """
        if SpiceSymbolExtractor.supports(file_path):
            return self._spice_extractor
        elif PythonSymbolExtractor.supports(file_path):
            return self._python_extractor
        else:
            return None


# 单例实例（可选使用）
_default_analyzer: Optional[FileAnalyzer] = None


def get_file_analyzer() -> FileAnalyzer:
    """获取默认的文件分析器实例"""
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = FileAnalyzer()
    return _default_analyzer


__all__ = [
    "FileAnalyzer",
    "get_file_analyzer",
]
