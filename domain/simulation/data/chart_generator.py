# ChartGenerator - Chart Image Generation Service
"""
图表生成服务

职责：
- 根据 SimulationResult 和 ChartType 生成 matplotlib 图表图片
- 每张图表只绘制最重要的一条曲线，保持简洁
- 与 ChartSelector 配合，只生成用户启用的图表
- 输出临时 PNG 文件路径供 ChartViewer 加载

设计原则：
- 白色背景，清晰的专业论文风格
- 每张图表只显示一条主信号曲线，避免杂乱
- 主信号自动选择：优先输出节点（含 out），排除电源节点
- 使用工程记数法标注坐标轴

使用示例：
    from domain.simulation.data.chart_generator import chart_generator

    # 生成单张图表
    path = chart_generator.generate(result, ChartType.BODE_COMBINED)

    # 根据分析类型批量生成
    charts = chart_generator.generate_for_result(result, enabled_types)

图表类型整合说明：
    以下冗余的图表类型已被合并或重定向：
    - DC_TRANSFER → DC_SWEEP（统一使用 DC_SWEEP 生成）
    - NOISE_DENSITY → NOISE_SPECTRUM（统一使用 NOISE_SPECTRUM 生成）
    - WAVEFORM_FREQ → BODE_COMBINED（AC 频域用 Bode 即可）
    - BODE_MAGNITUDE / BODE_PHASE → BODE_COMBINED（组合图更完整）
"""

import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")  # 非交互后端
    import matplotlib.pyplot as plt
    from matplotlib.ticker import EngFormatter
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from domain.simulation.service.chart_selector import ChartType


# ============================================================
# 常量定义
# ============================================================

# 白色主题（清晰论文风格）
CHART_STYLE = {
    "figure.facecolor": "#ffffff",
    "axes.facecolor": "#ffffff",
    "axes.edgecolor": "#cccccc",
    "axes.labelcolor": "#333333",
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "text.color": "#333333",
    "xtick.color": "#555555",
    "ytick.color": "#555555",
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "grid.color": "#e0e0e0",
    "grid.alpha": 0.8,
    "legend.facecolor": "#ffffff",
    "legend.edgecolor": "#cccccc",
    "legend.labelcolor": "#333333",
    "legend.fontsize": 9,
    "lines.linewidth": 1.6,
    "font.family": "sans-serif",
}

# 主曲线颜色（用于唯一的一条曲线）
PRIMARY_COLOR = "#1f77b4"       # 标准蓝
SECONDARY_COLOR = "#d62728"     # 标准红（Bode 相位等辅助曲线）

# 图片参数
CHART_DPI = 200
CHART_WIDTH_INCHES = 9
CHART_HEIGHT_INCHES = 4.5
CHART_HEIGHT_COMBINED = 6      # 组合图（双子图）高度

# 排除的电源节点关键词（小写匹配）
_SUPPLY_KEYWORDS = {"vcc", "vdd", "vss", "vee", "gnd", "avdd", "dvdd", "avss"}

# 临时目录
_TEMP_DIR: Optional[str] = None


def _get_temp_dir() -> str:
    """获取或创建临时目录"""
    global _TEMP_DIR
    if _TEMP_DIR is None or not Path(_TEMP_DIR).exists():
        _TEMP_DIR = tempfile.mkdtemp(prefix="circuit_ai_charts_")
    return _TEMP_DIR


# ============================================================
# ChartGeneratorService
# ============================================================

class ChartGeneratorService:
    """
    图表生成服务

    根据仿真结果和图表类型生成白色背景 matplotlib 图表图片。
    每张图表只绘制最重要的一条曲线，保持简洁。
    """

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._generated_paths: Dict[str, str] = {}

    # ============================================================
    # 公共方法
    # ============================================================

    def generate(
        self,
        result: SimulationResult,
        chart_type: ChartType,
    ) -> Optional[str]:
        """
        生成单张图表

        Args:
            result: 仿真结果
            chart_type: 图表类型

        Returns:
            Optional[str]: 生成的 PNG 文件路径，失败返回 None
        """
        if not HAS_MATPLOTLIB:
            self._logger.error("matplotlib not installed, cannot generate charts")
            return None

        if result.data is None:
            self._logger.warning("No simulation data to generate chart")
            return None

        # 冗余图表类型重定向
        generator_map = {
            ChartType.WAVEFORM_TIME: self._gen_waveform_time,
            ChartType.BODE_COMBINED: self._gen_bode_combined,
            ChartType.DC_SWEEP: self._gen_dc_sweep,
            ChartType.FFT_SPECTRUM: self._gen_fft_spectrum,
            ChartType.NOISE_SPECTRUM: self._gen_noise_spectrum,
            # 重定向：合并到对应的主图表
            ChartType.WAVEFORM_FREQ: self._gen_bode_combined,
            ChartType.BODE_MAGNITUDE: self._gen_bode_combined,
            ChartType.BODE_PHASE: self._gen_bode_combined,
            ChartType.DC_TRANSFER: self._gen_dc_sweep,
            ChartType.NOISE_DENSITY: self._gen_noise_spectrum,
        }

        gen_func = generator_map.get(chart_type)
        if gen_func is None:
            self._logger.debug(
                f"Chart type {chart_type.value} not supported for direct generation"
            )
            return None

        try:
            path = gen_func(result.data, result.analysis_type)
            if path:
                self._generated_paths[chart_type.value] = path
            return path
        except Exception as e:
            self._logger.error(f"Failed to generate {chart_type.value}: {e}")
            return None

    def generate_for_result(
        self,
        result: SimulationResult,
        enabled_types: Optional[List[ChartType]] = None,
    ) -> Dict[str, str]:
        """
        根据仿真结果批量生成图表

        每种分析类型只生成不重复的核心图表：
        - tran → WAVEFORM_TIME, FFT_SPECTRUM
        - ac   → BODE_COMBINED
        - dc   → DC_SWEEP
        - noise → NOISE_SPECTRUM

        Args:
            result: 仿真结果
            enabled_types: 用户启用的图表类型列表（None 表示全部）

        Returns:
            Dict[str, str]: {chart_type_value: file_path}
        """
        if not HAS_MATPLOTLIB or result.data is None:
            return {}

        applicable = self._get_applicable_charts(result)

        if enabled_types is not None:
            applicable = [ct for ct in applicable if ct in enabled_types]

        charts: Dict[str, str] = {}
        for chart_type in applicable:
            path = self.generate(result, chart_type)
            if path:
                charts[chart_type.value] = path

        self._logger.info(
            f"Generated {len(charts)} charts for {result.analysis_type} analysis"
        )
        return charts

    def get_generated_paths(self) -> Dict[str, str]:
        """获取已生成的图表路径"""
        return dict(self._generated_paths)

    def clear_cache(self):
        """清除已生成的图表文件"""
        for path in self._generated_paths.values():
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
        self._generated_paths.clear()

    # ============================================================
    # 适用性判断（去重后的核心图表）
    # ============================================================

    def _get_applicable_charts(self, result: SimulationResult) -> List[ChartType]:
        """根据仿真结果判断适用的核心（非冗余）图表类型"""
        analysis = result.analysis_type.lower() if result.analysis_type else ""
        data = result.data

        if data is None:
            return []

        applicable: List[ChartType] = []

        has_time = data.time is not None and len(data.time) > 0
        has_freq = data.frequency is not None and len(data.frequency) > 0
        has_signals = len(data.signals) > 0

        if analysis == "tran" and has_time and has_signals:
            applicable.append(ChartType.WAVEFORM_TIME)
            applicable.append(ChartType.FFT_SPECTRUM)

        if analysis == "ac" and has_freq and has_signals:
            applicable.append(ChartType.BODE_COMBINED)

        if analysis == "dc" and has_signals:
            applicable.append(ChartType.DC_SWEEP)

        if analysis == "noise" and has_freq and has_signals:
            applicable.append(ChartType.NOISE_SPECTRUM)

        return applicable

    # ============================================================
    # 主信号选择
    # ============================================================

    def _pick_primary_signal(
        self,
        data: SimulationData,
        prefer: str = "voltage",
    ) -> Optional[Tuple[str, np.ndarray]]:
        """
        从所有信号中选择最重要的一条

        优先级：
        1. 名称含 "out" 的电压信号
        2. 排除电源节点后的第一个电压信号
        3. 排除电源节点后的第一个电流信号
        4. 第一个可用信号

        Args:
            data: 仿真数据
            prefer: 偏好类型 "voltage" | "current"

        Returns:
            (name, array) 或 None
        """
        sig_types = getattr(data, "signal_types", {})

        voltage_sigs: List[Tuple[str, np.ndarray]] = []
        current_sigs: List[Tuple[str, np.ndarray]] = []
        other_sigs: List[Tuple[str, np.ndarray]] = []

        for name, arr in data.signals.items():
            stype = sig_types.get(name, "")
            if stype == "voltage" or name.lower().startswith("v("):
                voltage_sigs.append((name, arr))
            elif stype == "current" or name.lower().startswith("i("):
                current_sigs.append((name, arr))
            else:
                other_sigs.append((name, arr))

        def _is_supply(name: str) -> bool:
            low = name.lower()
            # V(vcc), V(gnd) 等
            inner = low
            if "(" in low and ")" in low:
                inner = low.split("(", 1)[1].rsplit(")", 1)[0]
            return inner in _SUPPLY_KEYWORDS

        def _has_out(name: str) -> bool:
            return "out" in name.lower()

        # 1. 含 out 的电压信号
        for name, arr in voltage_sigs:
            if _has_out(name):
                return (name, arr)

        # 2. 非电源电压信号
        for name, arr in voltage_sigs:
            if not _is_supply(name):
                return (name, arr)

        # 3. 非电源电流信号
        for name, arr in current_sigs:
            if not _is_supply(name):
                return (name, arr)

        # 4. 其他信号
        if other_sigs:
            return other_sigs[0]

        # 5. 最终回退
        if voltage_sigs:
            return voltage_sigs[0]
        if current_sigs:
            return current_sigs[0]

        return None

    # ============================================================
    # 内部工具方法
    # ============================================================

    def _save_figure(self, fig, chart_type_value: str) -> str:
        """保存 figure 到临时文件并关闭"""
        temp_dir = _get_temp_dir()
        path = str(Path(temp_dir) / f"{chart_type_value}.png")
        fig.savefig(
            path, dpi=CHART_DPI, bbox_inches="tight", pad_inches=0.2,
            facecolor=fig.get_facecolor(), edgecolor="none",
        )
        plt.close(fig)
        return path

    def _create_figure(
        self,
        width: float = CHART_WIDTH_INCHES,
        height: float = CHART_HEIGHT_INCHES,
    ) -> Tuple[plt.Figure, plt.Axes]:
        """创建单子图 Figure"""
        with plt.rc_context(CHART_STYLE):
            fig, ax = plt.subplots(figsize=(width, height))
            fig.set_facecolor("#ffffff")
            ax.set_facecolor("#ffffff")
        return fig, ax

    def _create_dual_figure(
        self,
        width: float = CHART_WIDTH_INCHES,
        height: float = CHART_HEIGHT_COMBINED,
    ) -> Tuple[plt.Figure, plt.Axes, plt.Axes]:
        """创建双子图 Figure（上下排列，共享 X 轴）"""
        with plt.rc_context(CHART_STYLE):
            fig, (ax1, ax2) = plt.subplots(
                2, 1, figsize=(width, height), sharex=True,
                gridspec_kw={"hspace": 0.1}
            )
            fig.set_facecolor("#ffffff")
            ax1.set_facecolor("#ffffff")
            ax2.set_facecolor("#ffffff")
        return fig, ax1, ax2

    def _format_eng_axis(self, ax: plt.Axes, axis: str = "both"):
        """为坐标轴设置工程记数法格式"""
        if axis in ("x", "both"):
            ax.xaxis.set_major_formatter(EngFormatter())
        if axis in ("y", "both"):
            ax.yaxis.set_major_formatter(EngFormatter())

    @staticmethod
    def _to_real(arr: np.ndarray) -> np.ndarray:
        """安全取实部"""
        return np.real(arr) if np.iscomplexobj(arr) else arr

    # ============================================================
    # 图表生成方法（每张图只绘制一条主曲线）
    # ============================================================

    def _gen_waveform_time(
        self, data: SimulationData, analysis_type: str
    ) -> Optional[str]:
        """生成时域波形图 —— 一条主信号"""
        if data.time is None:
            return None

        primary = self._pick_primary_signal(data, prefer="voltage")
        if primary is None:
            return None
        name, arr = primary
        y = self._to_real(arr)

        with plt.rc_context(CHART_STYLE):
            fig, ax = self._create_figure()
            ax.plot(data.time, y, color=PRIMARY_COLOR, linewidth=1.6)

            ax.set_xlabel("Time (s)")
            ax.set_ylabel(name)
            ax.set_title("Transient Analysis", fontsize=13, fontweight="bold", pad=12)
            ax.grid(True, alpha=0.5)
            self._format_eng_axis(ax, "x")

        return self._save_figure(fig, ChartType.WAVEFORM_TIME.value)

    def _gen_bode_combined(
        self, data: SimulationData, analysis_type: str
    ) -> Optional[str]:
        """生成 Bode 组合图 —— 一条主信号的幅度 + 相位"""
        if data.frequency is None:
            return None

        primary = self._pick_primary_signal(data, prefer="voltage")
        if primary is None:
            return None
        name, arr = primary

        if np.iscomplexobj(arr):
            mag_db = 20 * np.log10(np.abs(arr) + 1e-30)
            phase_deg = np.degrees(np.angle(arr))
        else:
            mag_db = arr
            phase_deg = np.zeros_like(arr)

        with plt.rc_context(CHART_STYLE):
            fig, ax_mag, ax_phase = self._create_dual_figure()

            ax_mag.semilogx(data.frequency, mag_db, color=PRIMARY_COLOR, linewidth=1.6)
            ax_mag.set_ylabel("Magnitude (dB)")
            ax_mag.set_title(f"Bode Plot — {name}", fontsize=13, fontweight="bold", pad=12)
            ax_mag.grid(True, which="both", alpha=0.5)

            ax_phase.semilogx(data.frequency, phase_deg, color=SECONDARY_COLOR, linewidth=1.6)
            ax_phase.set_xlabel("Frequency (Hz)")
            ax_phase.set_ylabel("Phase (°)")
            ax_phase.grid(True, which="both", alpha=0.5)

        return self._save_figure(fig, ChartType.BODE_COMBINED.value)

    def _gen_dc_sweep(
        self, data: SimulationData, analysis_type: str
    ) -> Optional[str]:
        """生成 DC 扫描曲线 —— 一条主信号"""
        primary = self._pick_primary_signal(data, prefer="voltage")
        if primary is None:
            return None
        name, arr = primary
        y = self._to_real(arr)

        x_data, x_label = self._find_dc_sweep_axis(data)
        if x_data is None:
            return None
        if len(y) != len(x_data):
            return None

        with plt.rc_context(CHART_STYLE):
            fig, ax = self._create_figure()
            ax.plot(x_data, y, color=PRIMARY_COLOR, linewidth=1.6)

            ax.set_xlabel(x_label)
            ax.set_ylabel(name)
            ax.set_title("DC Sweep", fontsize=13, fontweight="bold", pad=12)
            ax.grid(True, alpha=0.5)
            self._format_eng_axis(ax, "both")

        return self._save_figure(fig, ChartType.DC_SWEEP.value)

    def _gen_fft_spectrum(
        self, data: SimulationData, analysis_type: str
    ) -> Optional[str]:
        """从时域数据生成 FFT 频谱图 —— 一条主信号"""
        if data.time is None:
            return None

        primary = self._pick_primary_signal(data, prefer="voltage")
        if primary is None:
            return None
        name, arr = primary
        y = self._to_real(arr)

        n = len(data.time)
        if len(y) != n or n < 2:
            return None

        dt = np.mean(np.diff(data.time))
        freqs = np.fft.rfftfreq(n, d=dt)

        spectrum = np.abs(np.fft.rfft(y)) / n * 2
        spectrum[0] /= 2  # DC 分量不乘 2
        spectrum_db = 20 * np.log10(spectrum + 1e-30)

        with plt.rc_context(CHART_STYLE):
            fig, ax = self._create_figure()
            ax.plot(freqs[1:], spectrum_db[1:], color=PRIMARY_COLOR, linewidth=1.4)

            ax.set_xlabel("Frequency (Hz)")
            ax.set_ylabel("Magnitude (dB)")
            ax.set_title(f"FFT Spectrum — {name}", fontsize=13, fontweight="bold", pad=12)
            ax.set_xscale("log")
            ax.grid(True, which="both", alpha=0.5)

        return self._save_figure(fig, ChartType.FFT_SPECTRUM.value)

    def _gen_noise_spectrum(
        self, data: SimulationData, analysis_type: str
    ) -> Optional[str]:
        """生成噪声频谱图 —— 一条主信号"""
        if data.frequency is None:
            return None

        primary = self._pick_primary_signal(data, prefer="voltage")
        if primary is None:
            return None
        name, arr = primary
        y = np.abs(arr) if np.iscomplexobj(arr) else arr

        with plt.rc_context(CHART_STYLE):
            fig, ax = self._create_figure()
            ax.loglog(data.frequency, y, color=PRIMARY_COLOR, linewidth=1.6)

            ax.set_xlabel("Frequency (Hz)")
            ax.set_ylabel("Noise Spectral Density (V/√Hz)")
            ax.set_title(f"Noise Spectrum — {name}", fontsize=13, fontweight="bold", pad=12)
            ax.grid(True, which="both", alpha=0.5)

        return self._save_figure(fig, ChartType.NOISE_SPECTRUM.value)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _find_dc_sweep_axis(
        self,
        data: SimulationData,
    ) -> Tuple[Optional[np.ndarray], str]:
        """
        确定 DC 分析的 X 轴数据

        Returns:
            (x_data, x_label) 或 (None, "")
        """
        if data.sweep is not None and len(data.sweep) > 0:
            return data.sweep, data.sweep_name or "Sweep"

        # 优先使用 time 轴（某些 DC 仿真将扫描值存入 time）
        if data.time is not None and len(data.time) > 0:
            return data.time, "Sweep Variable"

        if data.frequency is not None and len(data.frequency) > 0:
            return data.frequency, "Sweep Variable"

        # 从信号中寻找名为 sweep 的变量
        for name, arr in data.signals.items():
            lower = name.lower()
            if "sweep" in lower or lower == "v-sweep" or lower == "i-sweep":
                return (self._to_real(arr), name)

        # 回退：用索引
        if data.signals:
            first_arr = next(iter(data.signals.values()))
            return np.arange(len(first_arr)), "Index"

        return None, ""


# ============================================================
# 模块级单例
# ============================================================

chart_generator = ChartGeneratorService()


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ChartGeneratorService",
    "chart_generator",
]
