from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QVBoxLayout,
    QWidget,
)

from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.simulation_export_coordinator import SimulationExportCoordinator
from resources.theme import (
    BORDER_RADIUS_NORMAL,
    COLOR_ACCENT,
    COLOR_ACCENT_LIGHT,
    COLOR_BG_PRIMARY,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    FONT_SIZE_SMALL,
    SPACING_NORMAL,
    SPACING_SMALL,
)


class SimulationExportPanel(QWidget):
    def __init__(self, chart_viewer, waveform_widget, parent=None):
        super().__init__(parent)
        self._export_coordinator = SimulationExportCoordinator(chart_viewer, waveform_widget)
        self._result: Optional[SimulationResult] = None
        self._metrics: List[Any] = []
        self._overall_score: float = 0.0
        self._latest_project_export_root: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        layout.setSpacing(SPACING_NORMAL)

        self._selection_card = QFrame()
        self._selection_card.setObjectName("exportSelectionCard")
        selection_layout = QVBoxLayout(self._selection_card)
        selection_layout.setContentsMargins(SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL, SPACING_NORMAL)
        selection_layout.setSpacing(SPACING_NORMAL)

        self._selection_title = QLabel()
        self._selection_title.setObjectName("exportSelectionTitle")
        selection_layout.addWidget(self._selection_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACING_NORMAL)
        grid.setVerticalSpacing(SPACING_SMALL)
        self._checkboxes: Dict[str, QCheckBox] = {}

        checkbox_specs = [
            ("metrics", 0, 0),
            ("charts", 0, 1),
            ("waveforms", 1, 0),
            ("analysis_info", 1, 1),
            ("raw_data", 2, 0),
            ("output_log", 2, 1),
        ]
        for key, row, column in checkbox_specs:
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self._checkboxes[key] = checkbox
            grid.addWidget(checkbox, row, column)
        selection_layout.addLayout(grid)

        button_row = QHBoxLayout()
        button_row.setSpacing(SPACING_SMALL)

        self._select_all_btn = QPushButton()
        self._select_all_btn.setObjectName("exportSecondaryBtn")
        self._select_all_btn.clicked.connect(self._select_all)
        button_row.addWidget(self._select_all_btn)

        self._clear_selection_btn = QPushButton()
        self._clear_selection_btn.setObjectName("exportSecondaryBtn")
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        button_row.addWidget(self._clear_selection_btn)

        button_row.addStretch()

        self._export_btn = QPushButton()
        self._export_btn.setObjectName("exportPrimaryBtn")
        self._export_btn.clicked.connect(self._export_selected)
        button_row.addWidget(self._export_btn)

        selection_layout.addLayout(button_row)
        layout.addWidget(self._selection_card)
        layout.addStretch()

        self._apply_style()
        self.retranslate_ui()

    def set_result(self, result: Optional[SimulationResult]):
        self._result = result
        self._latest_project_export_root = None
        self._update_enabled_state()

    def set_metrics(self, metrics: List[Any]):
        self._metrics = list(metrics)

    def set_overall_score(self, overall_score: float):
        self._overall_score = overall_score

    def clear(self):
        self._result = None
        self._metrics = []
        self._overall_score = 0.0
        self._latest_project_export_root = None
        self._update_enabled_state()

    @property
    def latest_project_export_root(self) -> Optional[Path]:
        return self._latest_project_export_root

    def retranslate_ui(self):
        self._selection_title.setText(self._get_text("simulation.export.selection_title", "导出内容"))
        self._checkboxes["metrics"].setText(self._get_text("simulation.export.metrics", "仿真指标"))
        self._checkboxes["charts"].setText(self._get_text("simulation.export.charts", "图表"))
        self._checkboxes["waveforms"].setText(self._get_text("simulation.export.waveforms", "波形"))
        self._checkboxes["analysis_info"].setText(self._get_text("simulation.export.analysis_info", "分析信息"))
        self._checkboxes["raw_data"].setText(self._get_text("simulation.export.raw_data", "原始数据"))
        self._checkboxes["output_log"].setText(self._get_text("simulation.export.output_log", "输出日志"))
        self._select_all_btn.setText(self._get_text("simulation.export.select_all", "全选"))
        self._clear_selection_btn.setText(self._get_text("simulation.export.clear_selection", "清空选择"))
        self._export_btn.setText(self._get_text("simulation.export.execute", "导出所选内容"))

    def _select_all(self):
        for checkbox in self._checkboxes.values():
            checkbox.setChecked(True)

    def _clear_selection(self):
        for checkbox in self._checkboxes.values():
            checkbox.setChecked(False)

    def _export_selected(self):
        result = self._result
        if result is None:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text("simulation.export.no_result", "当前没有可导出的仿真结果。"),
            )
            return

        selected_types = self._get_selected_types()
        if not selected_types:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text("simulation.export.no_selection", "请至少选择一种导出内容。"),
            )
            return

        base_directory = QFileDialog.getExistingDirectory(
            self,
            self._get_text("simulation.export.choose_directory", "选择导出根目录"),
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not base_directory:
            return

        execution = self._export_coordinator.export_to_base_directory(
            base_directory,
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
            return

        QMessageBox.information(
            self,
            self._get_text("simulation.export.title", "统一数据导出"),
            self._get_text(
                "simulation.export.success",
                "导出完成。\n根目录：{path}\n文件数量：{count}",
            ).format(path=str(execution.export_root), count=len(execution.exported_files)),
        )

    def auto_export_to_project(self, project_root: str):
        result = self._result
        if result is None or not project_root:
            return None

        selected_types = self._get_selected_types(fallback_to_all=True)
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

    def _get_selected_types(self, fallback_to_all: bool = False) -> List[str]:
        selected_types = [key for key, checkbox in self._checkboxes.items() if checkbox.isChecked()]
        if selected_types or not fallback_to_all:
            return selected_types
        return self._export_coordinator.all_export_types()

    def _update_enabled_state(self):
        has_result = self._result is not None
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(has_result)
        self._select_all_btn.setEnabled(has_result)
        self._clear_selection_btn.setEnabled(has_result)
        self._export_btn.setEnabled(has_result)

    def _apply_style(self):
        checkmark_icon_path = (Path(__file__).resolve().parents[3] / "resources" / "icons" / "ui" / "checkmark-dark.svg").as_posix()
        self.setStyleSheet(f"""
            SimulationExportPanel {{
                background-color: {COLOR_BG_PRIMARY};
            }}
            #exportSelectionCard {{
                background-color: {COLOR_BG_TERTIARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: {BORDER_RADIUS_NORMAL}px;
            }}
            #exportSelectionTitle {{
                color: {COLOR_TEXT_PRIMARY};
                font-weight: bold;
            }}
            QCheckBox {{
                color: {COLOR_TEXT_PRIMARY};
                spacing: 8px;
                font-size: {FONT_SIZE_SMALL}px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                background-color: {COLOR_BG_PRIMARY};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {COLOR_BORDER};
                background-color: {COLOR_BG_PRIMARY};
                image: url("{checkmark_icon_path}");
            }}
            QCheckBox::indicator:unchecked {{
                image: none;
            }}
            QCheckBox::indicator:disabled {{
                background-color: {COLOR_BG_SECONDARY};
            }}
            QCheckBox::indicator:checked:disabled {{
                border: 1px solid {COLOR_BORDER};
                background-color: {COLOR_BG_SECONDARY};
                image: url("{checkmark_icon_path}");
            }}
            #exportSecondaryBtn, #exportPrimaryBtn {{
                border-radius: {BORDER_RADIUS_NORMAL}px;
                padding: 6px 12px;
            }}
            #exportSecondaryBtn {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BORDER};
            }}
            #exportSecondaryBtn:hover {{
                background-color: {COLOR_ACCENT_LIGHT};
            }}
            #exportPrimaryBtn {{
                background-color: {COLOR_ACCENT};
                color: white;
                border: 1px solid {COLOR_ACCENT};
            }}
        """)

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            return I18nManager().get_text(key, default)
        except Exception:
            return default


__all__ = ["SimulationExportPanel"]
