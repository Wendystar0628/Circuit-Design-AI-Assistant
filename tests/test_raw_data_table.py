# Tests for RawDataTable
"""
原始数据表格测试

测试内容：
- RawDataTableModel 数据加载和缓存
- 虚拟滚动行为
- 跳转和搜索功能
"""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np

from domain.simulation.data.waveform_data_service import TableData, TableRow
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_simulation_result():
    """创建模拟仿真结果"""
    # 创建测试数据
    time = np.linspace(0, 1e-3, 1000)
    v_out = np.sin(2 * np.pi * 1000 * time)
    v_in = np.cos(2 * np.pi * 1000 * time)
    
    data = SimulationData(
        time=time,
        signals={"V(out)": v_out, "V(in)": v_in}
    )
    
    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        success=True,
        data=data,
        timestamp="2026-01-06T10:00:00",
    )


@pytest.fixture
def mock_table_data():
    """创建模拟表格数据"""
    rows = [
        TableRow(index=i, x_value=i * 1e-6, values={"V(out)": np.sin(i * 0.1), "V(in)": np.cos(i * 0.1)})
        for i in range(100)
    ]
    
    return TableData(
        rows=rows,
        total_rows=1000,
        start_index=0,
        signal_names=["V(out)", "V(in)"],
        x_label="Time (s)"
    )


# ============================================================
# RawDataTableModel Tests
# ============================================================

class TestRawDataTableModel:
    """RawDataTableModel 测试"""
    
    def test_initial_state(self):
        """测试初始状态"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        assert model.rowCount() == 0
        assert model.columnCount() == 1  # 只有 X 轴列
        assert model.total_rows == 0
        assert model.signal_names == []
    
    def test_load_result(self, mock_simulation_result, mock_table_data):
        """测试加载仿真结果"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        # Mock 数据服务
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            
            model.load_result(mock_simulation_result)
            
            assert model.total_rows == 1000
            assert model.signal_names == ["V(out)", "V(in)"]
            assert model.x_label == "Time (s)"
            assert model.columnCount() == 3  # X + 2 signals
    
    def test_clear(self, mock_simulation_result, mock_table_data):
        """测试清空数据"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        model.clear()
        
        assert model.rowCount() == 0
        assert model.total_rows == 0
        assert model.signal_names == []
    
    def test_data_retrieval(self, mock_simulation_result, mock_table_data):
        """测试数据获取"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        from PyQt6.QtCore import Qt
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 测试获取 X 轴值
        index = model.index(0, 0)
        value = model.data(index, Qt.ItemDataRole.DisplayRole)
        assert value is not None
        
        # 测试获取信号值
        index = model.index(0, 1)
        value = model.data(index, Qt.ItemDataRole.DisplayRole)
        assert value is not None
    
    def test_header_data(self, mock_simulation_result, mock_table_data):
        """测试表头数据"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        from PyQt6.QtCore import Qt
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 水平表头
        header0 = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        assert header0 == "Time (s)"
        
        header1 = model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        assert header1 == "V(out)"
    
    def test_get_row_for_x_value(self, mock_simulation_result, mock_table_data):
        """测试 X 轴值查找"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 查找存在的 X 轴值
        row = model.get_row_for_x_value(0.0)
        assert row == 0
        
        row = model.get_row_for_x_value(1e-6)
        assert row == 1
    
    def test_search_value(self, mock_simulation_result, mock_table_data):
        """测试值搜索"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 搜索 X 轴值
        row = model.search_value(0, 0.0, tolerance=1e-9)
        assert row == 0
    
    def test_value_formatting(self):
        """测试数值格式化"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        # 小数值使用科学计数法
        formatted = model._format_value(1e-9)
        assert "e" in formatted.lower()
        
        # 大数值使用科学计数法
        formatted = model._format_value(1e9)
        assert "e" in formatted.lower()
        
        # 普通数值
        formatted = model._format_value(1.5)
        assert formatted == "1.5"
    
    def test_get_row_data(self, mock_simulation_result, mock_table_data):
        """测试获取行数据"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 获取第一行数据
        row_data = model.get_row_data(0)
        assert row_data is not None
        assert row_data.index == 0
        assert "V(out)" in row_data.values
    
    def test_get_column_values(self, mock_simulation_result, mock_table_data):
        """测试获取列值"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 获取 X 轴列的值
        values = model.get_column_values(0, 0, 10)
        assert len(values) == 10
        assert values[0] == 0.0


# ============================================================
# RawDataTable Widget Tests (without qtbot)
# ============================================================

class TestRawDataTableWidget:
    """RawDataTable 组件测试（不依赖 qtbot）"""
    
    def test_model_creation(self):
        """测试模型创建"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        assert model is not None
        assert model.total_rows == 0
    
    def test_cache_management(self, mock_simulation_result, mock_table_data):
        """测试缓存管理"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        model = RawDataTableModel()
        
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = mock_table_data
            model.load_result(mock_simulation_result)
        
        # 验证缓存已填充
        assert len(model._cache) > 0
        assert len(model._cache) <= 200  # 不超过缓存限制


# ============================================================
# Performance Tests
# ============================================================

class TestRawDataTablePerformance:
    """性能测试"""
    
    def test_large_dataset_model(self):
        """测试大数据集模型"""
        from presentation.panels.simulation.raw_data_table import RawDataTableModel
        
        # 创建大数据集
        large_rows = [
            TableRow(
                index=i,
                x_value=i * 1e-9,
                values={"V(out)": float(i), "V(in)": float(i * 2)}
            )
            for i in range(100)  # 只返回 100 行，但声明有 100 万行
        ]
        
        large_table_data = TableData(
            rows=large_rows,
            total_rows=1_000_000,  # 100 万行
            start_index=0,
            signal_names=["V(out)", "V(in)"],
            x_label="Time (s)"
        )
        
        model = RawDataTableModel()
        
        # Mock 数据服务
        with patch.object(model, '_data_service') as mock_service:
            mock_service.get_table_data.return_value = large_table_data
            
            # 加载应该很快（虚拟滚动）
            model.load_result(MagicMock())
            
            # 验证总行数正确
            assert model.total_rows == 1_000_000
            
            # 但缓存只有部分数据
            assert len(model._cache) <= 200  # CHUNK_SIZE * BUFFER_MULTIPLIER
