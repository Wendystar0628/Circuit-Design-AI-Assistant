# Simulation Data Processing Layer
"""
仿真数据处理层

职责：
- 波形数据降采样（LTTB 算法）
- 多分辨率金字塔管理
- 波形数据服务（统一访问入口）
- 数据导出（CSV/MATLAB/NumPy/JSON）
- 仿真输出日志解析

设计原则：
- 领域层专注于数据处理逻辑
- 不包含任何 UI 组件
- 为表示层提供标准化的数据访问接口
"""

from domain.simulation.data.downsampler import (
    downsample,
    downsample_multiple,
)
from domain.simulation.data.resolution_pyramid import (
    DEFAULT_PYRAMID_LEVELS,
    PyramidData,
    PyramidLevel,
    build_pyramid,
    get_level_data,
    get_optimal_data,
    select_optimal_level,
)
from domain.simulation.data.waveform_data_service import (
    WaveformData,
    TableRow,
    TableData,
    WaveformDataService,
    waveform_data_service,
)
from domain.simulation.data.data_exporter import (
    ExportFormat,
    ExportResult,
    DataExporter,
    data_exporter,
)
from domain.simulation.data.simulation_output_reader import (
    LogLevel,
    LogLine,
    SimulationSummary,
    SimulationOutputReader,
    simulation_output_reader,
)

__all__ = [
    # Downsampler
    "downsample",
    "downsample_multiple",
    # Resolution Pyramid
    "DEFAULT_PYRAMID_LEVELS",
    "PyramidLevel",
    "PyramidData",
    "build_pyramid",
    "select_optimal_level",
    "get_level_data",
    "get_optimal_data",
    # Waveform Data Service
    "WaveformData",
    "TableRow",
    "TableData",
    "WaveformDataService",
    "waveform_data_service",
    # Data Exporter
    "ExportFormat",
    "ExportResult",
    "DataExporter",
    "data_exporter",
    # Simulation Output Reader
    "LogLevel",
    "LogLine",
    "SimulationSummary",
    "SimulationOutputReader",
    "simulation_output_reader",
]
