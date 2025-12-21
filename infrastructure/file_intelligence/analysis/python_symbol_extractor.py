# Python Symbol Extractor - AST-based Symbol Extraction for Python Files
"""
Python 符号提取器

职责：
- 使用 Python AST 模块提取符号信息
- 支持跳转定义、查找引用、结构大纲
- 大文件保护：超过阈值时拒绝分析

提取的符号类型：
- class: 类定义
- function: 函数定义
- method: 方法定义（类内函数）
- variable: 模块级变量
"""

import ast
from pathlib import Path
from typing import List, Optional

from infrastructure.config.settings import ANALYZE_FILE_MAX_BYTES
from infrastructure.file_intelligence.analysis.symbol_types import (
    SymbolType,
    SymbolInfo,
    FileStructure,
)


class PythonSymbolExtractor:
    """
    Python 符号提取器
    
    使用 AST 解析，提取类、函数、变量等符号信息。
    包含大文件保护，超过阈值时拒绝分析。
    """
    
    # 支持的文件扩展名
    SUPPORTED_EXTENSIONS = {".py", ".pyw"}
    
    @classmethod
    def supports(cls, file_path: str) -> bool:
        """检查是否支持该文件类型"""
        return Path(file_path).suffix.lower() in cls.SUPPORTED_EXTENSIONS
    
    def extract_symbols(self, file_path: str) -> FileStructure:
        """
        提取文件中的所有符号
        
        包含大文件保护：超过 ANALYZE_FILE_MAX_BYTES 时拒绝分析。
        Python AST 解析对大文件内存占用较高，必须有此保护。
        
        Args:
            file_path: 文件路径
            
        Returns:
            FileStructure: 文件结构信息，大文件时 error 字段包含错误信息
        """
        file_path_obj = Path(file_path)
        structure = FileStructure(file_path=str(file_path))
        
        # 大文件保护检查
        try:
            file_size = file_path_obj.stat().st_size
            if file_size > ANALYZE_FILE_MAX_BYTES:
                size_mb = file_size / (1024 * 1024)
                structure.error = (
                    f"文件过大（{size_mb:.1f}MB），无法分析。"
                    f"建议使用 read_file(start_line, end_line) 分段读取"
                )
                return structure
        except OSError:
            # 文件不存在或无法访问，让后续逻辑处理
            pass
        
        try:
            content = file_path_obj.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            # 语法错误时返回空结构
            return structure
        except Exception:
            return structure
        
        # 提取导入
        structure.imports = self._extract_imports(tree)
        
        # 提取符号
        for node in ast.iter_child_nodes(tree):
            symbol = self._node_to_symbol(node)
            if symbol:
                structure.symbols.append(symbol)
        
        return structure
    
    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """提取导入语句"""
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}" if module else alias.name)
        
        return imports
    
    def _node_to_symbol(
        self,
        node: ast.AST,
        parent_name: Optional[str] = None
    ) -> Optional[SymbolInfo]:
        """
        将 AST 节点转换为符号信息
        
        Args:
            node: AST 节点
            parent_name: 父符号名称
            
        Returns:
            SymbolInfo: 符号信息，不支持的节点返回 None
        """
        if isinstance(node, ast.ClassDef):
            return self._class_to_symbol(node)
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            symbol_type = SymbolType.METHOD if parent_name else SymbolType.FUNCTION
            return self._function_to_symbol(node, symbol_type, parent_name)
        elif isinstance(node, ast.Assign):
            # 仅处理模块级简单赋值
            if parent_name is None and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    return SymbolInfo(
                        name=target.id,
                        type=SymbolType.VARIABLE,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                        column_start=node.col_offset,
                        column_end=node.end_col_offset or 0,
                    )
        elif isinstance(node, ast.AnnAssign):
            # 带类型注解的赋值
            if parent_name is None and isinstance(node.target, ast.Name):
                return SymbolInfo(
                    name=node.target.id,
                    type=SymbolType.VARIABLE,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    column_start=node.col_offset,
                    column_end=node.end_col_offset or 0,
                )
        
        return None
    
    def _class_to_symbol(self, node: ast.ClassDef) -> SymbolInfo:
        """将类定义转换为符号"""
        # 提取基类
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(ast.unparse(base))
        
        signature = f"({', '.join(bases)})" if bases else None
        
        # 提取文档字符串
        docstring = ast.get_docstring(node)
        
        symbol = SymbolInfo(
            name=node.name,
            type=SymbolType.CLASS,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            column_start=node.col_offset,
            column_end=node.end_col_offset or 0,
            signature=signature,
            docstring=docstring[:200] if docstring else None,  # 截断长文档
        )
        
        # 提取方法
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = self._function_to_symbol(child, SymbolType.METHOD, node.name)
                if method:
                    symbol.children.append(method)
        
        return symbol
    
    def _function_to_symbol(
        self,
        node: ast.FunctionDef,
        symbol_type: SymbolType,
        parent_name: Optional[str] = None
    ) -> SymbolInfo:
        """将函数定义转换为符号"""
        # 构建签名
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                try:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                except Exception:
                    pass
            args.append(arg_str)
        
        # 添加 *args
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        
        # 添加 **kwargs
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        
        signature = f"({', '.join(args)})"
        
        # 添加返回类型
        if node.returns:
            try:
                signature += f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass
        
        # 提取文档字符串
        docstring = ast.get_docstring(node)
        
        return SymbolInfo(
            name=node.name,
            type=symbol_type,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            column_start=node.col_offset,
            column_end=node.end_col_offset or 0,
            signature=signature,
            docstring=docstring[:200] if docstring else None,
            parent=parent_name,
        )
    
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
        structure = self.extract_symbols(file_path)
        return structure.find_symbol(symbol_name)
    
    def get_imports(self, file_path: str) -> List[str]:
        """
        获取导入列表
        
        Args:
            file_path: 文件路径
            
        Returns:
            List[str]: 导入的模块列表
        """
        structure = self.extract_symbols(file_path)
        return structure.imports


__all__ = ["PythonSymbolExtractor"]
