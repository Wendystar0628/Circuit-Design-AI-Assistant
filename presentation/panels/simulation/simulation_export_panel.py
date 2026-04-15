from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QWidget,
)

from domain.simulation.data.op_result_data_builder import op_result_data_builder
from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.simulation_export_coordinator import SimulationExportCoordinator


class SimulationExportPanel(QWidget):
    def __init__(self, chart_viewer, waveform_widget, parent=None):
        super().__init__(parent)
        self._export_coordinator = SimulationExportCoordinator(chart_viewer, waveform_widget)
        self._result: Optional[SimulationResult] = None
        self._metrics: List[Any] = []
        self._overall_score: float = 0.0
        self._latest_project_export_root: Optional[Path] = None
        self._manual_export_directory: Optional[Path] = None
        self._selected_type_preferences: Set[str] = set(self._export_coordinator.all_export_types())
        self.retranslate_ui()

    def set_result(self, result: Optional[SimulationResult]):
        self._result = result
        self._latest_project_export_root = None

    def set_metrics(self, metrics: List[Any]):
        self._metrics = list(metrics)

    def set_overall_score(self, overall_score: float):
        self._overall_score = overall_score

    def clear(self):
        self._result = None
        self._metrics = []
        self._overall_score = 0.0
        self._latest_project_export_root = None

    @property
    def latest_project_export_root(self) -> Optional[Path]:
        return self._latest_project_export_root

    def get_web_snapshot(self) -> Dict[str, Any]:
        return {
            "has_result": self._result is not None,
            "can_export": self._can_export_selected(),
            "items": self._build_export_items(),
            "selected_directory": str(self._manual_export_directory) if self._manual_export_directory is not None else "",
            "latest_project_export_root": str(self._latest_project_export_root) if self._latest_project_export_root is not None else "",
        }

    def set_selected_types(self, selected_types: List[str]):
        self._selected_type_preferences = set(self._export_coordinator.normalize_selected_types(selected_types))

    def set_export_type_selected(self, export_type: str, selected: bool):
        normalized_types = self._export_coordinator.normalize_selected_types([export_type])
        if not normalized_types:
            return
        normalized_type = normalized_types[0]
        if selected:
            self._selected_type_preferences.add(normalized_type)
            return
        self._selected_type_preferences.discard(normalized_type)

    def set_all_types_selected(self, selected: bool):
        if selected:
            self._selected_type_preferences = set(self._export_coordinator.all_export_types())
            return
        self._selected_type_preferences.clear()

    def set_manual_export_directory(self, directory: str):
        normalized_directory = str(directory or "").strip()
        self._manual_export_directory = Path(normalized_directory) if normalized_directory else None

    def clear_manual_export_directory(self):
        self._manual_export_directory = None

    def choose_export_directory(self) -> bool:
        start_directory = str(self._manual_export_directory) if self._manual_export_directory is not None else ""
        base_directory = QFileDialog.getExistingDirectory(
            self,
            self._get_text("simulation.export.choose_directory", "选择导出根目录"),
            start_directory,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not base_directory:
            return False
        self._manual_export_directory = Path(base_directory)
        return True

    def export_selected(self):
        result = self._result
        if result is None:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text("simulation.export.no_result", "当前没有可导出的仿真结果。"),
            )
            return None

        selected_types = self._get_selected_types()
        if not selected_types:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text("simulation.export.no_selection", "请至少选择一种导出内容。"),
            )
            return None

        if self._manual_export_directory is None:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text("simulation.export.no_directory", "请先选择导出目录。"),
            )
            return None

        execution = self._export_coordinator.export_to_base_directory(
            str(self._manual_export_directory),
            result,
            selected_types,
            self._metrics,
            self._overall_score,
        )

        if execution.errors:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text(
                    "simulation.export.partial_failed",
                    "导出已完成，但部分内容失败。\n根目录：{path}\n错误数量：{count}",
                ).format(path=str(execution.export_root), count=len(execution.errors)),
            )
            return execution

        QMessageBox.information(
            self,
            self._get_text("simulation.export.title", "统一数据导出"),
            self._get_text(
                "simulation.export.success",
                "导出完成。\n根目录：{path}\n文件数量：{count}",
            ).format(path=str(execution.export_root), count=len(execution.exported_files)),
        )
        return execution

    def retranslate_ui(self):
        return

    def auto_export_to_project(self, project_root: str):
        result = self._result
        if result is None or not project_root:
            return None

        selected_types = self._available_export_types()
        if not selected_types:
            return None

        execution = self._export_coordinator.export_to_project_directory(
            project_root,
            result,
            selected_types,
            self._metrics,
            self._overall_score,
        )
        self._latest_project_export_root = execution.export_root
        return execution

    def _get_selected_types(self) -> List[str]:
        available_types = set(self._available_export_types())
        requested_types = self._export_coordinator.normalize_selected_types(list(self._selected_type_preferences))
        return [export_type for export_type in requested_types if export_type in available_types]

    def _available_export_types(self) -> List[str]:
        result = self._result
        if result is None:
            return []
        available_types = self._export_coordinator.all_export_types()
        if not op_result_data_builder.is_available(result):
            available_types = [item for item in available_types if item != "op_result"]
        return available_types

    def _build_export_items(self) -> List[Dict[str, Any]]:
        available_types = set(self._available_export_types())
        return [
            {
                "id": export_type,
                "label": self._export_type_label(export_type),
                "selected": export_type in self._selected_type_preferences and export_type in available_types,
                "enabled": export_type in available_types,
            }
            for export_type in self._export_coordinator.all_export_types()
        ]

    def _can_export_selected(self) -> bool:
        return self._result is not None and bool(self._get_selected_types()) and self._manual_export_directory is not None

    def _export_type_label(self, export_type: str) -> str:
        labels = {
            "metrics": ("simulation.export.metrics", "仿真指标"),
            "charts": ("simulation.export.charts", "图表"),
            "waveforms": ("simulation.export.waveforms", "波形"),
            "analysis_info": ("simulation.export.analysis_info", "分析信息"),
            "raw_data": ("simulation.export.raw_data", "原始数据"),
            "output_log": ("simulation.export.output_log", "输出日志"),
            "op_result": ("simulation.export.op_result", "工作点结果"),
        }
        key, default = labels.get(export_type, ("", export_type))
        return self._get_text(key, default) if key else default

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            return I18nManager().get_text(key, default)
        except Exception:
            return default


__all__ = ["SimulationExportPanel"]
