# Test Data Exporter
"""
数据导出服务测试

测试内容：
- CSV 导出
- JSON 导出
- MATLAB 导出（需要 scipy）
- NumPy 导出
- 信号过滤
- 错误处理
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from domain.simulation.data.data_exporter import (
    DataExporter,
    ExportFormat,
    ExportResult,
    data_exporter,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_time_data() -> SimulationData:
    """创建时域仿真数据样本"""
    time = np.linspace(0, 1e-3, 1000)  # 1ms, 1000 points
    return SimulationData(
        time=time,
        frequency=None,
        signals={
            "V(out)": np.sin(2 * np.pi * 1000 * time),
            "V(in)": np.sin(2 * np.pi * 1000 * time + np.pi / 4),
            "I(R1)": np.cos(2 * np.pi * 1000 * time) * 1e-3,
        },
    )


@pytest.fixture
def sample_freq_data() -> SimulationData:
    """创建频域仿真数据样本"""
    frequency = np.logspace(1, 6, 100)  # 10Hz to 1MHz, 100 points
    return SimulationData(
        time=None,
        frequency=frequency,
        signals={
            "V(out)": 20 * np.log10(1 / np.sqrt(1 + (frequency / 1e4) ** 2)),
            "phase": -np.arctan(frequency / 1e4) * 180 / np.pi,
        },
    )


@pytest.fixture
def sample_result(sample_time_data: SimulationData) -> SimulationResult:
    """创建仿真结果样本"""
    return SimulationResult(
        executor="spice",
        file_path="test.cir",
        analysis_type="tran",
        success=True,
        data=sample_time_data,
    )


@pytest.fixture
def exporter() -> DataExporter:
    """创建导出器实例"""
    return DataExporter()


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================
# 基础功能测试
# ============================================================

class TestDataExporterBasic:
    """基础功能测试"""
    
    def test_get_supported_formats(self, exporter: DataExporter):
        """测试获取支持的格式列表"""
        formats = exporter.get_supported_formats()
        assert "csv" in formats
        assert "json" in formats
        assert "mat" in formats
        assert "npy" in formats
        assert "npz" in formats
    
    def test_get_format_description(self, exporter: DataExporter):
        """测试获取格式描述"""
        desc = exporter.get_format_description("csv")
        assert "CSV" in desc
        
        desc = exporter.get_format_description("unknown")
        assert "Unknown" in desc
    
    def test_get_format_extension(self, exporter: DataExporter):
        """测试获取格式扩展名"""
        assert exporter.get_format_extension("csv") == ".csv"
        assert exporter.get_format_extension("json") == ".json"
        assert exporter.get_format_extension("mat") == ".mat"
        assert exporter.get_format_extension("npy") == ".npy"
        assert exporter.get_format_extension("npz") == ".npz"
        assert exporter.get_format_extension("unknown") == ""
    
    def test_module_singleton(self):
        """测试模块级单例"""
        assert data_exporter is not None
        assert isinstance(data_exporter, DataExporter)


# ============================================================
# CSV 导出测试
# ============================================================

class TestCSVExport:
    """CSV 导出测试"""
    
    def test_export_time_data(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试时域数据 CSV 导出"""
        output_path = temp_dir / "output.csv"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="csv",
            path=str(output_path),
        )
        
        assert result.success
        assert result.signal_count == 3
        assert result.point_count == 1000
        assert output_path.exists()
        
        # 验证文件内容
        with open(output_path, "r") as f:
            lines = f.readlines()
        
        # 检查表头
        header = lines[0].strip().split(",")
        assert header[0] == "time"
        assert "V(out)" in header
        assert "V(in)" in header
        assert "I(R1)" in header
        
        # 检查数据行数
        assert len(lines) == 1001  # 1 header + 1000 data rows
    
    def test_export_freq_data(
        self,
        exporter: DataExporter,
        sample_freq_data: SimulationData,
        temp_dir: Path,
    ):
        """测试频域数据 CSV 导出"""
        output_path = temp_dir / "output.csv"
        
        result = exporter.export_with_result(
            data=sample_freq_data,
            format="csv",
            path=str(output_path),
        )
        
        assert result.success
        assert result.signal_count == 2
        assert result.point_count == 100
        
        # 验证表头
        with open(output_path, "r") as f:
            header = f.readline().strip().split(",")
        assert header[0] == "frequency"
    
    def test_export_selected_signals(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试选择性信号导出"""
        output_path = temp_dir / "output.csv"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="csv",
            path=str(output_path),
            signals=["V(out)"],
        )
        
        assert result.success
        assert result.signal_count == 1
        
        # 验证只有选中的信号
        with open(output_path, "r") as f:
            header = f.readline().strip().split(",")
        assert len(header) == 2  # time + V(out)
        assert "V(in)" not in header
    
    def test_export_from_simulation_result(
        self,
        exporter: DataExporter,
        sample_result: SimulationResult,
        temp_dir: Path,
    ):
        """测试从 SimulationResult 导出"""
        output_path = temp_dir / "output.csv"
        
        success = exporter.export(
            data=sample_result,
            format="csv",
            path=str(output_path),
        )
        
        assert success
        assert output_path.exists()


# ============================================================
# JSON 导出测试
# ============================================================

class TestJSONExport:
    """JSON 导出测试"""
    
    def test_export_time_data(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试时域数据 JSON 导出"""
        output_path = temp_dir / "output.json"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="json",
            path=str(output_path),
        )
        
        assert result.success
        assert output_path.exists()
        
        # 验证 JSON 结构
        with open(output_path, "r") as f:
            data = json.load(f)
        
        assert data["time"] is not None
        assert len(data["time"]) == 1000
        assert data["frequency"] is None
        assert "V(out)" in data["signals"]
        assert len(data["signals"]["V(out)"]) == 1000
        assert data["metadata"]["signal_count"] == 3
        assert data["metadata"]["point_count"] == 1000
    
    def test_export_freq_data(
        self,
        exporter: DataExporter,
        sample_freq_data: SimulationData,
        temp_dir: Path,
    ):
        """测试频域数据 JSON 导出"""
        output_path = temp_dir / "output.json"
        
        result = exporter.export_with_result(
            data=sample_freq_data,
            format="json",
            path=str(output_path),
        )
        
        assert result.success
        
        with open(output_path, "r") as f:
            data = json.load(f)
        
        assert data["time"] is None
        assert data["frequency"] is not None
        assert len(data["frequency"]) == 100


# ============================================================
# MATLAB 导出测试
# ============================================================

class TestMATLABExport:
    """MATLAB 导出测试"""
    
    def test_export_time_data(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试时域数据 MATLAB 导出"""
        pytest.importorskip("scipy")
        
        output_path = temp_dir / "output.mat"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="mat",
            path=str(output_path),
        )
        
        assert result.success
        assert output_path.exists()
        
        # 验证 MAT 文件内容
        from scipy.io import loadmat
        mat_data = loadmat(str(output_path))
        
        assert "time" in mat_data
        # scipy.io.loadmat 返回的数组形状可能是 (1, N) 或 (N,)
        time_data = mat_data["time"].flatten()
        assert len(time_data) == 1000
        # V(out) 转换为 V_out
        assert "V_out" in mat_data
    
    def test_matlab_varname_conversion(self, exporter: DataExporter):
        """测试 MATLAB 变量名转换"""
        # 测试括号转换
        assert exporter._to_matlab_varname("V(out)") == "V_out"
        assert exporter._to_matlab_varname("I(R1)") == "I_R1"
        
        # 测试数字开头
        assert exporter._to_matlab_varname("1signal").startswith("sig_")
        
        # 测试特殊字符
        assert exporter._to_matlab_varname("a.b-c") == "a_b_c"
    
    def test_export_without_scipy(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
        monkeypatch,
    ):
        """测试无 scipy 时的错误处理"""
        # 模拟 scipy 不可用
        import builtins
        original_import = builtins.__import__
        
        def mock_import(name, *args, **kwargs):
            if name == "scipy.io" or name.startswith("scipy"):
                raise ImportError("No module named 'scipy'")
            return original_import(name, *args, **kwargs)
        
        monkeypatch.setattr(builtins, "__import__", mock_import)
        
        output_path = temp_dir / "output.mat"
        result = exporter.export_with_result(
            data=sample_time_data,
            format="mat",
            path=str(output_path),
        )
        
        assert not result.success
        assert "scipy" in result.error_message.lower()


# ============================================================
# NumPy 导出测试
# ============================================================

class TestNumPyExport:
    """NumPy 导出测试"""
    
    def test_export_npy(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试 .npy 格式导出"""
        output_path = temp_dir / "output.npy"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="npy",
            path=str(output_path),
        )
        
        assert result.success
        assert output_path.exists()
        
        # 验证数据
        loaded = np.load(str(output_path))
        assert len(loaded) == 1000
        assert "time" in loaded.dtype.names
        assert "V_out" in loaded.dtype.names
    
    def test_export_npz(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试 .npz 压缩格式导出"""
        output_path = temp_dir / "output.npz"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="npz",
            path=str(output_path),
        )
        
        assert result.success
        assert output_path.exists()
        
        # 验证数据
        loaded = np.load(str(output_path))
        assert "time" in loaded.files
        assert "V_out" in loaded.files
        assert len(loaded["time"]) == 1000


# ============================================================
# 错误处理测试
# ============================================================

class TestErrorHandling:
    """错误处理测试"""
    
    def test_invalid_format(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试无效格式"""
        output_path = temp_dir / "output.xyz"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="xyz",
            path=str(output_path),
        )
        
        assert not result.success
        assert "Unsupported" in result.error_message
    
    def test_no_x_axis_data(self, exporter: DataExporter, temp_dir: Path):
        """测试无 X 轴数据"""
        data = SimulationData(
            time=None,
            frequency=None,
            signals={"V(out)": np.array([1, 2, 3])},
        )
        
        output_path = temp_dir / "output.csv"
        result = exporter.export_with_result(
            data=data,
            format="csv",
            path=str(output_path),
        )
        
        assert not result.success
        assert "x-axis" in result.error_message.lower()
    
    def test_no_signals(
        self,
        exporter: DataExporter,
        temp_dir: Path,
    ):
        """测试无信号数据"""
        data = SimulationData(
            time=np.array([0, 1, 2]),
            frequency=None,
            signals={},
        )
        
        output_path = temp_dir / "output.csv"
        result = exporter.export_with_result(
            data=data,
            format="csv",
            path=str(output_path),
        )
        
        assert not result.success
        assert "signal" in result.error_message.lower()
    
    def test_invalid_signal_filter(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试无效的信号过滤"""
        output_path = temp_dir / "output.csv"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="csv",
            path=str(output_path),
            signals=["nonexistent_signal"],
        )
        
        # 过滤后无有效信号
        assert not result.success
    
    def test_create_parent_directory(
        self,
        exporter: DataExporter,
        sample_time_data: SimulationData,
        temp_dir: Path,
    ):
        """测试自动创建父目录"""
        output_path = temp_dir / "subdir" / "nested" / "output.csv"
        
        result = exporter.export_with_result(
            data=sample_time_data,
            format="csv",
            path=str(output_path),
        )
        
        assert result.success
        assert output_path.exists()


# ============================================================
# ExportResult 测试
# ============================================================

class TestExportResult:
    """ExportResult 数据类测试"""
    
    def test_ok_factory(self):
        """测试成功结果工厂方法"""
        result = ExportResult.ok(
            path="/path/to/file.csv",
            format="csv",
            signal_count=3,
            point_count=1000,
        )
        
        assert result.success
        assert result.path == "/path/to/file.csv"
        assert result.format == "csv"
        assert result.signal_count == 3
        assert result.point_count == 1000
        assert result.error_message is None
    
    def test_error_factory(self):
        """测试失败结果工厂方法"""
        result = ExportResult.error(
            path="/path/to/file.csv",
            format="csv",
            message="Something went wrong",
        )
        
        assert not result.success
        assert result.error_message == "Something went wrong"
        assert result.signal_count == 0
        assert result.point_count == 0
