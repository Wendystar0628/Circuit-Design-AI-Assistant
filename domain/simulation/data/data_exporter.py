# DataExporter - Simulation Data Export Service
"""
数据导出服务

职责：
- 将仿真数据导出为多种标准格式
- 支持从 SimulationResult 对象或文件路径导出
- 提供统一的导出接口供 UI 层调用

支持格式：
- CSV: 通用表格格式，兼容 Excel/LibreOffice
- JSON: 结构化数据格式，便于程序处理
- MATLAB: .mat 格式，兼容 MATLAB/Octave
- NumPy: .npy/.npz 格式，便于 Python 科学计算

设计原则：
- 领域层模块，不依赖 UI 组件
- 支持信号选择性导出
- 提供详细的错误信息

使用示例：
    from domain.simulation.data.data_exporter import DataExporter, data_exporter
    
    # 从 SimulationResult 对象导出
    exporter = DataExporter()
    success = exporter.export(
        data=simulation_result,
        format="csv",
        path="/path/to/output.csv",
        signals=["V(out)", "I(R1)"]
    )
    
    # 获取支持的格式
    formats = exporter.get_supported_formats()
"""

import csv
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from domain.simulation.models.simulation_result import SimulationResult


class ExportFormat(Enum):
    """导出格式枚举"""
    CSV = "csv"
    JSON = "json"
    MATLAB = "mat"
    NUMPY = "npy"
    NUMPY_COMPRESSED = "npz"


@dataclass
class ExportResult:
    """
    导出结果
    
    Attributes:
        success: 是否成功
        path: 导出文件路径
        format: 导出格式
        signal_count: 导出的信号数量
        point_count: 导出的数据点数量
        error_message: 错误信息（失败时有值）
    """
    success: bool
    path: str
    format: str
    signal_count: int = 0
    point_count: int = 0
    error_message: Optional[str] = None
    
    @classmethod
    def ok(
        cls,
        path: str,
        format: str,
        signal_count: int,
        point_count: int,
    ) -> "ExportResult":
        """创建成功结果"""
        return cls(
            success=True,
            path=path,
            format=format,
            signal_count=signal_count,
            point_count=point_count,
        )
    
    @classmethod
    def error(cls, path: str, format: str, message: str) -> "ExportResult":
        """创建失败结果"""
        return cls(
            success=False,
            path=path,
            format=format,
            error_message=message,
        )


class DataExporter:
    """
    数据导出服务
    
    提供仿真数据的多格式导出功能。
    """
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
    def get_supported_formats(self) -> List[str]:
        """
        获取支持的导出格式列表
        
        Returns:
            List[str]: 格式名称列表
        """
        return [fmt.value for fmt in ExportFormat]
    
    def get_format_extension(self, format: str) -> str:
        """
        获取格式对应的文件扩展名
        
        Args:
            format: 格式名称
            
        Returns:
            str: 文件扩展名（含点号）
        """
        extensions = {
            "csv": ".csv",
            "json": ".json",
            "mat": ".mat",
            "npy": ".npy",
            "npz": ".npz",
        }
        return extensions.get(format, "")
    
    def export(
        self,
        data: SimulationResult,
        format: str,
        path: str,
        signals: Optional[List[str]] = None,
    ) -> ExportResult:
        """
        导出仿真数据（返回详细结果）
        
        Args:
            data: SimulationData 或 SimulationResult 对象
            format: 导出格式（csv/json/mat/npy/npz）
            path: 导出文件路径
            signals: 要导出的信号列表（None 表示全部）
            
        Returns:
            ExportResult: 导出结果
        """
        if data is None or data.data is None:
            return ExportResult.error(path, format, "Invalid data: no simulation data")
        
        # 验证格式
        format_lower = format.lower()
        if format_lower not in self.get_supported_formats():
            return ExportResult.error(
                path, format, f"Unsupported format: {format}"
            )
        
        # 确保目录存在
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 分发到具体导出方法
        try:
            if format_lower == "csv":
                return self._export_csv(data, str(output_path), signals)
            elif format_lower == "json":
                return self._export_json(data, str(output_path), signals)
            elif format_lower == "mat":
                return self._export_matlab(data, str(output_path), signals)
            elif format_lower == "npy":
                return self._export_numpy(data, str(output_path), signals)
            elif format_lower == "npz":
                return self._export_numpy_compressed(data, str(output_path), signals)
            else:
                return ExportResult.error(path, format, f"Unsupported format: {format}")
        except Exception as e:
            self._logger.error(f"Export failed: {e}")
            return ExportResult.error(path, format, str(e))

    def _get_x_axis(self, result: SimulationResult) -> tuple[Optional[np.ndarray], str]:
        """获取权威 X 轴数据和名称"""
        x_data = result.get_x_axis_data()
        x_name = (result.x_axis_kind or "x").lower()
        return x_data, x_name if x_name and x_name != "none" else "x"
    
    def _filter_signals(
        self, result: SimulationResult, signals: Optional[List[str]]
    ) -> List[str]:
        """过滤要导出的信号列表"""
        data = result.data
        if data is None:
            return []
        all_signals = data.get_signal_names()
        if signals is None:
            return all_signals
        return [s for s in signals if s in all_signals]
    
    def _export_csv(
        self,
        result: SimulationResult,
        path: str,
        signals: Optional[List[str]],
    ) -> ExportResult:
        """导出为 CSV 格式"""
        data = result.data
        if data is None:
            return ExportResult.error(path, "csv", "No simulation data")
        x_data, _ = self._get_x_axis(result)
        if x_data is None:
            return ExportResult.error(path, "csv", "No x-axis data")
        
        signal_names = self._filter_signals(result, signals)
        if not signal_names:
            return ExportResult.error(path, "csv", "No signals to export")
        
        point_count = len(x_data)
        
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # 写入表头
            header = [result.get_x_axis_label()] + signal_names
            writer.writerow(header)
            
            # 写入数据
            for i in range(point_count):
                row = [x_data[i]]
                for sig_name in signal_names:
                    sig_data = data.get_signal(sig_name)
                    if sig_data is not None and i < len(sig_data):
                        row.append(sig_data[i])
                    else:
                        row.append("")
                writer.writerow(row)
        
        self._logger.info(f"Exported to CSV: {path}")
        return ExportResult.ok(path, "csv", len(signal_names), point_count)
    
    def _export_json(
        self,
        result: SimulationResult,
        path: str,
        signals: Optional[List[str]],
    ) -> ExportResult:
        """导出为 JSON 格式"""
        data = result.data
        if data is None:
            return ExportResult.error(path, "json", "No simulation data")
        signal_names = self._filter_signals(result, signals)
        x_data, x_name = self._get_x_axis(result)
        
        export_dict: Dict[str, Any] = {
            "x_axis_kind": result.x_axis_kind,
            "x_axis_label": result.get_x_axis_label(),
            "x_axis_scale": result.x_axis_scale,
            "x": x_data.tolist() if x_data is not None else None,
            "x_name": x_name,
            "signals": {},
            "metadata": {
                "signal_count": len(signal_names),
                "point_count": 0,
                "requested_x_range": list(result.requested_x_range) if result.requested_x_range is not None else None,
                "actual_x_range": list(result.actual_x_range) if result.actual_x_range is not None else None,
                "analysis_command": result.analysis_command,
            },
        }
        
        point_count = len(x_data) if x_data is not None else 0
        export_dict["metadata"]["point_count"] = point_count
        
        # 信号数据
        for sig_name in signal_names:
            sig_data = data.get_signal(sig_name)
            if sig_data is not None:
                export_dict["signals"][sig_name] = sig_data.tolist()
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export_dict, f, indent=2)
        
        self._logger.info(f"Exported to JSON: {path}")
        return ExportResult.ok(path, "json", len(signal_names), point_count)
    
    def _export_matlab(
        self,
        result: SimulationResult,
        path: str,
        signals: Optional[List[str]],
    ) -> ExportResult:
        """导出为 MATLAB .mat 格式"""
        try:
            from scipy.io import savemat
        except ImportError:
            return ExportResult.error(
                path, "mat", "scipy not installed. Run: pip install scipy"
            )
        
        data = result.data
        if data is None:
            return ExportResult.error(path, "mat", "No simulation data")
        signal_names = self._filter_signals(result, signals)
        
        mat_dict: Dict[str, Any] = {}
        x_data, x_name = self._get_x_axis(result)
        point_count = 0
        
        if x_data is not None:
            mat_dict[x_name] = x_data
            point_count = len(x_data)
        mat_dict["x_axis_label"] = np.array([result.get_x_axis_label()], dtype=object)
        mat_dict["x_axis_scale"] = np.array([result.x_axis_scale], dtype=object)
        
        # 信号数据（MATLAB 变量名需要合法化）
        for sig_name in signal_names:
            sig_data = data.get_signal(sig_name)
            if sig_data is not None:
                # 将信号名转换为合法的 MATLAB 变量名
                mat_name = self._to_matlab_varname(sig_name)
                mat_dict[mat_name] = sig_data
        
        savemat(path, mat_dict)
        
        self._logger.info(f"Exported to MATLAB: {path}")
        return ExportResult.ok(path, "mat", len(signal_names), point_count)
    
    def _to_matlab_varname(self, name: str) -> str:
        """
        将信号名转换为合法的 MATLAB 变量名
        
        MATLAB 变量名规则：
        - 以字母开头
        - 只包含字母、数字、下划线
        - 最大长度 63 字符
        """
        # 替换常见的非法字符
        result = name.replace("(", "_").replace(")", "")
        result = result.replace("[", "_").replace("]", "")
        result = result.replace(".", "_").replace("-", "_")
        result = result.replace(" ", "_").replace("/", "_")
        
        # 移除其他非法字符
        result = "".join(c if c.isalnum() or c == "_" else "_" for c in result)
        
        # 确保以字母开头
        if result and not result[0].isalpha():
            result = "sig_" + result
        
        # 截断到最大长度
        return result[:63] if result else "signal"
    
    def _export_numpy(
        self,
        result: SimulationResult,
        path: str,
        signals: Optional[List[str]],
    ) -> ExportResult:
        """导出为 NumPy .npy 格式（单个结构化数组）"""
        data = result.data
        if data is None:
            return ExportResult.error(path, "npy", "No simulation data")
        signal_names = self._filter_signals(result, signals)
        
        # 确定数据点数量
        x_data, x_name = self._get_x_axis(result)
        if x_data is None:
            return ExportResult.error(path, "npy", "No x-axis data")
        
        point_count = len(x_data)
        
        # 构建结构化数组的 dtype
        dtype_list = [(x_name, np.float64)]
        for sig_name in signal_names:
            # NumPy 字段名需要合法化
            field_name = self._to_numpy_fieldname(sig_name)
            dtype_list.append((field_name, np.float64))
        
        # 创建结构化数组
        structured_array = np.zeros(point_count, dtype=dtype_list)
        structured_array[x_name] = x_data
        
        for sig_name in signal_names:
            sig_data = data.get_signal(sig_name)
            if sig_data is not None:
                field_name = self._to_numpy_fieldname(sig_name)
                structured_array[field_name] = sig_data
        
        np.save(path, structured_array)
        
        self._logger.info(f"Exported to NumPy: {path}")
        return ExportResult.ok(path, "npy", len(signal_names), point_count)
    
    def _export_numpy_compressed(
        self,
        result: SimulationResult,
        path: str,
        signals: Optional[List[str]],
    ) -> ExportResult:
        """导出为 NumPy .npz 压缩格式（多个数组）"""
        data = result.data
        if data is None:
            return ExportResult.error(path, "npz", "No simulation data")
        signal_names = self._filter_signals(result, signals)
        
        arrays: Dict[str, np.ndarray] = {}
        x_data, x_name = self._get_x_axis(result)
        point_count = 0
        
        if x_data is not None:
            arrays[x_name] = x_data
            point_count = len(x_data)
        arrays["x_axis_label"] = np.array([result.get_x_axis_label()], dtype=object)
        arrays["x_axis_scale"] = np.array([result.x_axis_scale], dtype=object)
        
        # 信号数据
        for sig_name in signal_names:
            sig_data = data.get_signal(sig_name)
            if sig_data is not None:
                field_name = self._to_numpy_fieldname(sig_name)
                arrays[field_name] = sig_data
        
        np.savez_compressed(path, **arrays)
        
        self._logger.info(f"Exported to NumPy compressed: {path}")
        return ExportResult.ok(path, "npz", len(signal_names), point_count)
    
    def _to_numpy_fieldname(self, name: str) -> str:
        """
        将信号名转换为合法的 NumPy 字段名
        
        NumPy 结构化数组字段名规则较宽松，但为了兼容性，
        使用与 MATLAB 类似的规则。
        """
        return self._to_matlab_varname(name)


# 模块级单例
data_exporter = DataExporter()
"""模块级单例实例，便于直接导入使用"""


__all__ = [
    "ExportFormat",
    "ExportResult",
    "DataExporter",
    "data_exporter",
]
