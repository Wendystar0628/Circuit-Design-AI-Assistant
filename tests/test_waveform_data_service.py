# Test Waveform Data Service
"""
波形数据服务测试

测试内容：
- WaveformData 数据类
- TableData 数据类
- WaveformDataService 核心方法
- LRU 缓存机制
"""

import numpy as np
import pytest

from domain.simulation.data.waveform_data_service import (
    WaveformData,
    TableRow,
    TableData,
    WaveformDataService,
    LRUCache,
)
from domain.simulation.models.simulation_result import (
    SimulationResult,
    SimulationData,
    create_success_result,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_sim_data() -> SimulationData:
    """创建示例仿真数据"""
    time = np.linspace(0, 1e-3, 10000)  # 1ms, 10000 点
    return SimulationData(
        time=time,
        signals={
            "V(out)": np.sin(2 * np.pi * 1000 * time),
            "V(in)": np.cos(2 * np.pi * 1000 * time),
            "I(r1)": 0.001 * np.sin(2 * np.pi * 1000 * time + 0.5),
        },
    )


@pytest.fixture
def sample_result(sample_sim_data: SimulationData) -> SimulationResult:
    """创建示例仿真结果"""
    return create_success_result(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        data=sample_sim_data,
        metrics={"rise_time": "10us"},
    )


@pytest.fixture
def ac_sim_data() -> SimulationData:
    """创建 AC 分析仿真数据"""
    frequency = np.logspace(1, 6, 5000)  # 10Hz - 1MHz, 5000 点
    v_out = 10 / (1 + 1j * (frequency / 10000))
    v_in = np.ones_like(frequency, dtype=np.complex128)
    return SimulationData(
        frequency=frequency,
        signals={
            "V(out)": v_out,
            "V(out)_mag": np.abs(v_out),
            "V(out)_phase": np.angle(v_out, deg=True),
            "V(out)_real": np.real(v_out),
            "V(out)_imag": np.imag(v_out),
            "V(in)": v_in,
            "V(in)_mag": np.abs(v_in),
            "V(in)_phase": np.angle(v_in, deg=True),
            "V(in)_real": np.real(v_in),
            "V(in)_imag": np.imag(v_in),
        },
        signal_types={
            "V(out)": "voltage",
            "V(out)_mag": "voltage",
            "V(out)_phase": "voltage",
            "V(out)_real": "voltage",
            "V(out)_imag": "voltage",
            "V(in)": "voltage",
            "V(in)_mag": "voltage",
            "V(in)_phase": "voltage",
            "V(in)_real": "voltage",
            "V(in)_imag": "voltage",
        },
    )


@pytest.fixture
def ac_result(ac_sim_data: SimulationData) -> SimulationResult:
    """创建 AC 分析仿真结果"""
    return create_success_result(
        executor="spice",
        file_path="test.cir",
        analysis_type="ac",
        data=ac_sim_data,
    )


@pytest.fixture
def service() -> WaveformDataService:
    """创建服务实例"""
    return WaveformDataService(cache_size=16)


# ============================================================
# WaveformData 测试
# ============================================================

class TestWaveformData:
    """WaveformData 数据类测试"""
    
    def test_basic_creation(self):
        """测试基本创建"""
        x = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([0.0, 1.0, 0.0, -1.0])
        
        data = WaveformData(
            signal_name="V(out)",
            x_data=x,
            y_data=y,
        )
        
        assert data.signal_name == "V(out)"
        assert data.point_count == 4
        assert data.x_range == (0.0, 3.0)
        assert data.y_range == (-1.0, 1.0)
        assert data.is_downsampled is False
        assert data.original_points == 4
    
    def test_downsampled_flag(self):
        """测试降采样标志"""
        x = np.array([0.0, 1.0])
        y = np.array([0.0, 1.0])
        
        data = WaveformData(
            signal_name="V(out)",
            x_data=x,
            y_data=y,
            is_downsampled=True,
            original_points=1000,
        )
        
        assert data.is_downsampled is True
        assert data.original_points == 1000
        assert data.point_count == 2
    
    def test_empty_data(self):
        """测试空数据"""
        x = np.array([])
        y = np.array([])
        
        data = WaveformData(
            signal_name="V(out)",
            x_data=x,
            y_data=y,
        )
        
        assert data.point_count == 0
        assert data.x_range == (0.0, 0.0)
        assert data.y_range == (0.0, 0.0)


# ============================================================
# TableData 测试
# ============================================================

class TestTableData:
    """TableData 数据类测试"""
    
    def test_basic_creation(self):
        """测试基本创建"""
        rows = [
            TableRow(index=0, x_value=0.0, values={"V(out)": 1.0}),
            TableRow(index=1, x_value=0.1, values={"V(out)": 2.0}),
        ]
        
        table = TableData(
            rows=rows,
            total_rows=100,
            start_index=0,
            signal_names=["V(out)"],
            x_label="Time (s)",
        )
        
        assert len(table.rows) == 2
        assert table.total_rows == 100
        assert table.start_index == 0
        assert table.signal_names == ["V(out)"]
        assert table.x_label == "Time (s)"
    
    def test_row_access(self):
        """测试行数据访问"""
        row = TableRow(
            index=5,
            x_value=0.5,
            values={"V(out)": 1.5, "I(r1)": 0.001},
        )
        
        assert row.index == 5
        assert row.x_value == 0.5
        assert row.values["V(out)"] == 1.5
        assert row.values["I(r1)"] == 0.001


# ============================================================
# LRUCache 测试
# ============================================================

class TestLRUCache:
    """LRU 缓存测试"""
    
    def test_basic_put_get(self):
        """测试基本存取"""
        from domain.simulation.data.resolution_pyramid import build_pyramid
        
        cache = LRUCache(max_size=3)
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 0.0])
        pyramid = build_pyramid(x, y)
        
        cache.put("key1", pyramid)
        result = cache.get("key1")
        
        assert result is not None
        assert result.original_points == 3
    
    def test_cache_miss(self):
        """测试缓存未命中"""
        cache = LRUCache(max_size=3)
        result = cache.get("nonexistent")
        assert result is None
    
    def test_lru_eviction(self):
        """测试 LRU 淘汰"""
        from domain.simulation.data.resolution_pyramid import build_pyramid
        
        cache = LRUCache(max_size=2)
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 0.0])
        
        pyramid1 = build_pyramid(x, y)
        pyramid2 = build_pyramid(x, y * 2)
        pyramid3 = build_pyramid(x, y * 3)
        
        cache.put("key1", pyramid1)
        cache.put("key2", pyramid2)
        cache.put("key3", pyramid3)  # 应该淘汰 key1
        
        assert cache.get("key1") is None
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None
    
    def test_access_updates_order(self):
        """测试访问更新顺序"""
        from domain.simulation.data.resolution_pyramid import build_pyramid
        
        cache = LRUCache(max_size=2)
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 0.0])
        
        pyramid1 = build_pyramid(x, y)
        pyramid2 = build_pyramid(x, y * 2)
        pyramid3 = build_pyramid(x, y * 3)
        
        cache.put("key1", pyramid1)
        cache.put("key2", pyramid2)
        cache.get("key1")  # 访问 key1，使其变为最近使用
        cache.put("key3", pyramid3)  # 应该淘汰 key2
        
        assert cache.get("key1") is not None
        assert cache.get("key2") is None
        assert cache.get("key3") is not None
    
    def test_clear(self):
        """测试清空缓存"""
        from domain.simulation.data.resolution_pyramid import build_pyramid
        
        cache = LRUCache(max_size=3)
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 0.0])
        pyramid = build_pyramid(x, y)
        
        cache.put("key1", pyramid)
        cache.put("key2", pyramid)
        assert cache.size() == 2
        
        cache.clear()
        assert cache.size() == 0
        assert cache.get("key1") is None


# ============================================================
# WaveformDataService 测试
# ============================================================

class TestWaveformDataService:
    """WaveformDataService 测试"""
    
    def test_get_initial_data(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试获取初始数据"""
        data = service.get_initial_data(sample_result, "V(out)", target_points=500)
        
        assert data is not None
        assert data.signal_name == "V(out)"
        assert data.point_count <= 500
        assert data.is_downsampled is True
        assert data.original_points == 10000
    
    def test_get_initial_data_small_dataset(
        self,
        service: WaveformDataService,
    ):
        """测试小数据集不降采样"""
        time = np.linspace(0, 1e-3, 100)
        sim_data = SimulationData(
            time=time,
            signals={"V(out)": np.sin(2 * np.pi * 1000 * time)},
        )
        result = create_success_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="tran",
            data=sim_data,
        )
        
        data = service.get_initial_data(result, "V(out)", target_points=500)
        
        assert data is not None
        assert data.point_count == 100
        assert data.is_downsampled is False
    
    def test_get_initial_data_invalid_signal(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试无效信号名"""
        data = service.get_initial_data(sample_result, "V(nonexistent)")
        assert data is None
    
    def test_get_viewport_data(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试获取视口数据"""
        # 获取前半部分数据
        data = service.get_viewport_data(
            sample_result,
            "V(out)",
            x_min=0.0,
            x_max=0.5e-3,
            target_points=500,
        )
        
        assert data is not None
        assert data.signal_name == "V(out)"
        assert data.x_range[0] >= 0.0
        assert data.x_range[1] <= 0.5e-3
    
    def test_get_viewport_data_zoom_in(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试缩放时获取数据"""
        # 缩放到很小的范围
        data = service.get_viewport_data(
            sample_result,
            "V(out)",
            x_min=0.1e-3,
            x_max=0.2e-3,
            target_points=1000,
        )
        
        assert data is not None
        assert data.point_count > 0
    
    def test_get_full_resolution_data(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试获取完整分辨率数据"""
        data = service.get_full_resolution_data(sample_result, "V(out)")
        
        assert data is not None
        assert data.point_count == 10000
        assert data.is_downsampled is False
        assert data.original_points == 10000

    def test_get_available_signals(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试获取可用信号列表"""
        signals = service.get_available_signals(sample_result)
        
        assert len(signals) == 3
        assert "V(out)" in signals
        assert "V(in)" in signals
        assert "I(r1)" in signals
    
    def test_get_x_axis_label_transient(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试瞬态分析 X 轴标签"""
        label = service.get_x_axis_label(sample_result)
        assert label == "Time (s)"
    
    def test_get_x_axis_label_ac(
        self,
        service: WaveformDataService,
        ac_result: SimulationResult,
    ):
        """测试 AC 分析 X 轴标签"""
        label = service.get_x_axis_label(ac_result)
        assert label == "Frequency (Hz)"
    
    def test_get_table_data(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试获取表格数据"""
        table = service.get_table_data(sample_result, start_row=0, count=10)
        
        assert table is not None
        assert len(table.rows) == 10
        assert table.total_rows == 10000
        assert table.start_index == 0
        assert "V(out)" in table.signal_names
        assert table.x_label == "Time (s)"
    
    def test_get_table_data_pagination(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试表格数据分页"""
        table = service.get_table_data(sample_result, start_row=100, count=50)
        
        assert table is not None
        assert len(table.rows) == 50
        assert table.start_index == 100
        assert table.rows[0].index == 100
    
    def test_get_table_data_filter_signals(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试表格数据信号过滤"""
        table = service.get_table_data(
            sample_result,
            start_row=0,
            count=5,
            signal_names=["V(out)"],
        )
        
        assert table is not None
        assert table.signal_names == ["V(out)"]
        assert "V(in)" not in table.rows[0].values

    def test_get_display_signal_names_for_ac_expand_complex_signals(
        self,
        service: WaveformDataService,
        ac_result: SimulationResult,
    ):
        signals = service.get_display_signal_names(ac_result)

        assert "V(out)_mag" in signals
        assert "V(out)_phase" in signals
        assert "V(out)" not in signals

    def test_get_preferred_display_signal_for_ac_prefers_output_magnitude(
        self,
        service: WaveformDataService,
        ac_result: SimulationResult,
    ):
        signal_name = service.get_preferred_display_signal(ac_result)

        assert signal_name == "V(out)_mag"

    def test_get_table_data_for_ac_expands_complex_signal_filter(
        self,
        service: WaveformDataService,
        ac_result: SimulationResult,
    ):
        table = service.get_table_data(
            ac_result,
            start_row=0,
            count=5,
            signal_names=["V(out)"],
        )

        assert table is not None
        assert table.signal_names == [
            "V(out)_mag",
            "V(out)_phase",
            "V(out)_real",
            "V(out)_imag",
        ]
        assert "V(out)_mag" in table.rows[0].values
    
    def test_get_table_data_beyond_range(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试超出范围的表格请求"""
        table = service.get_table_data(sample_result, start_row=20000, count=10)
        
        assert table is not None
        assert len(table.rows) == 0
        assert table.total_rows == 10000

    def test_get_signal_statistics(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试获取信号统计信息"""
        stats = service.get_signal_statistics(sample_result, "V(out)")
        
        assert stats is not None
        assert "min" in stats
        assert "max" in stats
        assert "mean" in stats
        assert "std" in stats
        assert "rms" in stats
        assert "peak_to_peak" in stats
        
        # 正弦波的统计特性
        assert stats["min"] < 0
        assert stats["max"] > 0
        assert abs(stats["mean"]) < 0.1  # 均值接近 0
        assert stats["peak_to_peak"] > 1.9  # 峰峰值接近 2
    
    def test_get_signal_statistics_invalid_signal(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试无效信号的统计"""
        stats = service.get_signal_statistics(sample_result, "V(nonexistent)")
        assert stats is None
    
    def test_cache_mechanism(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试缓存机制"""
        # 首次访问
        service.get_initial_data(sample_result, "V(out)")
        assert service.get_cache_size() == 1
        
        # 再次访问同一信号，应该命中缓存
        service.get_initial_data(sample_result, "V(out)")
        assert service.get_cache_size() == 1
        
        # 访问不同信号
        service.get_initial_data(sample_result, "V(in)")
        assert service.get_cache_size() == 2
    
    def test_clear_cache(
        self,
        service: WaveformDataService,
        sample_result: SimulationResult,
    ):
        """测试清空缓存"""
        service.get_initial_data(sample_result, "V(out)")
        service.get_initial_data(sample_result, "V(in)")
        assert service.get_cache_size() == 2
        
        service.clear_cache()
        assert service.get_cache_size() == 0
    
    def test_failed_result(self, service: WaveformDataService):
        """测试失败的仿真结果"""
        from domain.simulation.models.simulation_result import create_error_result
        
        result = create_error_result(
            executor="spice",
            file_path="test.cir",
            analysis_type="tran",
            error="Simulation failed",
        )
        
        assert service.get_initial_data(result, "V(out)") is None
        assert service.get_available_signals(result) == []
        assert service.get_table_data(result, 0, 10) is None
    
    def test_ac_analysis_data(
        self,
        service: WaveformDataService,
        ac_result: SimulationResult,
    ):
        """测试 AC 分析数据"""
        data = service.get_initial_data(ac_result, "V(out)", target_points=500)
        
        assert data is not None
        assert data.signal_name == "V(out)_mag"
        assert data.is_downsampled is True
        
        # 验证频率范围
        assert data.x_range[0] >= 10  # 10 Hz
        assert data.x_range[1] <= 1e6  # 1 MHz
