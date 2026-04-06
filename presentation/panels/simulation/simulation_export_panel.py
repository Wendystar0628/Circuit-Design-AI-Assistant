import json
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

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationResult
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
        self._chart_viewer = chart_viewer
        self._waveform_widget = waveform_widget
        self._result: Optional[SimulationResult] = None
        self._metrics: List[Any] = []
        self._overall_score: float = 0.0

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
        self._update_enabled_state()

    def set_metrics(self, metrics: List[Any]):
        self._metrics = list(metrics)

    def set_overall_score(self, overall_score: float):
        self._overall_score = overall_score

    def clear(self):
        self._result = None
        self._metrics = []
        self._overall_score = 0.0
        self._update_enabled_state()

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

        selected_types = [key for key, checkbox in self._checkboxes.items() if checkbox.isChecked()]
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

        export_root = simulation_artifact_exporter.create_export_root(base_directory, result)
        exported_files: List[str] = []
        category_exports: Dict[str, List[str]] = {}
        errors: List[Dict[str, str]] = []

        for export_type in selected_types:
            try:
                category_file_paths: List[str] = []
                if export_type == "metrics":
                    category_file_paths = simulation_artifact_exporter.export_metrics(export_root, result, self._metrics, self._overall_score)
                elif export_type == "charts":
                    category_file_paths = self._chart_viewer.export_bundle(str(export_root / "charts"))
                elif export_type == "waveforms":
                    category_file_paths = self._waveform_widget.export_bundle(str(export_root / "waveforms"))
                elif export_type == "analysis_info":
                    category_file_paths = simulation_artifact_exporter.export_analysis_info(export_root, result)
                elif export_type == "raw_data":
                    category_file_paths = simulation_artifact_exporter.export_raw_data(export_root, result)
                elif export_type == "output_log":
                    category_file_paths = simulation_artifact_exporter.export_output_log(export_root, result)
                exported_files.extend(category_file_paths)
                category_exports[export_type] = self._to_relative_paths(export_root, category_file_paths)
            except Exception as exc:
                category_exports[export_type] = []
                errors.append({
                    "artifact_type": export_type,
                    "message": str(exc),
                })

        manifest_path = export_root / "export_manifest.json"
        manifest_payload = simulation_artifact_exporter.build_artifact_payload(
            result,
            "export_manifest",
            summary={
                "selected_type_count": len(selected_types),
                "exported_file_count": len(exported_files) + 1,
                "error_count": len(errors),
            },
            files={
                "categories": category_exports,
                "manifest": manifest_path.name,
            },
            data={
                "selected_types": selected_types,
                "exported_files": self._to_relative_paths(export_root, [*exported_files, str(manifest_path)]),
                "errors": errors,
            },
        )
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        exported_files.append(str(manifest_path))

        if errors:
            QMessageBox.warning(
                self,
                self._get_text("simulation.export.title", "统一数据导出"),
                self._get_text(
                    "simulation.export.partial_failed",
                    "导出已完成，但部分内容失败。\n根目录：{path}\n错误数量：{count}",
                ).format(path=str(export_root), count=len(errors)),
            )
            return

        QMessageBox.information(
            self,
            self._get_text("simulation.export.title", "统一数据导出"),
            self._get_text(
                "simulation.export.success",
                "导出完成。\n根目录：{path}\n文件数量：{count}",
            ).format(path=str(export_root), count=len(exported_files)),
        )

    def _to_relative_paths(self, export_root: Path, file_paths: List[str]) -> List[str]:
        root = export_root.resolve()
        relative_paths: List[str] = []
        for file_path in file_paths:
            path = Path(file_path)
            try:
                relative_paths.append(str(path.resolve().relative_to(root)).replace("\\", "/"))
            except Exception:
                relative_paths.append(path.name)
        return relative_paths

    def _update_enabled_state(self):
        has_result = self._result is not None
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(has_result)
        self._select_all_btn.setEnabled(has_result)
        self._clear_selection_btn.setEnabled(has_result)
        self._export_btn.setEnabled(has_result)

    def _apply_style(self):
        checkmark_icon_path = (Path(__file__).resolve().parents[3] / "resources" / "icons" / "ui" / "checkmark.svg").as_posix()
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
            QCheckBox::indicator:hover {{
                border: 1px solid {COLOR_ACCENT};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {COLOR_ACCENT};
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
