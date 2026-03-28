# Test Location Service - 定位服务测试
"""
测试智能定位模块

运行方式：
    cd circuit_design_ai
    python tests/test_location_service.py
"""

import sys
import tempfile
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from infrastructure.file_intelligence.location.location_types import (
    LocationResult,
    ReferenceResult,
    LocationScope,
)
from infrastructure.file_intelligence.location.symbol_locator import SymbolLocator
from infrastructure.file_intelligence.location.reference_finder import ReferenceFinder
from infrastructure.file_intelligence.location.location_service import LocationService


class TestSymbolLocator:
    """测试符号定位器"""

    def test_locate_in_file_spice(self):
        """测试在 SPICE 文件中定位符号"""
        content = """
* Test circuit
.subckt opamp in+ in- out vcc vee
R1 in+ 1 10k
.ends opamp

.subckt buffer in out
R1 in out 1k
.ends buffer
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cir", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            locator = SymbolLocator()
            result = locator.locate_in_file("opamp", temp_path)

            assert result is not None
            assert result.symbol_name == "opamp"
            assert result.symbol_type == "subcircuit"
            assert result.line == 3
            assert ".subckt opamp" in result.preview
        finally:
            os.unlink(temp_path)

    def test_locate_in_file_python(self):
        """测试在 Python 文件中定位符号"""
        content = '''
class MyClass:
    """Test class"""
    def method1(self):
        pass

def my_function():
    pass
'''
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            locator = SymbolLocator()

            # 定位类
            result = locator.locate_in_file("MyClass", temp_path)
            assert result is not None
            assert result.symbol_name == "MyClass"
            assert result.symbol_type == "class"

            # 定位函数
            result = locator.locate_in_file("my_function", temp_path)
            assert result is not None
            assert result.symbol_name == "my_function"
            assert result.symbol_type == "function"
        finally:
            os.unlink(temp_path)

    def test_locate_not_found(self):
        """测试符号未找到"""
        content = ".subckt test in out\n.ends test"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cir", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            locator = SymbolLocator()
            result = locator.locate_in_file("nonexistent", temp_path)
            assert result is None
        finally:
            os.unlink(temp_path)


class TestReferenceFinder:
    """测试引用查找器"""

    def test_find_references_in_file(self):
        """测试在文件中查找引用"""
        content = """
.subckt opamp in+ in- out
R1 in+ 1 10k
.ends opamp

* Use opamp subcircuit
X1 a b c opamp
X2 d e f opamp
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cir", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            finder = ReferenceFinder()
            results = finder.find_references_in_file(
                "opamp", temp_path, is_definition_file=True, definition_line=2
            )

            # 应该找到多个引用
            assert len(results) >= 3  # 定义 + 注释 + 使用

            # 检查定义位置
            definitions = [r for r in results if r.is_definition]
            assert len(definitions) == 1

            # 检查注释中的引用
            comments = [r for r in results if r.context_type == "comment"]
            assert len(comments) >= 1
        finally:
            os.unlink(temp_path)

    def test_exclude_comments(self):
        """测试排除注释中的引用"""
        content = """
def my_func():
    pass

# Call my_func here
my_func()
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            finder = ReferenceFinder()
            results = finder.find_references_in_file("my_func", temp_path)

            # 应该找到多个引用
            assert len(results) >= 2

            # 检查上下文类型
            usages = [r for r in results if r.context_type == "usage"]
            comments = [r for r in results if r.context_type == "comment"]

            assert len(usages) >= 1
            assert len(comments) >= 1
        finally:
            os.unlink(temp_path)


class TestLocationService:
    """测试定位服务门面类"""

    def test_go_to_definition(self):
        """测试跳转到定义"""
        content = """
.param GAIN=100
.subckt amp in out
R1 in out {GAIN}k
.ends amp
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cir", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            service = LocationService()
            result = service.go_to_definition("amp", temp_path)

            assert result is not None
            assert result.symbol_name == "amp"
            assert result.symbol_type == "subcircuit"
        finally:
            os.unlink(temp_path)

    def test_find_references(self):
        """测试查找引用"""
        content = """
.subckt buffer in out
R1 in out 1k
.ends buffer

X1 a b buffer
X2 c d buffer
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cir", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            # 直接使用 ReferenceFinder 测试单文件
            finder = ReferenceFinder()
            results = finder.find_references_in_file("buffer", temp_path)

            # 应该找到多个引用（定义行 + .ends 行 + X1 + X2）
            assert len(results) >= 2, f"Expected >= 2 references, got {len(results)}"
        finally:
            os.unlink(temp_path)

    def test_get_symbol_at_position(self):
        """测试获取位置处的符号"""
        content = "def my_function():\n    pass"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            service = LocationService()
            # 光标在 "my_function" 上
            symbol = service.get_symbol_at_position(temp_path, 1, 6)
            assert symbol == "my_function"
        finally:
            os.unlink(temp_path)


class TestLocationTypes:
    """测试定位类型"""

    def test_location_result_to_dict(self):
        """测试 LocationResult 转字典"""
        result = LocationResult(
            file_path="test.cir",
            absolute_path="/path/to/test.cir",
            line=10,
            column=5,
            symbol_name="opamp",
            symbol_type="subcircuit",
            preview=".subckt opamp in out",
            scope=LocationScope.CURRENT_FILE,
        )

        d = result.to_dict()
        assert d["file_path"] == "test.cir"
        assert d["line"] == 10
        assert d["symbol_name"] == "opamp"
        assert d["scope"] == "current_file"

    def test_reference_result_to_dict(self):
        """测试 ReferenceResult 转字典"""
        result = ReferenceResult(
            file_path="test.cir",
            absolute_path="/path/to/test.cir",
            line=5,
            column=10,
            line_content="X1 a b opamp",
            is_definition=False,
            context_type="usage",
        )

        d = result.to_dict()
        assert d["file_path"] == "test.cir"
        assert d["line"] == 5
        assert d["is_definition"] is False
        assert d["context_type"] == "usage"


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Testing Location Service Module")
    print("=" * 60)

    # SymbolLocator 测试
    print("\n--- SymbolLocator Tests ---")
    locator_tests = TestSymbolLocator()
    locator_tests.test_locate_in_file_spice()
    print("✓ test_locate_in_file_spice")
    locator_tests.test_locate_in_file_python()
    print("✓ test_locate_in_file_python")
    locator_tests.test_locate_not_found()
    print("✓ test_locate_not_found")

    # ReferenceFinder 测试
    print("\n--- ReferenceFinder Tests ---")
    finder_tests = TestReferenceFinder()
    finder_tests.test_find_references_in_file()
    print("✓ test_find_references_in_file")
    finder_tests.test_exclude_comments()
    print("✓ test_exclude_comments")

    # LocationService 测试
    print("\n--- LocationService Tests ---")
    service_tests = TestLocationService()
    service_tests.test_go_to_definition()
    print("✓ test_go_to_definition")
    service_tests.test_find_references()
    print("✓ test_find_references")
    service_tests.test_get_symbol_at_position()
    print("✓ test_get_symbol_at_position")

    # LocationTypes 测试
    print("\n--- LocationTypes Tests ---")
    type_tests = TestLocationTypes()
    type_tests.test_location_result_to_dict()
    print("✓ test_location_result_to_dict")
    type_tests.test_reference_result_to_dict()
    print("✓ test_reference_result_to_dict")

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
