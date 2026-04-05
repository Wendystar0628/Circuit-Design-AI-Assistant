from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from domain.simulation.models.simulation_result import SimulationResult
from resources.theme import (
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    SPACING_NORMAL,
    SPACING_SMALL,
)


_ANALYSIS_TYPE_LABELS = {
    "ac": "AC 小信号分析",
    "dc": "DC 扫描分析",
    "tran": "瞬态分析",
    "noise": "噪声分析",
    "op": "工作点分析",
}

_X_AXIS_KIND_LABELS = {
    "time": "时间",
    "frequency": "频率",
    "sweep": "扫描量",
    "none": "",
}

_X_AXIS_SCALE_LABELS = {
    "linear": "线性",
    "log": "对数",
    "none": "",
}

_PARAMETER_LABELS = {
    "ac": (
        ("sweep_type", "扫描类型"),
        ("points_per_decade", "每十倍频程点数"),
        ("start_frequency", "起始频率"),
        ("stop_frequency", "终止频率"),
    ),
    "dc": (
        ("source_name", "扫描源名称"),
        ("start_value", "起始值"),
        ("stop_value", "终止值"),
        ("step", "步长"),
    ),
    "tran": (
        ("step_time", "步进时间"),
        ("stop_time", "结束时间"),
        ("start_time", "起始时间"),
        ("max_step", "最大步长"),
        ("use_initial_conditions", "初始条件"),
    ),
    "noise": (
        ("output_node", "输出节点"),
        ("input_source", "输入源"),
        ("sweep_type", "扫描类型"),
        ("points_per_decade", "每十倍频程点数"),
        ("start_frequency", "起始频率"),
        ("stop_frequency", "终止频率"),
    ),
    "op": (),
}


class AnalysisInfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: Optional[SimulationResult] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_SMALL)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        layout.addWidget(self._tree, 1)

        self._apply_style()
        self.retranslate_ui()

    def load_result(self, result: Optional[SimulationResult]):
        self._result = result
        self._rebuild()

    def clear(self):
        self._result = None
        self._tree.clear()

    def retranslate_ui(self):
        self._tree.setHeaderLabels([
            self._get_text("simulation.analysis_info.field", "字段"),
            self._get_text("simulation.analysis_info.value", "值"),
        ])
        self._rebuild()

    def _rebuild(self):
        self._tree.clear()
        result = self._result
        if result is None:
            return

        info = result.analysis_info if isinstance(result.analysis_info, dict) else {}
        analysis_type = str(info.get("analysis_type") or result.analysis_type or "").lower()
        parameters = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}

        self._add_section(
            self._get_text("simulation.analysis_info.section.analysis", "分析信息"),
            (
                (self._get_text("simulation.analysis_info.analysis_type", "分析类型"), self._format_analysis_type(analysis_type)),
                (self._get_text("simulation.analysis_info.executor", "执行器"), self._stringify(result.executor)),
                (self._get_text("simulation.analysis_info.file", "电路文件"), Path(result.file_path).name if result.file_path else ""),
            ),
        )
        self._add_section(
            self._get_text("simulation.analysis_info.section.axis", "坐标轴信息"),
            (
                (self._get_text("simulation.analysis_info.x_kind", "横轴类别"), self._format_x_axis_kind(str(info.get("x_axis_kind") or result.x_axis_kind or ""))),
                (self._get_text("simulation.analysis_info.x_label", "横轴标签"), self._stringify(info.get("x_axis_label") or result.x_axis_label)),
                (self._get_text("simulation.analysis_info.x_scale", "横轴显示"), self._format_x_axis_scale(str(info.get("x_axis_scale") or result.x_axis_scale or ""))),
                (self._get_text("simulation.analysis_info.requested_range", "请求范围"), self._format_range(info.get("requested_x_range") or result.requested_x_range)),
                (self._get_text("simulation.analysis_info.actual_range", "实际范围"), self._format_range(info.get("actual_x_range") or result.actual_x_range)),
            ),
        )
        self._add_section(
            self._get_text("simulation.analysis_info.section.parameters", "分析参数"),
            tuple(
                (label, self._stringify(parameters.get(key)))
                for key, label in _PARAMETER_LABELS.get(analysis_type, ())
            ),
        )
        self._tree.expandAll()
        self._tree.header().setStretchLastSection(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

    def _add_section(self, title: str, rows: Tuple[Tuple[str, str], ...]):
        section = QTreeWidgetItem(self._tree, [title, ""])
        section.setFirstColumnSpanned(True)
        for label, value in rows:
            QTreeWidgetItem(section, [label, value])

    def _format_analysis_type(self, value: str) -> str:
        return _ANALYSIS_TYPE_LABELS.get(value, value)

    def _format_x_axis_kind(self, value: str) -> str:
        return _X_AXIS_KIND_LABELS.get(value.lower(), value)

    def _format_x_axis_scale(self, value: str) -> str:
        return _X_AXIS_SCALE_LABELS.get(value.lower(), value)

    def _format_range(self, value: Any) -> str:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return ""
        try:
            start = float(value[0])
            stop = float(value[1])
        except (TypeError, ValueError):
            return ""
        return f"{start:.6g} ~ {stop:.6g}"

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def _apply_style(self):
        self.setStyleSheet(f"""
            AnalysisInfoPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            QTreeWidget {{
                background-color: {COLOR_BG_PRIMARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
            }}
            QTreeWidget::item {{
                padding: 4px 6px;
            }}
        """)

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            return I18nManager().get_text(key, default)
        except Exception:
            return default


__all__ = ["AnalysisInfoPanel"]
