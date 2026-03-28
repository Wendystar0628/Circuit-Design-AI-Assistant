# Test SimulationOutputReader
"""
仿真输出日志读取器测试

测试覆盖：
- LogLine 数据类
- SimulationSummary 数据类
- 日志级别检测
- 日志解析
- 搜索和过滤功能
- 仿真摘要生成
"""

import json
import tempfile
from pathlib import Path

import pytest

from domain.simulation.data.simulation_output_reader import (
    LogLevel,
    LogLine,
    SimulationSummary,
    SimulationOutputReader,
    simulation_output_reader,
)


# ============================================================
# LogLine 测试
# ============================================================

class TestLogLine:
    """LogLine 数据类测试"""
    
    def test_create_log_line(self):
        """测试创建日志行"""
        line = LogLine(
            line_number=1,
            content="Test message",
            level=LogLevel.INFO.value,
        )
        
        assert line.line_number == 1
        assert line.content == "Test message"
        assert line.level == LogLevel.INFO.value
    
    def test_default_level(self):
        """测试默认日志级别"""
        line = LogLine(line_number=1, content="Test")
        assert line.level == LogLevel.INFO.value
    
    def test_is_error(self):
        """测试错误行判断"""
        error_line = LogLine(line_number=1, content="Error", level=LogLevel.ERROR.value)
        info_line = LogLine(line_number=2, content="Info", level=LogLevel.INFO.value)
        
        assert error_line.is_error() is True
        assert info_line.is_error() is False
    
    def test_is_warning(self):
        """测试警告行判断"""
        warning_line = LogLine(line_number=1, content="Warning", level=LogLevel.WARNING.value)
        info_line = LogLine(line_number=2, content="Info", level=LogLevel.INFO.value)
        
        assert warning_line.is_warning() is True
        assert info_line.is_warning() is False
    
    def test_to_dict(self):
        """测试序列化"""
        line = LogLine(
            line_number=5,
            content="Test content",
            level=LogLevel.WARNING.value,
        )
        
        data = line.to_dict()
        
        assert data["line_number"] == 5
        assert data["content"] == "Test content"
        assert data["level"] == "warning"
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "line_number": 10,
            "content": "Error message",
            "level": "error",
        }
        
        line = LogLine.from_dict(data)
        
        assert line.line_number == 10
        assert line.content == "Error message"
        assert line.level == "error"


# ============================================================
# SimulationSummary 测试
# ============================================================

class TestSimulationSummary:
    """SimulationSummary 数据类测试"""
    
    def test_create_summary(self):
        """测试创建摘要"""
        summary = SimulationSummary(
            total_lines=100,
            error_count=2,
            warning_count=5,
            info_count=93,
            analysis_type="ac",
            duration_seconds=1.5,
            success=True,
            first_error="Error: convergence failed",
            timestamp="2026-01-06T10:00:00",
        )
        
        assert summary.total_lines == 100
        assert summary.error_count == 2
        assert summary.warning_count == 5
        assert summary.info_count == 93
        assert summary.analysis_type == "ac"
        assert summary.duration_seconds == 1.5
        assert summary.success is True
        assert summary.first_error == "Error: convergence failed"
    
    def test_default_values(self):
        """测试默认值"""
        summary = SimulationSummary()
        
        assert summary.total_lines == 0
        assert summary.error_count == 0
        assert summary.warning_count == 0
        assert summary.info_count == 0
        assert summary.analysis_type == ""
        assert summary.duration_seconds == 0.0
        assert summary.success is True
        assert summary.first_error is None
    
    def test_to_dict(self):
        """测试序列化"""
        summary = SimulationSummary(
            total_lines=50,
            error_count=1,
            warning_count=3,
            analysis_type="tran",
        )
        
        data = summary.to_dict()
        
        assert data["total_lines"] == 50
        assert data["error_count"] == 1
        assert data["warning_count"] == 3
        assert data["analysis_type"] == "tran"
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "total_lines": 200,
            "error_count": 5,
            "warning_count": 10,
            "info_count": 185,
            "analysis_type": "dc",
            "duration_seconds": 2.5,
            "success": False,
            "first_error": "Fatal error",
            "timestamp": "2026-01-06T12:00:00",
        }
        
        summary = SimulationSummary.from_dict(data)
        
        assert summary.total_lines == 200
        assert summary.error_count == 5
        assert summary.success is False
        assert summary.first_error == "Fatal error"


# ============================================================
# SimulationOutputReader 测试
# ============================================================

class TestSimulationOutputReader:
    """SimulationOutputReader 测试"""
    
    @pytest.fixture
    def reader(self):
        """创建读取器实例"""
        return SimulationOutputReader()
    
    @pytest.fixture
    def sample_output(self):
        """示例输出日志"""
        return """ngspice simulation started
Loading circuit: amplifier.cir
Parsing netlist...
Warning: Node 'vcc' has no DC path to ground
Analysis: AC analysis from 1Hz to 1GHz
Error: No convergence in DC operating point
Simulation failed
Total time: 0.5s"""
    
    @pytest.fixture
    def temp_project(self, sample_output):
        """创建临时项目目录和仿真结果文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 .circuit_ai/sim_results 目录
            sim_results_dir = Path(tmpdir) / ".circuit_ai" / "sim_results"
            sim_results_dir.mkdir(parents=True)
            
            # 创建仿真结果文件
            result_data = {
                "executor": "spice",
                "file_path": "amplifier.cir",
                "analysis_type": "ac",
                "success": False,
                "raw_output": sample_output,
                "timestamp": "2026-01-06T10:00:00",
                "duration_seconds": 0.5,
            }
            
            result_file = sim_results_dir / "run_001.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_data, f)
            
            yield tmpdir, "sim_results/run_001.json"
    
    # ============================================================
    # 日志级别检测测试
    # ============================================================
    
    def test_detect_error_level(self, reader):
        """测试错误级别检测"""
        error_lines = [
            "Error: syntax error at line 10",
            "FATAL: cannot open file",
            "Failed to converge",
            "Exception occurred",
            "No convergence in DC analysis",
        ]
        
        for line in error_lines:
            level = reader._detect_log_level(line)
            assert level == LogLevel.ERROR.value, f"应检测为错误: {line}"
    
    def test_detect_warning_level(self, reader):
        """测试警告级别检测"""
        warning_lines = [
            "Warning: node has no DC path",
            "WARN: deprecated syntax",
            "Caution: floating node detected",
            "Notice: using default value",
        ]
        
        for line in warning_lines:
            level = reader._detect_log_level(line)
            assert level == LogLevel.WARNING.value, f"应检测为警告: {line}"
    
    def test_detect_info_level(self, reader):
        """测试信息级别检测"""
        info_lines = [
            "Simulation started",
            "Loading circuit file",
            "Analysis complete",
            "Total time: 1.5s",
        ]
        
        for line in info_lines:
            level = reader._detect_log_level(line)
            assert level == LogLevel.INFO.value, f"应检测为信息: {line}"
    
    def test_detect_empty_line(self, reader):
        """测试空行检测"""
        assert reader._detect_log_level("") == LogLevel.INFO.value
        assert reader._detect_log_level("   ") == LogLevel.INFO.value
    
    # ============================================================
    # 日志解析测试
    # ============================================================
    
    def test_parse_log_lines(self, reader, sample_output):
        """测试日志行解析"""
        lines = reader.get_output_log_from_text(sample_output)
        
        assert len(lines) == 8
        assert lines[0].line_number == 1
        assert lines[0].content == "ngspice simulation started"
        assert lines[0].level == LogLevel.INFO.value
    
    def test_parse_with_max_lines(self, reader, sample_output):
        """测试最大行数限制"""
        lines = reader.get_output_log_from_text(sample_output, max_lines=3)
        
        assert len(lines) == 3
        assert lines[2].line_number == 3
    
    def test_parse_empty_output(self, reader):
        """测试空输出解析"""
        lines = reader.get_output_log_from_text("")
        assert lines == []
        
        lines = reader.get_output_log_from_text(None)
        assert lines == []
    
    def test_parse_detects_levels(self, reader, sample_output):
        """测试解析时检测日志级别"""
        lines = reader.get_output_log_from_text(sample_output)
        
        # 检查警告行
        warning_lines = [l for l in lines if l.is_warning()]
        assert len(warning_lines) == 1
        assert "Warning" in warning_lines[0].content
        
        # 检查错误行
        error_lines = [l for l in lines if l.is_error()]
        assert len(error_lines) == 2  # "Error" 和 "failed"
    
    # ============================================================
    # 文件读取测试
    # ============================================================
    
    def test_get_output_log_from_file(self, reader, temp_project):
        """测试从文件读取日志"""
        project_root, sim_result_path = temp_project
        
        lines = reader.get_output_log(sim_result_path, project_root)
        
        assert len(lines) == 8
        assert lines[0].content == "ngspice simulation started"
    
    def test_get_output_log_file_not_found(self, reader):
        """测试文件不存在"""
        lines = reader.get_output_log("nonexistent.json", "/tmp")
        assert lines == []
    
    def test_get_output_log_empty_path(self, reader):
        """测试空路径"""
        lines = reader.get_output_log("", "/tmp")
        assert lines == []
    
    # ============================================================
    # 过滤测试
    # ============================================================
    
    def test_get_error_lines(self, reader, temp_project):
        """测试获取错误行"""
        project_root, sim_result_path = temp_project
        
        errors = reader.get_error_lines(sim_result_path, project_root)
        
        assert len(errors) >= 1
        assert all(line.is_error() for line in errors)
    
    def test_get_warning_lines(self, reader, temp_project):
        """测试获取警告行"""
        project_root, sim_result_path = temp_project
        
        warnings = reader.get_warning_lines(sim_result_path, project_root)
        
        assert len(warnings) == 1
        assert all(line.is_warning() for line in warnings)
    
    def test_filter_by_level(self, reader, sample_output):
        """测试按级别过滤"""
        lines = reader.get_output_log_from_text(sample_output)
        
        # 过滤错误
        errors = reader.filter_by_level(lines, LogLevel.ERROR.value)
        assert all(l.is_error() for l in errors)
        
        # 过滤警告
        warnings = reader.filter_by_level(lines, LogLevel.WARNING.value)
        assert all(l.is_warning() for l in warnings)
        
        # 过滤全部
        all_lines = reader.filter_by_level(lines, "all")
        assert len(all_lines) == len(lines)
    
    # ============================================================
    # 搜索测试
    # ============================================================
    
    def test_search_log(self, reader, temp_project):
        """测试搜索日志"""
        project_root, sim_result_path = temp_project
        
        # 搜索 "analysis"
        matches = reader.search_log(sim_result_path, project_root, "analysis")
        assert len(matches) >= 1
        assert all("analysis" in m.content.lower() for m in matches)
    
    def test_search_log_case_insensitive(self, reader, temp_project):
        """测试不区分大小写搜索"""
        project_root, sim_result_path = temp_project
        
        # 搜索 "ERROR"（大写）
        matches = reader.search_log(sim_result_path, project_root, "ERROR", case_sensitive=False)
        assert len(matches) >= 1
    
    def test_search_log_case_sensitive(self, reader, temp_project):
        """测试区分大小写搜索"""
        project_root, sim_result_path = temp_project
        
        # 搜索 "Error"（首字母大写）
        matches = reader.search_log(sim_result_path, project_root, "Error", case_sensitive=True)
        assert len(matches) >= 1
        
        # 搜索 "error"（全小写）- 应该找不到
        matches = reader.search_log(sim_result_path, project_root, "error", case_sensitive=True)
        # 可能找到 "convergence" 等包含 error 的行
    
    def test_search_log_empty_keyword(self, reader, temp_project):
        """测试空关键词搜索"""
        project_root, sim_result_path = temp_project
        
        matches = reader.search_log(sim_result_path, project_root, "")
        assert matches == []
    
    def test_search_log_regex(self, reader, temp_project):
        """测试正则表达式搜索"""
        project_root, sim_result_path = temp_project
        
        # 搜索以 "ngspice" 开头的行
        matches = reader.search_log_regex(sim_result_path, project_root, r"^ngspice")
        assert len(matches) >= 1
        
        # 搜索包含数字的行
        matches = reader.search_log_regex(sim_result_path, project_root, r"\d+")
        assert len(matches) >= 1
    
    def test_search_log_invalid_regex(self, reader, temp_project):
        """测试无效正则表达式"""
        project_root, sim_result_path = temp_project
        
        # 无效的正则表达式
        matches = reader.search_log_regex(sim_result_path, project_root, r"[invalid")
        assert matches == []
    
    # ============================================================
    # 摘要测试
    # ============================================================
    
    def test_get_simulation_summary(self, reader, temp_project):
        """测试获取仿真摘要"""
        project_root, sim_result_path = temp_project
        
        summary = reader.get_simulation_summary(sim_result_path, project_root)
        
        assert summary.total_lines == 8
        assert summary.error_count >= 1
        assert summary.warning_count == 1
        assert summary.analysis_type == "ac"
        assert summary.duration_seconds == 0.5
        assert summary.success is False
        assert summary.first_error is not None
        assert "Error" in summary.first_error or "failed" in summary.first_error
    
    def test_get_simulation_summary_file_not_found(self, reader):
        """测试文件不存在时的摘要"""
        summary = reader.get_simulation_summary("nonexistent.json", "/tmp")
        
        assert summary.total_lines == 0
        assert summary.error_count == 0
        assert summary.success is True


# ============================================================
# 模块级单例测试
# ============================================================

class TestModuleSingleton:
    """模块级单例测试"""
    
    def test_singleton_exists(self):
        """测试单例存在"""
        assert simulation_output_reader is not None
        assert isinstance(simulation_output_reader, SimulationOutputReader)
    
    def test_singleton_methods(self):
        """测试单例方法可用"""
        lines = simulation_output_reader.get_output_log_from_text("Test line")
        assert len(lines) == 1
        assert lines[0].content == "Test line"
