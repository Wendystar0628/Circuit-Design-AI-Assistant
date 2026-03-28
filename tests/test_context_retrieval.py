# Test Context Retrieval Module
"""
上下文检索模块测试

使用标准 unittest 框架，不依赖 pytest。
测试内容：
- ContextSource 协议和数据类
- 各专职收集器
- ImplicitContextAggregator 聚合器
- ContextRetriever 门面类
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

# 添加项目根目录到 Python 路径
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ============================================================
# 测试辅助函数
# ============================================================

def run_async(coro):
    """运行异步函数的辅助方法"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def create_test_project(base_dir: Path) -> Path:
    """创建测试项目结构"""
    project_dir = base_dir / "test_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建 .circuit_ai 目录
    circuit_ai_dir = project_dir / ".circuit_ai"
    circuit_ai_dir.mkdir(exist_ok=True)
    
    # 创建 simulation_results 目录
    sim_results_dir = project_dir / ".circuit_ai" / "sim_results"
    sim_results_dir.mkdir(exist_ok=True)
    
    return project_dir


def create_test_circuit_file(project_dir: Path, filename: str = "test.cir") -> Path:
    """创建测试电路文件"""
    content = """* Test Amplifier Circuit
* Description: A simple inverting amplifier
* Author: Test

.subckt opamp in+ in- out vcc vee
* Operational amplifier model
R1 in+ 0 1MEG
R2 in- 0 1MEG
E1 out 0 in+ in- 100k
.ends opamp

* Main circuit
Vin input 0 AC 1
R1 input inv_in 10k
R2 inv_in output 100k
X1 0 inv_in output vcc vee opamp
Vcc vcc 0 15
Vee vee 0 -15

.ac dec 100 1 10MEG
.end
"""
    file_path = project_dir / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


def create_test_simulation_result(project_dir: Path) -> Path:
    """创建测试仿真结果文件"""
    result = {
        "timestamp": "2024-01-15T10:30:00",
        "analysis_type": "AC",
        "status": "success",
        "config": {
            "frequency_range": "1Hz - 10MHz",
            "temperature": "27°C"
        },
        "metrics": {
            "gain": 20.5,
            "bandwidth": 1500000,
            "phase_margin": 65.3,
            "input_impedance": 10000,
        }
    }
    
    sim_dir = project_dir / ".circuit_ai" / "sim_results"
    sim_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = sim_dir / "run_001.json"
    file_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return file_path


def create_test_design_goals(project_dir: Path) -> Path:
    """创建测试设计目标文件"""
    goals = {
        "description": "Inverting Amplifier Design",
        "goals": [
            {"name": "gain", "target": 20, "tolerance": "2", "priority": "high"},
            {"name": "bandwidth", "target": 1000000, "tolerance": "10%"},
            {"name": "phase_margin", "target": 60, "tolerance": "5"},
        ]
    }
    
    circuit_ai_dir = project_dir / ".circuit_ai"
    circuit_ai_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = circuit_ai_dir / "design_goals.json"
    file_path.write_text(json.dumps(goals, indent=2), encoding="utf-8")
    return file_path


# ============================================================
# 协议和数据类测试
# ============================================================

class TestContextSourceProtocol(unittest.TestCase):
    """测试上下文源协议和数据类"""
    
    def test_context_priority_ordering(self):
        """测试优先级枚举排序"""
        from domain.llm.context_retrieval.context_source_protocol import ContextPriority
        
        self.assertLess(ContextPriority.CRITICAL, ContextPriority.HIGH)
        self.assertLess(ContextPriority.HIGH, ContextPriority.MEDIUM)
        self.assertLess(ContextPriority.MEDIUM, ContextPriority.LOW)
    
    def test_collection_context_creation(self):
        """测试 CollectionContext 创建"""
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        ctx = CollectionContext(
            project_path="/test/project",
            circuit_file_path="test.cir",
            sim_result_path=".circuit_ai/sim_results/run_001.json",
        )
        
        self.assertEqual(ctx.project_path, "/test/project")
        self.assertEqual(ctx.circuit_file_path, "test.cir")
        self.assertEqual(ctx.design_goals_path, ".circuit_ai/design_goals.json")
    
    def test_collection_context_get_absolute_path(self):
        """测试相对路径转绝对路径"""
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        ctx = CollectionContext(project_path="/test/project")
        abs_path = ctx.get_absolute_path("subdir/file.txt")
        
        # 使用 Path 进行跨平台比较
        expected = str(Path("/test/project") / "subdir/file.txt")
        self.assertEqual(abs_path, expected)
    
    def test_context_result_empty(self):
        """测试空结果创建"""
        from domain.llm.context_retrieval.context_source_protocol import ContextResult
        
        result = ContextResult.empty("test_source")
        
        self.assertTrue(result.is_empty)
        self.assertEqual(result.source_name, "test_source")
        self.assertEqual(result.content, "")
        self.assertEqual(result.token_count, 0)
    
    def test_context_result_non_empty(self):
        """测试非空结果"""
        from domain.llm.context_retrieval.context_source_protocol import (
            ContextResult, ContextPriority
        )
        
        result = ContextResult(
            content="Test content",
            token_count=10,
            source_name="test",
            priority=ContextPriority.HIGH,
        )
        
        self.assertFalse(result.is_empty)
        self.assertEqual(result.priority, ContextPriority.HIGH)
    
    def test_build_collection_context(self):
        """测试从字典构建 CollectionContext"""
        from domain.llm.context_retrieval.context_source_protocol import (
            build_collection_context
        )
        
        state_context = {
            "circuit_file_path": "amp.cir",
            "sim_result_path": ".circuit_ai/sim_results/run_001.json",
            "error_context": "Test error",
        }
        
        ctx = build_collection_context("/project", state_context)
        
        self.assertEqual(ctx.project_path, "/project")
        self.assertEqual(ctx.circuit_file_path, "amp.cir")
        self.assertEqual(ctx.error_context, "Test error")


# ============================================================
# CircuitFileCollector 测试
# ============================================================

class TestCircuitFileCollector(unittest.TestCase):
    """测试电路文件收集器"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = create_test_project(cls.temp_dir)
        cls.circuit_file = create_test_circuit_file(cls.project_dir)
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_collect_circuit_file(self):
        """测试收集电路文件"""
        from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
        from domain.llm.context_retrieval.context_source_protocol import (
            CollectionContext, ContextPriority
        )
        
        collector = CircuitFileCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="test.cir",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertFalse(result.is_empty)
        self.assertEqual(result.source_name, "circuit_file")
        self.assertEqual(result.priority, ContextPriority.HIGH)
        self.assertIn("Test Amplifier Circuit", result.content)
        self.assertIn("opamp", result.content)
        self.assertGreater(result.token_count, 0)
    
    def test_collect_nonexistent_file(self):
        """测试收集不存在的文件"""
        from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = CircuitFileCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="nonexistent.cir",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertTrue(result.is_empty)
    
    def test_collect_no_path(self):
        """测试没有提供路径"""
        from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = CircuitFileCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path=None,
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertTrue(result.is_empty)
    
    def test_metadata_extraction(self):
        """测试元数据提取"""
        from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = CircuitFileCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="test.cir",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertIn("subcircuits", result.metadata)
        self.assertIn("opamp", result.metadata["subcircuits"])
    
    def test_get_priority(self):
        """测试优先级"""
        from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
        from domain.llm.context_retrieval.context_source_protocol import ContextPriority
        
        collector = CircuitFileCollector()
        self.assertEqual(collector.get_priority(), ContextPriority.HIGH)
    
    def test_get_source_name(self):
        """测试源名称"""
        from domain.llm.context_retrieval.circuit_file_collector import CircuitFileCollector
        
        collector = CircuitFileCollector()
        self.assertEqual(collector.get_source_name(), "circuit_file")


# ============================================================
# SimulationContextCollector 测试
# ============================================================

class TestSimulationContextCollector(unittest.TestCase):
    """测试仿真上下文收集器"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = create_test_project(cls.temp_dir)
        cls.sim_result_file = create_test_simulation_result(cls.project_dir)
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_collect_simulation_result(self):
        """测试收集仿真结果"""
        from domain.llm.context_retrieval.simulation_context_collector import (
            SimulationContextCollector
        )
        from domain.llm.context_retrieval.context_source_protocol import (
            CollectionContext, ContextPriority
        )
        
        collector = SimulationContextCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            sim_result_path=".circuit_ai/sim_results/run_001.json",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertFalse(result.is_empty)
        self.assertEqual(result.source_name, "simulation_context")
        self.assertEqual(result.priority, ContextPriority.HIGH)
        self.assertIn("Simulation Results", result.content)
        self.assertIn("gain", result.content)
        self.assertIn("bandwidth", result.content)
    
    def test_collect_with_error_context(self):
        """测试收集带错误上下文"""
        from domain.llm.context_retrieval.simulation_context_collector import (
            SimulationContextCollector
        )
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = SimulationContextCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            error_context="Simulation failed: convergence error",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertFalse(result.is_empty)
        self.assertIn("Simulation Error", result.content)
        self.assertIn("convergence error", result.content)
        self.assertTrue(result.metadata.get("has_error"))
    
    def test_collect_no_data(self):
        """测试没有数据时返回空"""
        from domain.llm.context_retrieval.simulation_context_collector import (
            SimulationContextCollector
        )
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = SimulationContextCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertTrue(result.is_empty)
    
    def test_metric_formatting(self):
        """测试指标格式化"""
        from domain.llm.context_retrieval.simulation_context_collector import (
            SimulationContextCollector
        )
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = SimulationContextCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            sim_result_path=".circuit_ai/sim_results/run_001.json",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        # 检查单位格式化
        self.assertIn("dB", result.content)  # gain 应该有 dB 单位


# ============================================================
# DesignGoalsCollector 测试
# ============================================================

class TestDesignGoalsCollector(unittest.TestCase):
    """测试设计目标收集器"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = create_test_project(cls.temp_dir)
        cls.goals_file = create_test_design_goals(cls.project_dir)
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_collect_design_goals(self):
        """测试收集设计目标"""
        from domain.llm.context_retrieval.design_goals_collector import DesignGoalsCollector
        from domain.llm.context_retrieval.context_source_protocol import (
            CollectionContext, ContextPriority
        )
        
        collector = DesignGoalsCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            design_goals_path=".circuit_ai/design_goals.json",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertFalse(result.is_empty)
        self.assertEqual(result.source_name, "design_goals")
        self.assertEqual(result.priority, ContextPriority.MEDIUM)
        self.assertIn("Design Goals", result.content)
        self.assertIn("gain", result.content)
        self.assertIn("bandwidth", result.content)
    
    def test_collect_with_progress(self):
        """测试带进度计算的收集"""
        from domain.llm.context_retrieval.design_goals_collector import DesignGoalsCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = DesignGoalsCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            design_goals_path=".circuit_ai/design_goals.json",
            last_metrics={
                "gain": 20.5,
                "bandwidth": 1500000,
                "phase_margin": 65,
            }
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertFalse(result.is_empty)
        self.assertIn("Progress", result.content)
        self.assertTrue(result.metadata.get("has_metrics"))
    
    def test_collect_no_file(self):
        """测试文件不存在"""
        from domain.llm.context_retrieval.design_goals_collector import DesignGoalsCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = DesignGoalsCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            design_goals_path="nonexistent.json",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        self.assertTrue(result.is_empty)
    
    def test_goal_priority_marking(self):
        """测试高优先级目标标记"""
        from domain.llm.context_retrieval.design_goals_collector import DesignGoalsCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = DesignGoalsCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            design_goals_path=".circuit_ai/design_goals.json",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        # gain 目标设置为 high priority
        self.assertIn("[HIGH]", result.content)


# ============================================================
# DiagnosticsCollector 测试
# ============================================================

class TestDiagnosticsCollector(unittest.TestCase):
    """测试诊断信息收集器"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = create_test_project(cls.temp_dir)
        cls.circuit_file = create_test_circuit_file(cls.project_dir)
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_collect_diagnostics(self):
        """测试收集诊断信息"""
        from domain.llm.context_retrieval.diagnostics_collector import DiagnosticsCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        collector = DiagnosticsCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="test.cir",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        # 测试文件语法正确，应该返回空结果或只有警告
        # 检查是否正确实现了 ContextSource 协议
        self.assertEqual(collector.get_source_name(), "diagnostics")
        self.assertEqual(collector.get_priority().value, 0)  # CRITICAL
    
    def test_syntax_error_detection(self):
        """测试语法错误检测"""
        from domain.llm.context_retrieval.diagnostics_collector import DiagnosticsCollector
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        # 创建有语法错误的文件
        bad_file = self.project_dir / "bad.cir"
        bad_file.write_text("""* Bad circuit
.subckt test a b
* Missing .ends
""", encoding="utf-8")
        
        collector = DiagnosticsCollector()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="bad.cir",
        )
        
        result = run_async(collector.collect_async(ctx))
        
        # 应该检测到未闭合的 .subckt
        self.assertFalse(result.is_empty)
        self.assertIn("syntax", result.content.lower())
        
        # 清理
        bad_file.unlink()
    
    def test_error_history_management(self):
        """测试错误历史管理"""
        from domain.llm.context_retrieval.diagnostics_collector import DiagnosticsCollector
        
        collector = DiagnosticsCollector()
        test_file = str(self.circuit_file)
        
        # 记录错误
        collector.record_error(test_file, "simulation", "Test error 1")
        collector.record_error(test_file, "simulation", "Test error 2")
        
        # 获取历史
        history = collector._get_error_history(test_file)
        self.assertEqual(len(history), 2)
        
        # 清除历史
        collector.clear_error_history(test_file)
        history = collector._get_error_history(test_file)
        self.assertEqual(len(history), 0)
    
    def test_diagnostics_context_result(self):
        """测试诊断信息返回 ContextResult"""
        from domain.llm.context_retrieval.diagnostics_collector import DiagnosticsCollector
        from domain.llm.context_retrieval.context_source_protocol import (
            CollectionContext, ContextResult, ContextPriority
        )
        
        collector = DiagnosticsCollector()
        
        # 测试协议方法
        self.assertEqual(collector.get_source_name(), "diagnostics")
        self.assertEqual(collector.get_priority(), ContextPriority.CRITICAL)
        
        # 测试空上下文返回空结果
        ctx = CollectionContext(
            project_path=str(self.project_dir),
        )
        result = run_async(collector.collect_async(ctx))
        
        # 应该返回 ContextResult 类型
        self.assertIsInstance(result, ContextResult)


# ============================================================
# ImplicitContextAggregator 测试
# ============================================================

class TestImplicitContextAggregator(unittest.TestCase):
    """测试隐式上下文聚合器"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = create_test_project(cls.temp_dir)
        cls.circuit_file = create_test_circuit_file(cls.project_dir)
        cls.sim_result = create_test_simulation_result(cls.project_dir)
        cls.design_goals = create_test_design_goals(cls.project_dir)
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_collect_all_context(self):
        """测试收集所有上下文"""
        from domain.llm.context_retrieval.implicit_context_aggregator import (
            ImplicitContextAggregator
        )
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        aggregator = ImplicitContextAggregator()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="test.cir",
            sim_result_path=".circuit_ai/sim_results/run_001.json",
            design_goals_path=".circuit_ai/design_goals.json",
        )
        
        results = run_async(aggregator.collect_async(ctx))
        
        # 应该有 4 个收集器的结果（包含 diagnostics）
        self.assertGreaterEqual(len(results), 3)
        
        # 检查各收集器的结果
        source_names = [r.source_name for r in results]
        self.assertIn("circuit_file", source_names)
        self.assertIn("simulation_context", source_names)
        self.assertIn("design_goals", source_names)
        # diagnostics 可能为空（如果没有错误）
    
    def test_results_sorted_by_priority(self):
        """测试结果按优先级排序"""
        from domain.llm.context_retrieval.implicit_context_aggregator import (
            ImplicitContextAggregator
        )
        from domain.llm.context_retrieval.context_source_protocol import CollectionContext
        
        aggregator = ImplicitContextAggregator()
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="test.cir",
            sim_result_path=".circuit_ai/sim_results/run_001.json",
            design_goals_path=".circuit_ai/design_goals.json",
        )
        
        results = run_async(aggregator.collect_async(ctx))
        
        # 验证按优先级排序（数值越小优先级越高）
        priorities = [r.priority.value for r in results]
        self.assertEqual(priorities, sorted(priorities))
    
    def test_register_collector(self):
        """测试注册自定义收集器"""
        from domain.llm.context_retrieval.implicit_context_aggregator import (
            ImplicitContextAggregator
        )
        from domain.llm.context_retrieval.context_source_protocol import (
            CollectionContext, ContextResult, ContextPriority
        )
        
        # 创建自定义收集器
        class CustomCollector:
            async def collect_async(self, context):
                return ContextResult(
                    content="Custom content",
                    token_count=10,
                    source_name="custom",
                    priority=ContextPriority.LOW,
                )
            
            def get_priority(self):
                return ContextPriority.LOW
            
            def get_source_name(self):
                return "custom"
        
        aggregator = ImplicitContextAggregator()
        aggregator.register_collector(CustomCollector())
        
        collectors = aggregator.get_registered_collectors()
        self.assertIn("custom", collectors)
    
    def test_unregister_collector(self):
        """测试注销收集器"""
        from domain.llm.context_retrieval.implicit_context_aggregator import (
            ImplicitContextAggregator
        )
        
        aggregator = ImplicitContextAggregator()
        initial_count = len(aggregator.get_registered_collectors())
        
        # 注销一个收集器
        result = aggregator.unregister_collector("circuit_file")
        self.assertTrue(result)
        
        # 验证数量减少
        self.assertEqual(
            len(aggregator.get_registered_collectors()),
            initial_count - 1
        )
    
    def test_collector_failure_isolation(self):
        """测试收集器失败隔离"""
        from domain.llm.context_retrieval.implicit_context_aggregator import (
            ImplicitContextAggregator
        )
        from domain.llm.context_retrieval.context_source_protocol import (
            CollectionContext, ContextPriority
        )
        
        # 创建会失败的收集器
        class FailingCollector:
            async def collect_async(self, context):
                raise RuntimeError("Intentional failure")
            
            def get_priority(self):
                return ContextPriority.LOW
            
            def get_source_name(self):
                return "failing"
        
        aggregator = ImplicitContextAggregator()
        aggregator.register_collector(FailingCollector())
        
        ctx = CollectionContext(
            project_path=str(self.project_dir),
            circuit_file_path="test.cir",
        )
        
        # 不应该抛出异常
        results = run_async(aggregator.collect_async(ctx))
        
        # 其他收集器应该正常工作
        self.assertGreater(len(results), 0)
    
    def test_get_status(self):
        """测试获取状态"""
        from domain.llm.context_retrieval.implicit_context_aggregator import (
            ImplicitContextAggregator
        )
        
        aggregator = ImplicitContextAggregator()
        status = aggregator.get_status()
        
        self.assertIn("collector_count", status)
        self.assertIn("collectors", status)
        self.assertEqual(status["collector_count"], 4)  # 默认 4 个收集器（含 diagnostics）


# ============================================================
# ContextRetriever 门面类测试
# ============================================================

class TestContextRetriever(unittest.TestCase):
    """测试上下文检索门面类"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = create_test_project(cls.temp_dir)
        cls.circuit_file = create_test_circuit_file(cls.project_dir)
        cls.sim_result = create_test_simulation_result(cls.project_dir)
        cls.design_goals = create_test_design_goals(cls.project_dir)
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_retrieve_async(self):
        """测试异步检索"""
        from domain.llm.context_retrieval.context_retriever import ContextRetriever
        
        retriever = ContextRetriever()
        state_context = {
            "circuit_file_path": "test.cir",
            "sim_result_path": ".circuit_ai/sim_results/run_001.json",
            "design_goals_path": ".circuit_ai/design_goals.json",
        }
        
        result = run_async(retriever.retrieve_async(
            message="Analyze the amplifier gain",
            project_path=str(self.project_dir),
            state_context=state_context,
            token_budget=2000,
        ))
        
        self.assertIsNotNone(result)
        self.assertGreater(len(result.implicit_results), 0)
        self.assertGreater(result.total_tokens, 0)
    
    def test_retrieve_sync(self):
        """测试同步检索"""
        from domain.llm.context_retrieval.context_retriever import ContextRetriever
        
        retriever = ContextRetriever()
        state_context = {
            "circuit_file_path": "test.cir",
        }
        
        result = retriever.retrieve(
            message="Check the circuit",
            project_path=str(self.project_dir),
            state_context=state_context,
        )
        
        self.assertIsNotNone(result)
    
    def test_keyword_extraction(self):
        """测试关键词提取"""
        from domain.llm.context_retrieval.context_retriever import ContextRetriever
        
        retriever = ContextRetriever()
        state_context = {
            "circuit_file_path": "test.cir",
        }
        
        result = run_async(retriever.retrieve_async(
            message="What is the gain of R1 and C1?",
            project_path=str(self.project_dir),
            state_context=state_context,
        ))
        
        self.assertIsNotNone(result.keywords)
    
    def test_error_history_management(self):
        """测试错误历史管理"""
        from domain.llm.context_retrieval.context_retriever import ContextRetriever
        
        retriever = ContextRetriever()
        test_file = str(self.circuit_file)
        
        # 记录错误
        retriever.record_error(test_file, "Test error")
        
        # 清除错误
        retriever.clear_error_history(test_file)
        
        # 不应抛出异常
        self.assertTrue(True)
    
    def test_retrieval_result_dataclass(self):
        """测试 RetrievalResult 数据类"""
        from domain.llm.context_retrieval.context_retriever import RetrievalResult
        
        result = RetrievalResult(
            path="test.cir",
            content="Test content",
            relevance=0.9,
            source="circuit_file",
            token_count=10,
        )
        
        result_dict = result.to_dict()
        self.assertEqual(result_dict["path"], "test.cir")
        self.assertEqual(result_dict["relevance"], 0.9)


# ============================================================
# KeywordExtractor 测试
# ============================================================

class TestKeywordExtractor(unittest.TestCase):
    """测试关键词提取器"""
    
    def test_extract_device_names(self):
        """测试器件名提取"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        # 测试各种器件类型
        message = "Check R1, R2, C1, L1, Q1, M1, D1, V1, I1, X1 values"
        devices = extractor.extract_device_names(message)
        
        self.assertIn("R1", devices)
        self.assertIn("R2", devices)
        self.assertIn("C1", devices)
        self.assertIn("L1", devices)
        self.assertIn("Q1", devices)
        self.assertIn("M1", devices)
        self.assertIn("D1", devices)
        self.assertIn("V1", devices)
        self.assertIn("I1", devices)
        self.assertIn("X1", devices)
        self.assertEqual(len(devices), 10)
    
    def test_extract_device_names_case_insensitive(self):
        """测试器件名提取不区分大小写"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Check r1, c2, l3"
        devices = extractor.extract_device_names(message)
        
        # 应该统一转为大写
        self.assertIn("R1", devices)
        self.assertIn("C2", devices)
        self.assertIn("L3", devices)
    
    def test_extract_node_names(self):
        """测试节点名提取"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Connect Vcc to Vin, Vout to GND, net_1 to n_out"
        nodes = extractor.extract_node_names(message)
        
        self.assertIn("Vcc", nodes)
        self.assertIn("Vin", nodes)
        self.assertIn("Vout", nodes)
        self.assertIn("GND", nodes)
        self.assertIn("net_1", nodes)
        self.assertIn("n_out", nodes)
    
    def test_extract_node_names_excludes_devices(self):
        """测试节点名提取排除器件名"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        # V1 是电压源，不应被识别为节点
        message = "V1 connects to Vout"
        nodes = extractor.extract_node_names(message)
        
        self.assertIn("Vout", nodes)
        self.assertNotIn("V1", nodes)
    
    def test_extract_file_names(self):
        """测试文件名提取"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Load amp.cir, include lib.sp and model.lib"
        files = extractor.extract_file_names(message)
        
        self.assertIn("amp.cir", files)
        self.assertIn("lib.sp", files)
        self.assertIn("model.lib", files)
    
    def test_extract_subcircuit_names(self):
        """测试子电路名提取"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        # 测试 .subckt 定义
        message = ".subckt opamp in+ in- out vcc vee"
        subcircuits = extractor.extract_subcircuit_names(message)
        
        self.assertIn("opamp", subcircuits)
    
    def test_extract_metric_keywords(self):
        """测试指标词提取"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Check the gain, bandwidth, and phase margin"
        metrics = extractor.extract_metric_keywords(message)
        
        self.assertIn("gain", metrics)
        self.assertIn("bandwidth", metrics)
        self.assertIn("phase", metrics)
        self.assertIn("margin", metrics)
    
    def test_extract_all_keywords(self):
        """测试完整关键词提取"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Analyze amp.cir: R1=10k, C1=100nF, check gain at Vout"
        keywords = extractor.extract(message)
        
        self.assertIn("R1", keywords.devices)
        self.assertIn("C1", keywords.devices)
        self.assertIn("amp.cir", keywords.files)
        self.assertIn("gain", keywords.metrics)
        self.assertIn("Vout", keywords.nodes)
    
    def test_generate_semantic_query(self):
        """测试语义查询生成"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Please analyze the gain of R1 in amp.cir"
        keywords = extractor.extract(message)
        semantic_query = extractor.generate_semantic_query(message, keywords)
        
        # 语义查询应该排除已提取的关键词和停用词
        self.assertNotIn("R1", semantic_query)
        self.assertNotIn("amp.cir", semantic_query)
        self.assertNotIn("gain", semantic_query)
        self.assertNotIn("Please", semantic_query)
        self.assertNotIn("the", semantic_query)
    
    def test_get_search_terms_priority(self):
        """测试搜索词优先级排序"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Check R1 in amp.cir, gain at Vout"
        keywords = extractor.extract(message)
        search_terms = extractor.get_search_terms(keywords)
        
        # 器件名应该在前面
        r1_index = search_terms.index("R1")
        file_index = search_terms.index("amp.cir")
        
        self.assertLess(r1_index, file_index)
    
    def test_extracted_keywords_to_dict(self):
        """测试 ExtractedKeywords.to_dict()"""
        from domain.llm.context_retrieval.keyword_extractor import ExtractedKeywords
        
        keywords = ExtractedKeywords(
            devices={"R1", "C1"},
            nodes={"Vout"},
            files={"amp.cir"},
            subcircuits=set(),
            metrics={"gain"},
            identifiers=set(),
        )
        
        result = keywords.to_dict()
        
        self.assertEqual(result["devices"], ["C1", "R1"])  # 排序后
        self.assertEqual(result["nodes"], ["Vout"])
        self.assertEqual(result["files"], ["amp.cir"])
        self.assertEqual(result["metrics"], ["gain"])
    
    def test_extracted_keywords_is_empty(self):
        """测试 ExtractedKeywords.is_empty()"""
        from domain.llm.context_retrieval.keyword_extractor import ExtractedKeywords
        
        empty_keywords = ExtractedKeywords()
        self.assertTrue(empty_keywords.is_empty())
        
        non_empty = ExtractedKeywords(devices={"R1"})
        self.assertFalse(non_empty.is_empty())
    
    def test_empty_message(self):
        """测试空消息处理"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        keywords = extractor.extract("")
        self.assertTrue(keywords.is_empty())
        
        keywords = extractor.extract("   ")
        self.assertTrue(keywords.is_empty())
    
    def test_identifiers_exclude_common_words(self):
        """测试标识符排除常见英文单词"""
        from domain.llm.context_retrieval.keyword_extractor import KeywordExtractor
        
        extractor = KeywordExtractor()
        
        message = "Please Check the Circuit and Analyze the Output"
        keywords = extractor.extract(message)
        
        # 常见英文单词不应出现在标识符中
        self.assertNotIn("Please", keywords.identifiers)
        self.assertNotIn("Check", keywords.identifiers)
        self.assertNotIn("Circuit", keywords.identifiers)
        self.assertNotIn("Analyze", keywords.identifiers)
        self.assertNotIn("Output", keywords.identifiers)


# ============================================================
# DependencyAnalyzer 测试
# ============================================================

class TestDependencyAnalyzer(unittest.TestCase):
    """测试电路依赖图分析器"""
    
    @classmethod
    def setUpClass(cls):
        """创建测试目录和文件"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.project_dir = cls.temp_dir / "test_project"
        cls.project_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建主电路文件
        cls.main_circuit = cls.project_dir / "main.cir"
        cls.main_circuit.write_text("""* Main Circuit
.include "subcircuits/opamp.cir"
.include "lib/models.lib"

Vin input 0 AC 1
R1 input inv_in 10k
X1 0 inv_in output vcc vee opamp

.ac dec 100 1 10MEG
.end
""", encoding="utf-8")
        
        # 创建子电路目录和文件
        subcircuits_dir = cls.project_dir / "subcircuits"
        subcircuits_dir.mkdir(exist_ok=True)
        
        cls.opamp_file = subcircuits_dir / "opamp.cir"
        cls.opamp_file.write_text("""* Operational Amplifier Subcircuit
.subckt opamp in+ in- out vcc vee
R1 in+ 0 1MEG
R2 in- 0 1MEG
E1 out 0 in+ in- 100k
.ends opamp
""", encoding="utf-8")
        
        # 创建库目录和文件
        lib_dir = cls.project_dir / "lib"
        lib_dir.mkdir(exist_ok=True)
        
        cls.models_file = lib_dir / "models.lib"
        cls.models_file.write_text("""* Model Library
.model NPN NPN(BF=100)
.model PNP PNP(BF=100)
""", encoding="utf-8")
        
        # 创建仿真结果文件
        sim_dir = cls.project_dir / ".circuit_ai" / "sim_results"
        sim_dir.mkdir(parents=True, exist_ok=True)
        
        cls.sim_result = sim_dir / "main_sim.json"
        cls.sim_result.write_text(json.dumps({
            "status": "success",
            "metrics": {"gain": 20.0}
        }), encoding="utf-8")
        
        # 创建设计目标文件
        circuit_ai_dir = cls.project_dir / ".circuit_ai"
        cls.design_goals = circuit_ai_dir / "main_goals.json"
        cls.design_goals.write_text(json.dumps({
            "gain_target": 20.0
        }), encoding="utf-8")
    
    @classmethod
    def tearDownClass(cls):
        """清理测试目录"""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
    
    def test_build_dependency_graph_async(self):
        """测试异步构建依赖图"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        graph = run_async(analyzer.build_dependency_graph_async(str(self.main_circuit)))
        
        self.assertEqual(graph.root, str(self.main_circuit))
        self.assertGreater(len(graph.nodes), 0)
        self.assertIn(str(self.main_circuit), graph.nodes)
    
    def test_dependency_parsing(self):
        """测试依赖解析"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        graph = run_async(analyzer.build_dependency_graph_async(str(self.main_circuit)))
        
        # 主文件应该有依赖
        main_node = graph.nodes.get(str(self.main_circuit))
        self.assertIsNotNone(main_node)
        self.assertGreater(len(main_node.dependencies), 0)
    
    def test_topological_sort(self):
        """测试拓扑排序"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        graph = run_async(analyzer.build_dependency_graph_async(str(self.main_circuit)))
        
        # 拓扑排序应该把依赖放在前面
        self.assertGreater(len(graph.order), 0)
        # 主文件应该在最后
        self.assertEqual(graph.order[-1], str(self.main_circuit))
    
    def test_get_all_dependencies(self):
        """测试获取所有依赖"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        # 先构建依赖图
        run_async(analyzer.build_dependency_graph_async(str(self.main_circuit)))
        
        # 获取依赖
        deps = analyzer.get_all_dependencies(str(self.main_circuit))
        
        # 不应包含主文件
        self.assertNotIn(str(self.main_circuit), deps)
    
    def test_get_dependency_content_async(self):
        """测试异步获取依赖内容"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        deps = run_async(analyzer.get_dependency_content_async(
            str(self.main_circuit),
            project_path=str(self.project_dir),
            max_depth=3,
        ))
        
        self.assertIsInstance(deps, list)
        # 每个依赖应该有 path, content, depth, mtime
        for dep in deps:
            self.assertIn("path", dep)
            self.assertIn("content", dep)
            self.assertIn("depth", dep)
            self.assertIn("mtime", dep)
    
    def test_subcircuit_extraction(self):
        """测试子电路提取"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        graph = run_async(analyzer.build_dependency_graph_async(str(self.opamp_file)))
        
        opamp_node = graph.nodes.get(str(self.opamp_file.resolve()))
        self.assertIsNotNone(opamp_node)
        self.assertIn("opamp", opamp_node.subcircuits)
    
    def test_cache_invalidation(self):
        """测试缓存失效"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        
        # 构建依赖图（会缓存）
        run_async(analyzer.build_dependency_graph_async(str(self.main_circuit)))
        
        # 失效缓存
        analyzer.invalidate_cache(str(self.main_circuit))
        
        # 缓存应该被清除
        self.assertNotIn(str(self.main_circuit), analyzer._cache)
    
    def test_clear_cache(self):
        """测试清除所有缓存"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        
        # 构建依赖图
        run_async(analyzer.build_dependency_graph_async(str(self.main_circuit)))
        
        # 清除所有缓存
        analyzer.clear_cache()
        
        self.assertEqual(len(analyzer._cache), 0)
    
    def test_get_associated_files_async(self):
        """测试异步获取关联文件"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        associated = run_async(analyzer.get_associated_files_async(
            str(self.main_circuit),
            str(self.project_dir),
        ))
        
        self.assertIn("simulation_result", associated)
        self.assertIn("design_goals", associated)
        
        # 应该找到仿真结果
        if associated["simulation_result"]:
            path, mtime = associated["simulation_result"]
            self.assertIn("main_sim.json", path)
            self.assertGreater(mtime, 0)
    
    def test_depth_based_content_injection(self):
        """测试基于深度的内容注入策略"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        deps = run_async(analyzer.get_dependency_content_async(
            str(self.main_circuit),
            project_path=str(self.project_dir),
            max_depth=3,
        ))
        
        # 检查深度 1 的依赖应该有完整内容
        for dep in deps:
            if dep["depth"] <= 1:
                # 直接依赖应该有完整内容
                self.assertGreater(len(dep["content"]), 0)
    
    def test_mtime_sorting(self):
        """测试按修改时间排序"""
        from domain.llm.context_retrieval.dependency_analyzer import DependencyAnalyzer
        
        analyzer = DependencyAnalyzer()
        deps = run_async(analyzer.get_dependency_content_async(
            str(self.main_circuit),
            project_path=str(self.project_dir),
            max_depth=3,
        ))
        
        if len(deps) > 1:
            # 应该按修改时间降序排列
            mtimes = [d.get("mtime", 0) for d in deps]
            self.assertEqual(mtimes, sorted(mtimes, reverse=True))


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    # 设置事件循环
    if not asyncio.get_event_loop().is_running():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # 运行测试
    unittest.main(verbosity=2)
