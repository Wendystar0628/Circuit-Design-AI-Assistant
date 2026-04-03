# Test ExecutorRegistry
"""
执行器注册表测试

测试内容：
- 执行器注册和注销
- 按名称查询执行器
- 根据文件扩展名自动选择执行器
- 获取所有执行器和支持的扩展名
- 线程安全性
- 边界条件处理
"""

import pytest
from pathlib import Path
from typing import List, Optional, Dict, Any

from domain.simulation.executor.executor_registry import ExecutorRegistry
from domain.simulation.executor.simulation_executor import SimulationExecutor
from domain.simulation.models.simulation_result import SimulationResult


# ============================================================
# 测试用模拟执行器
# ============================================================

class MockSpiceExecutor(SimulationExecutor):
    """模拟 SPICE 执行器"""
    
    def get_name(self) -> str:
        return "mock_spice"
    
    def get_supported_extensions(self) -> List[str]:
        return [".cir", ".sp", ".spice"]
    
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        return SimulationResult(
            executor="mock_spice",
            file_path=file_path,
            analysis_type="ac",
            success=True,
            data=None,
            error=None,
            raw_output="Mock output",
            timestamp="2024-01-01T00:00:00",
            duration_seconds=1.0,
            version=1
        )
    
    def get_available_analyses(self) -> List[str]:
        return ["ac", "dc", "tran"]


class MockPythonExecutor(SimulationExecutor):
    """模拟 Python 执行器"""
    
    def get_name(self) -> str:
        return "mock_python"
    
    def get_supported_extensions(self) -> List[str]:
        return [".py"]
    
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        return SimulationResult(
            executor="mock_python",
            file_path=file_path,
            analysis_type="custom",
            success=True,
            data=None,
            error=None,
            raw_output="Mock Python output",
            timestamp="2024-01-01T00:00:00",
            duration_seconds=2.0,
            version=1
        )
    
    def get_available_analyses(self) -> List[str]:
        return ["custom"]


class MockDuplicateExecutor(SimulationExecutor):
    """模拟重复扩展名的执行器"""
    
    def get_name(self) -> str:
        return "mock_duplicate"
    
    def get_supported_extensions(self) -> List[str]:
        return [".cir", ".net"]  # .cir 与 SpiceExecutor 重复
    
    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None
    ) -> SimulationResult:
        return SimulationResult(
            executor="mock_duplicate",
            file_path=file_path,
            analysis_type="ac",
            success=True,
            data=None,
            error=None,
            raw_output="Mock duplicate output",
            timestamp="2024-01-01T00:00:00",
            duration_seconds=1.5,
            version=1
        )
    
    def get_available_analyses(self) -> List[str]:
        return ["ac"]


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def registry():
    """创建空的注册表实例"""
    return ExecutorRegistry()


@pytest.fixture
def populated_registry():
    """创建已注册执行器的注册表实例"""
    registry = ExecutorRegistry()
    registry.register(MockSpiceExecutor())
    registry.register(MockPythonExecutor())
    return registry


# ============================================================
# 测试：执行器注册
# ============================================================

def test_register_executor(registry):
    """测试注册执行器"""
    executor = MockSpiceExecutor()
    registry.register(executor)
    
    # 验证执行器已注册
    assert registry.has_executor("mock_spice")
    assert registry.get_executor("mock_spice") is executor


def test_register_multiple_executors(registry):
    """测试注册多个执行器"""
    spice_executor = MockSpiceExecutor()
    python_executor = MockPythonExecutor()
    
    registry.register(spice_executor)
    registry.register(python_executor)
    
    # 验证两个执行器都已注册
    assert registry.has_executor("mock_spice")
    assert registry.has_executor("mock_python")
    
    # 验证执行器数量
    assert len(registry.get_all_executors()) == 2


def test_register_none_executor(registry):
    """测试注册 None 执行器应抛出异常"""
    with pytest.raises(ValueError, match="executor 不能为 None"):
        registry.register(None)


def test_register_duplicate_name_overwrites(registry):
    """测试注册同名执行器会覆盖旧的"""
    executor1 = MockSpiceExecutor()
    executor2 = MockSpiceExecutor()
    
    registry.register(executor1)
    registry.register(executor2)
    
    # 验证只有一个执行器
    assert len(registry.get_all_executors()) == 1
    
    # 验证是新的执行器
    assert registry.get_executor("mock_spice") is executor2


# ============================================================
# 测试：执行器注销
# ============================================================

def test_unregister_executor(populated_registry):
    """测试注销执行器"""
    result = populated_registry.unregister("mock_spice")
    
    # 验证注销成功
    assert result is True
    assert not populated_registry.has_executor("mock_spice")
    
    # 验证其他执行器不受影响
    assert populated_registry.has_executor("mock_python")


def test_unregister_nonexistent_executor(registry):
    """测试注销不存在的执行器"""
    result = registry.unregister("nonexistent")
    
    # 验证注销失败
    assert result is False


def test_unregister_clears_extension_map(populated_registry):
    """测试注销执行器会清理扩展名映射"""
    populated_registry.unregister("mock_spice")
    
    # 验证 .cir 扩展名不再支持
    assert not populated_registry.can_handle_file("test.cir")
    
    # 验证 .py 扩展名仍然支持
    assert populated_registry.can_handle_file("test.py")


# ============================================================
# 测试：按名称查询执行器
# ============================================================

def test_get_executor_by_name(populated_registry):
    """测试按名称获取执行器"""
    executor = populated_registry.get_executor("mock_spice")
    
    assert executor is not None
    assert executor.get_name() == "mock_spice"


def test_get_nonexistent_executor(registry):
    """测试获取不存在的执行器"""
    executor = registry.get_executor("nonexistent")
    
    assert executor is None


# ============================================================
# 测试：根据文件扩展名自动选择执行器
# ============================================================

def test_get_executor_for_file_cir(populated_registry):
    """测试为 .cir 文件选择执行器"""
    executor = populated_registry.get_executor_for_file("amplifier.cir")
    
    assert executor is not None
    assert executor.get_name() == "mock_spice"


def test_get_executor_for_file_py(populated_registry):
    """测试为 .py 文件选择执行器"""
    executor = populated_registry.get_executor_for_file("simulation.py")
    
    assert executor is not None
    assert executor.get_name() == "mock_python"


def test_get_executor_for_file_case_insensitive(populated_registry):
    """测试扩展名匹配不区分大小写"""
    executor1 = populated_registry.get_executor_for_file("test.CIR")
    executor2 = populated_registry.get_executor_for_file("test.Py")
    
    assert executor1 is not None
    assert executor1.get_name() == "mock_spice"
    
    assert executor2 is not None
    assert executor2.get_name() == "mock_python"


def test_get_executor_for_file_with_path(populated_registry):
    """测试带路径的文件名"""
    executor = populated_registry.get_executor_for_file("/path/to/circuit.cir")
    
    assert executor is not None
    assert executor.get_name() == "mock_spice"


def test_get_executor_for_unsupported_file(populated_registry):
    """测试不支持的文件类型"""
    executor = populated_registry.get_executor_for_file("document.txt")
    
    assert executor is None


def test_get_executor_for_file_without_extension(populated_registry):
    """测试没有扩展名的文件"""
    executor = populated_registry.get_executor_for_file("makefile")
    
    assert executor is None


def test_get_executor_for_duplicate_extension(registry):
    """测试多个执行器支持同一扩展名时，返回第一个注册的"""
    spice_executor = MockSpiceExecutor()
    duplicate_executor = MockDuplicateExecutor()
    
    # 先注册 spice，再注册 duplicate
    registry.register(spice_executor)
    registry.register(duplicate_executor)
    
    # 验证返回第一个注册的执行器
    executor = registry.get_executor_for_file("test.cir")
    assert executor.get_name() == "mock_spice"


# ============================================================
# 测试：获取所有执行器和扩展名
# ============================================================

def test_get_all_executors(populated_registry):
    """测试获取所有执行器"""
    executors = populated_registry.get_all_executors()
    
    assert len(executors) == 2
    
    executor_names = {e.get_name() for e in executors}
    assert "mock_spice" in executor_names
    assert "mock_python" in executor_names


def test_get_all_executors_empty(registry):
    """测试空注册表"""
    executors = registry.get_all_executors()
    
    assert len(executors) == 0


def test_get_all_supported_extensions(populated_registry):
    """测试获取所有支持的扩展名"""
    extensions = populated_registry.get_all_supported_extensions()
    
    # 验证包含所有扩展名
    assert ".cir" in extensions
    assert ".sp" in extensions
    assert ".spice" in extensions
    assert ".py" in extensions


def test_get_all_supported_extensions_empty(registry):
    """测试空注册表的扩展名"""
    extensions = registry.get_all_supported_extensions()
    
    assert len(extensions) == 0


# ============================================================
# 测试：辅助方法
# ============================================================

def test_has_executor(populated_registry):
    """测试检查执行器是否存在"""
    assert populated_registry.has_executor("mock_spice") is True
    assert populated_registry.has_executor("mock_python") is True
    assert populated_registry.has_executor("nonexistent") is False


def test_can_handle_file(populated_registry):
    """测试检查是否能处理文件"""
    assert populated_registry.can_handle_file("test.cir") is True
    assert populated_registry.can_handle_file("test.py") is True
    assert populated_registry.can_handle_file("test.txt") is False


def test_clear(populated_registry):
    """测试清空注册表"""
    populated_registry.clear()
    
    # 验证所有执行器已清空
    assert len(populated_registry.get_all_executors()) == 0
    assert len(populated_registry.get_all_supported_extensions()) == 0
    
    # 验证查询返回 None
    assert populated_registry.get_executor("mock_spice") is None


# ============================================================
# 测试：注册表信息
# ============================================================

def test_get_registry_info(populated_registry):
    """测试获取注册表信息"""
    info = populated_registry.get_registry_info()
    
    # 验证信息结构
    assert "executor_count" in info
    assert "executors" in info
    assert "extension_map" in info
    
    # 验证执行器数量
    assert info["executor_count"] == 2
    
    # 验证执行器列表
    assert len(info["executors"]) == 2
    
    # 验证扩展名映射
    assert ".cir" in info["extension_map"]
    assert ".py" in info["extension_map"]


def test_str_representation(populated_registry):
    """测试字符串表示"""
    str_repr = str(populated_registry)
    
    assert "ExecutorRegistry" in str_repr
    assert "executors=2" in str_repr


def test_repr_representation(populated_registry):
    """测试详细表示"""
    repr_str = repr(populated_registry)
    
    assert "ExecutorRegistry" in repr_str
    assert "mock_spice" in repr_str or "mock_python" in repr_str


# ============================================================
# 测试：线程安全性
# ============================================================

def test_thread_safety_register(registry):
    """测试并发注册的线程安全性"""
    import threading
    
    def register_executor(name_suffix):
        class TempExecutor(SimulationExecutor):
            def get_name(self):
                return f"temp_{name_suffix}"
            
            def get_supported_extensions(self):
                return [f".t{name_suffix}"]
            
            def execute(self, file_path, analysis_config=None):
                pass
            
            def get_available_analyses(self):
                return []
        
        registry.register(TempExecutor())
    
    # 创建多个线程并发注册
    threads = []
    for i in range(10):
        thread = threading.Thread(target=register_executor, args=(i,))
        threads.append(thread)
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    # 验证所有执行器都已注册
    assert len(registry.get_all_executors()) == 10


def test_thread_safety_query(populated_registry):
    """测试并发查询的线程安全性"""
    import threading
    
    results = []
    
    def query_executor():
        executor = populated_registry.get_executor_for_file("test.cir")
        results.append(executor is not None)
    
    # 创建多个线程并发查询
    threads = []
    for _ in range(20):
        thread = threading.Thread(target=query_executor)
        threads.append(thread)
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    # 验证所有查询都成功
    assert all(results)
    assert len(results) == 20


# ============================================================
# 测试：边界条件
# ============================================================

def test_empty_extension_list(registry):
    """测试注册不支持任何扩展名的执行器"""
    class EmptyExecutor(SimulationExecutor):
        def get_name(self):
            return "empty"
        
        def get_supported_extensions(self):
            return []
        
        def execute(self, file_path, analysis_config=None):
            pass
        
        def get_available_analyses(self):
            return []
    
    registry.register(EmptyExecutor())
    
    # 验证执行器已注册
    assert registry.has_executor("empty")
    
    # 验证没有添加扩展名映射
    assert len(registry.get_all_supported_extensions()) == 0


def test_multiple_dots_in_filename(populated_registry):
    """测试文件名包含多个点的情况"""
    executor = populated_registry.get_executor_for_file("my.circuit.v1.cir")
    
    assert executor is not None
    assert executor.get_name() == "mock_spice"


def test_hidden_file(populated_registry):
    """测试隐藏文件（以点开头）"""
    executor = populated_registry.get_executor_for_file(".hidden.cir")
    
    assert executor is not None
    assert executor.get_name() == "mock_spice"
