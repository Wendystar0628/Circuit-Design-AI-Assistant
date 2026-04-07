from enum import Enum


class ChartType(Enum):
    WAVEFORM_TIME = "waveform_time"
    BODE_OVERLAY = "bode_overlay"
    DC_SWEEP = "dc_sweep"
    NOISE_SPECTRUM = "noise_spectrum"

    @classmethod
    def get_display_name(cls, chart_type: "ChartType") -> str:
        names = {
            cls.WAVEFORM_TIME: "时域波形图",
            cls.BODE_OVERLAY: "Bode 幅相图",
            cls.DC_SWEEP: "DC 扫描曲线",
            cls.NOISE_SPECTRUM: "噪声频谱图",
        }
        return names.get(chart_type, chart_type.value)

    @classmethod
    def get_category(cls, chart_type: "ChartType") -> str:
        categories = {
            cls.WAVEFORM_TIME: "waveform",
            cls.BODE_OVERLAY: "bode",
            cls.DC_SWEEP: "dc",
            cls.NOISE_SPECTRUM: "noise",
        }
        return categories.get(chart_type, "other")


__all__ = ["ChartType"]
