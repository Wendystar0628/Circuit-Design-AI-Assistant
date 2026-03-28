# Test File Analyzer - 文件分析模块测试
"""
测试轻量级文件分析模块

运行方式：
    cd circuit_design_ai
    python -m pytest tests/test_file_analyzer.py -v
    
或直接运行：
    cd circuit_design_ai
    python tests/test_file_analyzer.py
"""

import sys
import tempfile
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 直接导入，避免依赖其他模块
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
from infrastructure.file_intelligence.analysis.file_analyzer import FileAnalyzer


class TestSpiceSymbolExtractor:
    """测试 SPICE 符号提取器"""
    
    def test_extract_subcircuit(self):
        """测试子电路提取"""
        content = """
* Test SPICE file
.subckt opamp in+ in- out vcc vee
R1 in+ 1 10k
R2 in- 1 10k
.ends opamp
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = SpiceSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            assert len(structure.symbols) == 1
            subckt = structure.symbols[0]
            assert subckt.name == "opamp"
            assert subckt.type == SymbolType.SUBCIRCUIT
            assert subckt.signature == "(in+, in-, out, vcc, vee)"
            assert subckt.line_start == 3
            assert subckt.line_end == 6
        finally:
            os.unlink(temp_path)
    
    def test_extract_parameters(self):
        """测试参数提取"""
        content = """
.param R1=1k
.param C1=1u
.param GAIN=100
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = SpiceSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            params = [s for s in structure.symbols if s.type == SymbolType.PARAMETER]
            assert len(params) == 3
            assert {p.name for p in params} == {"R1", "C1", "GAIN"}
        finally:
            os.unlink(temp_path)
    
    def test_extract_model(self):
        """测试模型提取"""
        content = """
.model NPN1 NPN (BF=100)
.model DIODE1 D (IS=1e-14)
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = SpiceSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            models = [s for s in structure.symbols if s.type == SymbolType.MODEL]
            assert len(models) == 2
            assert {m.name for m in models} == {"NPN1", "DIODE1"}
            assert models[0].metadata.get("model_type") == "NPN"
        finally:
            os.unlink(temp_path)
    
    def test_extract_includes(self):
        """测试 include 提取"""
        content = """
.include models/transistors.lib
.lib "opamps.lib"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = SpiceSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            assert len(structure.includes) == 2
            assert "models/transistors.lib" in structure.includes
            assert "opamps.lib" in structure.includes
        finally:
            os.unlink(temp_path)
    
    def test_nested_param_in_subcircuit(self):
        """测试子电路内的参数"""
        content = """
.subckt amp in out
.param GAIN=10
R1 in out {GAIN}k
.ends amp
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = SpiceSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            assert len(structure.symbols) == 1
            subckt = structure.symbols[0]
            assert subckt.name == "amp"
            assert len(subckt.children) == 1
            assert subckt.children[0].name == "GAIN"
            assert subckt.children[0].parent == "amp"
        finally:
            os.unlink(temp_path)


class TestPythonSymbolExtractor:
    """测试 Python 符号提取器"""
    
    def test_extract_class(self):
        """测试类提取"""
        content = '''
class MyClass(BaseClass):
    """A test class"""
    
    def method1(self):
        pass
    
    def method2(self, arg1: str) -> int:
        pass
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = PythonSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            assert len(structure.symbols) == 1
            cls = structure.symbols[0]
            assert cls.name == "MyClass"
            assert cls.type == SymbolType.CLASS
            assert cls.signature == "(BaseClass)"
            assert len(cls.children) == 2
            assert cls.children[0].name == "method1"
            assert cls.children[0].type == SymbolType.METHOD
        finally:
            os.unlink(temp_path)
    
    def test_extract_function(self):
        """测试函数提取"""
        content = '''
def my_function(arg1: str, arg2: int = 0) -> bool:
    """A test function"""
    return True

async def async_func():
    pass
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = PythonSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            funcs = [s for s in structure.symbols if s.type == SymbolType.FUNCTION]
            assert len(funcs) == 2
            assert funcs[0].name == "my_function"
            assert "arg1: str" in funcs[0].signature
            assert "-> bool" in funcs[0].signature
        finally:
            os.unlink(temp_path)
    
    def test_extract_variable(self):
        """测试变量提取"""
        content = '''
MY_CONSTANT = 42
typed_var: str = "hello"
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = PythonSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            vars = [s for s in structure.symbols if s.type == SymbolType.VARIABLE]
            assert len(vars) == 2
            assert {v.name for v in vars} == {"MY_CONSTANT", "typed_var"}
        finally:
            os.unlink(temp_path)
    
    def test_extract_imports(self):
        """测试导入提取"""
        content = '''
import os
from pathlib import Path
from typing import List, Optional
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            extractor = PythonSymbolExtractor()
            structure = extractor.extract_symbols(temp_path)
            
            assert "os" in structure.imports
            assert "pathlib.Path" in structure.imports
        finally:
            os.unlink(temp_path)


class TestFileAnalyzer:
    """测试文件分析器门面类"""
    
    def test_supports_spice(self):
        """测试 SPICE 文件支持"""
        analyzer = FileAnalyzer()
        assert analyzer.supports("test.cir")
        assert analyzer.supports("test.sp")
        assert analyzer.supports("test.spice")
        assert analyzer.supports("test.net")
        assert analyzer.supports("test.ckt")
    
    def test_supports_python(self):
        """测试 Python 文件支持"""
        analyzer = FileAnalyzer()
        assert analyzer.supports("test.py")
        assert analyzer.supports("test.pyw")
    
    def test_unsupported_file(self):
        """测试不支持的文件类型"""
        analyzer = FileAnalyzer()
        assert not analyzer.supports("test.txt")
        assert not analyzer.supports("test.js")
        assert not analyzer.supports("test.cpp")
    
    def test_get_symbols_flattened(self):
        """测试符号列表展平"""
        content = '''
class MyClass:
    def method1(self):
        pass

def standalone():
    pass
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            analyzer = FileAnalyzer()
            symbols = analyzer.get_symbols(temp_path)
            
            # 应该包含 class、method、function
            names = {s.name for s in symbols}
            assert "MyClass" in names
            assert "method1" in names
            assert "standalone" in names
        finally:
            os.unlink(temp_path)
    
    def test_find_symbol(self):
        """测试符号查找"""
        content = """
.subckt opamp in out
.ends opamp

.subckt buffer in out
.ends buffer
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            analyzer = FileAnalyzer()
            
            symbol = analyzer.find_symbol(temp_path, "opamp")
            assert symbol is not None
            assert symbol.name == "opamp"
            
            symbol = analyzer.find_symbol(temp_path, "buffer")
            assert symbol is not None
            assert symbol.name == "buffer"
            
            symbol = analyzer.find_symbol(temp_path, "nonexistent")
            assert symbol is None
        finally:
            os.unlink(temp_path)


class TestFileStructure:
    """测试 FileStructure 数据类"""
    
    def test_find_symbol(self):
        """测试符号查找"""
        structure = FileStructure(file_path="test.py")
        structure.symbols = [
            SymbolInfo(name="ClassA", type=SymbolType.CLASS, line_start=1, children=[
                SymbolInfo(name="method1", type=SymbolType.METHOD, line_start=2),
            ]),
            SymbolInfo(name="func1", type=SymbolType.FUNCTION, line_start=10),
        ]
        
        assert structure.find_symbol("ClassA") is not None
        assert structure.find_symbol("method1") is not None
        assert structure.find_symbol("func1") is not None
        assert structure.find_symbol("nonexistent") is None
    
    def test_get_symbols_by_type(self):
        """测试按类型获取符号"""
        structure = FileStructure(file_path="test.py")
        structure.symbols = [
            SymbolInfo(name="ClassA", type=SymbolType.CLASS, line_start=1, children=[
                SymbolInfo(name="method1", type=SymbolType.METHOD, line_start=2),
            ]),
            SymbolInfo(name="func1", type=SymbolType.FUNCTION, line_start=10),
        ]
        
        classes = structure.get_symbols_by_type(SymbolType.CLASS)
        assert len(classes) == 1
        
        methods = structure.get_symbols_by_type(SymbolType.METHOD)
        assert len(methods) == 1
        
        functions = structure.get_symbols_by_type(SymbolType.FUNCTION)
        assert len(functions) == 1


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Testing File Analyzer Module")
    print("=" * 60)
    
    # SPICE 提取器测试
    print("\n--- SpiceSymbolExtractor Tests ---")
    spice_tests = TestSpiceSymbolExtractor()
    spice_tests.test_extract_subcircuit()
    print("✓ test_extract_subcircuit")
    spice_tests.test_extract_parameters()
    print("✓ test_extract_parameters")
    spice_tests.test_extract_model()
    print("✓ test_extract_model")
    spice_tests.test_extract_includes()
    print("✓ test_extract_includes")
    spice_tests.test_nested_param_in_subcircuit()
    print("✓ test_nested_param_in_subcircuit")
    
    # Python 提取器测试
    print("\n--- PythonSymbolExtractor Tests ---")
    python_tests = TestPythonSymbolExtractor()
    python_tests.test_extract_class()
    print("✓ test_extract_class")
    python_tests.test_extract_function()
    print("✓ test_extract_function")
    python_tests.test_extract_variable()
    print("✓ test_extract_variable")
    python_tests.test_extract_imports()
    print("✓ test_extract_imports")
    
    # FileAnalyzer 测试
    print("\n--- FileAnalyzer Tests ---")
    analyzer_tests = TestFileAnalyzer()
    analyzer_tests.test_supports_spice()
    print("✓ test_supports_spice")
    analyzer_tests.test_supports_python()
    print("✓ test_supports_python")
    analyzer_tests.test_unsupported_file()
    print("✓ test_unsupported_file")
    analyzer_tests.test_get_symbols_flattened()
    print("✓ test_get_symbols_flattened")
    analyzer_tests.test_find_symbol()
    print("✓ test_find_symbol")
    
    # FileStructure 测试
    print("\n--- FileStructure Tests ---")
    structure_tests = TestFileStructure()
    structure_tests.test_find_symbol()
    print("✓ test_find_symbol")
    structure_tests.test_get_symbols_by_type()
    print("✓ test_get_symbols_by_type")
    
    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
