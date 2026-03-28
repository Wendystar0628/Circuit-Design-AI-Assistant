# Test Circuit Analyzer
"""
电路分析器单元测试

测试 CircuitAnalyzer 的核心功能：
- 文件扫描
- 引用解析
- 依赖图构建
- 主电路检测
- 文件类型判断
"""

import pytest
from pathlib import Path
from domain.simulation.executor import CircuitAnalyzer, CircuitFileInfo, MainCircuitDetectionResult


class TestCircuitAnalyzer:
    """电路分析器测试类"""
    
    @pytest.fixture
    def analyzer(self):
        """创建分析器实例"""
        return CircuitAnalyzer()
    
    @pytest.fixture
    def test_project_path(self):
        """获取测试项目路径"""
        # 使用 Test 目录作为测试项目
        test_path = Path(__file__).parent.parent.parent / "Test"
        if not test_path.exists():
            pytest.skip("Test 目录不存在")
        return str(test_path)
    
    def test_scan_circuit_files(self, analyzer, test_project_path):
        """测试扫描电路文件"""
        circuit_files = analyzer.scan_circuit_files(test_project_path)
        
        # 验证返回类型
        assert isinstance(circuit_files, list)
        
        # 验证文件信息结构
        for file_info in circuit_files:
            assert isinstance(file_info, CircuitFileInfo)
            assert file_info.path
            assert file_info.abs_path.exists()
            assert file_info.file_type in ["main", "subcircuit", "parameter", "library", "unknown"]
            assert file_info.size_bytes > 0
    
    def test_parse_includes(self, analyzer, test_project_path):
        """测试解析引用语句"""
        # 先扫描文件
        circuit_files = analyzer.scan_circuit_files(test_project_path)
        
        if not circuit_files:
            pytest.skip("没有找到电路文件")
        
        # 测试第一个文件的引用解析
        test_file = circuit_files[0]
        includes = analyzer.parse_includes(str(test_file.abs_path))
        
        # 验证返回类型
        assert isinstance(includes, list)
        
        # 验证引用信息结构
        for inc in includes:
            assert inc.line_number > 0
            assert inc.statement_type in ["include", "lib"]
            assert inc.raw_path
            # resolved_path 和 exists 应该已经被设置
            assert hasattr(inc, 'resolved_path')
            assert hasattr(inc, 'exists')
    
    def test_build_dependency_graph(self, analyzer, test_project_path):
        """测试构建依赖关系图"""
        dep_graph = analyzer.build_dependency_graph(test_project_path)
        
        # 验证返回类型
        assert isinstance(dep_graph, dict)
        
        # 验证图结构
        for file_path, refs in dep_graph.items():
            assert isinstance(file_path, str)
            assert isinstance(refs, list)
            for ref in refs:
                assert isinstance(ref, str)
    
    def test_detect_main_circuit(self, analyzer, test_project_path):
        """测试检测主电路"""
        result = analyzer.detect_main_circuit(test_project_path)
        
        # 验证返回类型
        assert isinstance(result, MainCircuitDetectionResult)
        
        # 验证结果结构
        if result.main_circuit:
            assert isinstance(result.main_circuit, str)
            assert 0.0 <= result.confidence <= 1.0
        
        assert isinstance(result.candidates, list)
        assert isinstance(result.subcircuits, list)
        assert isinstance(result.parameters, list)
        assert isinstance(result.dependency_graph, dict)
    
    def test_get_circuit_type(self, analyzer, test_project_path):
        """测试判断文件类型"""
        # 先扫描文件
        circuit_files = analyzer.scan_circuit_files(test_project_path)
        
        if not circuit_files:
            pytest.skip("没有找到电路文件")
        
        # 测试每个文件的类型判断
        for file_info in circuit_files:
            file_type = analyzer.get_circuit_type(str(file_info.abs_path))
            assert file_type in ["main", "subcircuit", "parameter", "library", "unknown"]
            # 验证与扫描结果一致
            assert file_type == file_info.file_type
    
    def test_main_circuit_priority(self, analyzer, test_project_path):
        """测试主电路优先级计算"""
        result = analyzer.detect_main_circuit(test_project_path)
        
        # 如果有多个候选，验证优先级排序
        if len(result.candidates) > 1:
            priorities = [c['priority'] for c in result.candidates]
            # 验证优先级是降序排列的
            assert priorities == sorted(priorities, reverse=True)
    
    def test_file_type_classification(self, analyzer, test_project_path):
        """测试文件类型分类"""
        result = analyzer.detect_main_circuit(test_project_path)
        
        # 验证文件分类的互斥性
        all_files = set()
        
        if result.main_circuit:
            all_files.add(result.main_circuit)
        
        for candidate in result.candidates:
            all_files.add(candidate['path'])
        
        for subcircuit in result.subcircuits:
            all_files.add(subcircuit)
        
        for param in result.parameters:
            all_files.add(param)
        
        # 验证没有文件被重复分类
        total_count = (
            (1 if result.main_circuit else 0) +
            len(result.candidates) +
            len(result.subcircuits) +
            len(result.parameters)
        )
        assert len(all_files) == total_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
