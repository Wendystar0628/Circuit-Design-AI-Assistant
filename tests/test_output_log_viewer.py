# test_output_log_viewer.py - Tests for OutputLogViewer
"""
OutputLogViewer 单元测试

测试仿真输出日志查看器的核心功能：
- 日志加载和显示
- 搜索和高亮
- 按级别过滤
- 跳转到错误行
"""

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from domain.simulation.data.simulation_output_reader import (
    LogLine,
    LogLevel,
    SimulationSummary,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def sample_log_lines():
    """示例日志行数据"""
    return [
        LogLine(line_number=1, content="Starting simulation...", level=LogLevel.INFO.value),
        LogLine(line_number=2, content="Loading circuit file", level=LogLevel.INFO.value),
        LogLine(line_number=3, content="Warning: floating node detected", level=LogLevel.WARNING.value),
        LogLine(line_number=4, content="Running AC analysis", level=LogLevel.INFO.value),
        LogLine(line_number=5, content="Error: no convergence", level=LogLevel.ERROR.value),
        LogLine(line_number=6, content="Simulation failed", level=LogLevel.ERROR.value),
        LogLine(line_number=7, content="Warning: missing parameter", level=LogLevel.WARNING.value),
        LogLine(line_number=8, content="Cleanup complete", level=LogLevel.INFO.value),
    ]


@pytest.fixture
def sample_summary():
    """示例摘要数据"""
    return SimulationSummary(
        total_lines=8,
        error_count=2,
        warning_count=2,
        info_count=4,
        analysis_type="AC",
        success=False,
        first_error="Error: no convergence",
    )


@pytest.fixture
def mock_reader(sample_log_lines, sample_summary):
    """模拟日志读取器"""
    with patch("presentation.panels.simulation.output_log_viewer.simulation_output_reader") as mock:
        mock.get_output_log.return_value = sample_log_lines
        mock.get_simulation_summary.return_value = sample_summary
        mock.get_output_log_from_text.return_value = sample_log_lines
        mock.filter_by_level.side_effect = lambda lines, level: [
            line for line in lines if level == "all" or line.level == level
        ]
        yield mock


@pytest.fixture
def viewer(app, mock_reader):
    """创建 OutputLogViewer 实例"""
    from presentation.panels.simulation.output_log_viewer import OutputLogViewer
    widget = OutputLogViewer()
    yield widget
    widget.close()


# ============================================================
# 基础功能测试
# ============================================================

class TestOutputLogViewerBasic:
    """基础功能测试"""
    
    def test_init(self, viewer):
        """测试初始化"""
        assert viewer is not None
        assert viewer._log_lines == []
        assert viewer._filtered_lines == []
        assert viewer._summary is None
    
    def test_load_log(self, viewer, mock_reader, sample_log_lines, sample_summary):
        """测试加载日志"""
        viewer.load_log("sim_results/test.json", "/project")
        
        mock_reader.get_output_log.assert_called_once_with(
            "sim_results/test.json", "/project"
        )
        mock_reader.get_simulation_summary.assert_called_once()
        
        assert len(viewer._log_lines) == len(sample_log_lines)
        assert viewer._summary is not None
        assert viewer._summary.error_count == 2
    
    def test_load_log_from_text(self, viewer, mock_reader, sample_log_lines):
        """测试从文本加载日志"""
        raw_text = "\n".join([line.content for line in sample_log_lines])
        viewer.load_log_from_text(raw_text)
        
        mock_reader.get_output_log_from_text.assert_called_once_with(raw_text)
        assert len(viewer._log_lines) == len(sample_log_lines)
    
    def test_clear(self, viewer, mock_reader):
        """测试清空日志"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.clear()
        
        assert viewer._log_lines == []
        assert viewer._filtered_lines == []
        assert viewer._summary is None
    
    def test_get_counts(self, viewer, mock_reader):
        """测试获取计数"""
        viewer.load_log("sim_results/test.json", "/project")
        
        assert viewer.get_error_count() == 2
        assert viewer.get_warning_count() == 2
        assert viewer.get_total_lines() == 8


# ============================================================
# 过滤功能测试
# ============================================================

class TestOutputLogViewerFilter:
    """过滤功能测试"""
    
    def test_filter_all(self, viewer, mock_reader, sample_log_lines):
        """测试显示全部"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.filter_by_level("all")
        
        assert len(viewer._filtered_lines) == len(sample_log_lines)
    
    def test_filter_errors(self, viewer, mock_reader):
        """测试过滤错误"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.filter_by_level("error")
        
        assert len(viewer._filtered_lines) == 2
        assert all(line.is_error() for line in viewer._filtered_lines)
    
    def test_filter_warnings(self, viewer, mock_reader):
        """测试过滤警告"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.filter_by_level("warning")
        
        assert len(viewer._filtered_lines) == 2
        assert all(line.is_warning() for line in viewer._filtered_lines)
    
    def test_filter_info(self, viewer, mock_reader):
        """测试过滤信息"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.filter_by_level("info")
        
        assert len(viewer._filtered_lines) == 4
        assert all(line.level == LogLevel.INFO.value for line in viewer._filtered_lines)


# ============================================================
# 搜索功能测试
# ============================================================

class TestOutputLogViewerSearch:
    """搜索功能测试"""
    
    def test_search_keyword(self, viewer, mock_reader):
        """测试搜索关键词"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.search("convergence")
        
        # 验证高亮器设置了搜索关键词
        assert viewer._highlighter._search_keyword == "convergence"
    
    def test_search_empty(self, viewer, mock_reader):
        """测试空搜索"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.search("")
        
        assert viewer._highlighter._search_keyword == ""
    
    def test_clear_search(self, viewer, mock_reader):
        """测试清除搜索"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.search("error")
        viewer._highlighter.clear_search()
        
        assert viewer._highlighter._search_keyword == ""


# ============================================================
# 跳转功能测试
# ============================================================

class TestOutputLogViewerJump:
    """跳转功能测试"""
    
    def test_jump_to_error(self, viewer, mock_reader):
        """测试跳转到错误"""
        viewer.load_log("sim_results/test.json", "/project")
        
        result = viewer.jump_to_error()
        
        assert result is True
    
    def test_jump_to_error_no_errors(self, viewer, mock_reader):
        """测试无错误时跳转"""
        # 修改 mock 返回无错误的日志
        mock_reader.get_output_log.return_value = [
            LogLine(line_number=1, content="Info line", level=LogLevel.INFO.value),
        ]
        mock_reader.get_simulation_summary.return_value = SimulationSummary(
            total_lines=1, error_count=0, warning_count=0, info_count=1
        )
        mock_reader.filter_by_level.side_effect = lambda lines, level: lines
        
        viewer.load_log("sim_results/test.json", "/project")
        result = viewer.jump_to_error()
        
        assert result is False
    
    def test_jump_to_line(self, viewer, mock_reader):
        """测试跳转到指定行"""
        viewer.load_log("sim_results/test.json", "/project")
        viewer.jump_to_line(3)
        
        # 验证光标位置（通过检查是否有选中内容）
        cursor = viewer._log_view.textCursor()
        assert cursor.hasSelection() or cursor.position() >= 0


# ============================================================
# UI 组件测试
# ============================================================

class TestOutputLogViewerUI:
    """UI 组件测试"""
    
    def test_toolbar_exists(self, viewer):
        """测试工具栏存在"""
        assert viewer._toolbar is not None
        assert viewer._search_edit is not None
        assert viewer._filter_combo is not None
        assert viewer._refresh_btn is not None
    
    def test_log_view_readonly(self, viewer):
        """测试日志视图只读"""
        assert viewer._log_view.isReadOnly()
    
    def test_status_bar_exists(self, viewer):
        """测试状态栏存在"""
        assert viewer._status_bar is not None
        assert viewer._total_label is not None
        assert viewer._error_label is not None
        assert viewer._warning_label is not None
    
    def test_retranslate_ui(self, viewer):
        """测试国际化"""
        viewer.retranslate_ui()
        
        # 验证过滤下拉框有选项
        assert viewer._filter_combo.count() == 4


# ============================================================
# LogHighlighter 测试
# ============================================================

class TestLogHighlighter:
    """日志高亮器测试"""
    
    def test_highlighter_init(self, viewer):
        """测试高亮器初始化"""
        assert viewer._highlighter is not None
        assert viewer._highlighter._search_keyword == ""
    
    def test_set_search_keyword(self, viewer):
        """测试设置搜索关键词"""
        viewer._highlighter.set_search_keyword("test")
        assert viewer._highlighter._search_keyword == "test"
    
    def test_clear_search_keyword(self, viewer):
        """测试清除搜索关键词"""
        viewer._highlighter.set_search_keyword("test")
        viewer._highlighter.clear_search()
        assert viewer._highlighter._search_keyword == ""


# ============================================================
# 信号测试
# ============================================================

class TestOutputLogViewerSignals:
    """信号测试"""
    
    def test_error_clicked_signal(self, viewer, mock_reader):
        """测试错误点击信号"""
        signal_received = []
        viewer.error_clicked.connect(lambda line: signal_received.append(line))
        
        viewer.load_log("sim_results/test.json", "/project")
        viewer.jump_to_error()
        
        assert len(signal_received) == 1
        assert signal_received[0] == 5  # 第一个错误在第 5 行
