from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from domain.simulation.spice.ltspice_asc_to_cir_transcriber import (
    AscBatchConversionExecution,
    LtspiceAscToCirTranscriber,
)


class SimulationAscConversionPanel(QWidget):
    OUTPUT_DIRECTORY_NAME = "cir"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_root: Optional[Path] = None
        self._transcriber = LtspiceAscToCirTranscriber()
        self._selected_files_summary = ""
        self.retranslate_ui()

    def set_project_root(self, project_root: str) -> None:
        normalized = str(project_root or "").strip()
        self._project_root = Path(normalized).resolve() if normalized else None

    def get_web_snapshot(self) -> dict:
        return {
            "can_choose_files": self._project_root is not None,
            "selected_files_summary": self._selected_files_summary,
        }

    def choose_files_and_convert(self) -> Optional[AscBatchConversionExecution]:
        if self._project_root is None:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "警告"),
                self._get_text("simulation.asc_conversion.no_project", "请先打开项目，再执行 ASC 转换。"),
            )
            return None
        file_paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            self._get_text("simulation.asc_conversion.choose_files", "选择 ASC 文件"),
            str(self._project_root),
            "LTspice ASC Files (*.asc)",
        )
        if not file_paths:
            return None
        self._selected_files_summary = f"已选择并转换 {len(file_paths)} 个 .asc 文件"
        output_root = self._project_root / self.OUTPUT_DIRECTORY_NAME
        execution = self._transcriber.convert_files(file_paths, str(output_root))
        self._show_execution_result(execution)
        return execution

    def clear(self) -> None:
        return

    def retranslate_ui(self) -> None:
        return

    def _show_execution_result(self, execution: AscBatchConversionExecution) -> None:
        converted_count = len(execution.converted_files)
        failed_count = len(execution.failed_files)
        degraded_count = sum(1 for item in execution.converted_files if item.degraded)
        validation_issue_count = sum(len(item.validation_errors) for item in execution.converted_files)
        if failed_count:
            QMessageBox.warning(
                self,
                self._get_text("dialog.warning.title", "警告"),
                self._get_text(
                    "simulation.asc_conversion.partial_failed",
                    "ASC 转换已完成，但部分文件失败。\n输出目录：{path}\n成功：{success}\n失败：{failed}\n降级：{degraded}\n校验问题：{issues}",
                ).format(
                    path=execution.output_root,
                    success=converted_count,
                    failed=failed_count,
                    degraded=degraded_count,
                    issues=validation_issue_count,
                ),
            )
            return
        QMessageBox.information(
            self,
            self._get_text("simulation.asc_conversion.title", "ASC 转换"),
            self._get_text(
                "simulation.asc_conversion.success",
                "ASC 转换完成。\n输出目录：{path}\n文件数量：{count}\n降级：{degraded}\n校验问题：{issues}",
            ).format(
                path=execution.output_root,
                count=converted_count,
                degraded=degraded_count,
                issues=validation_issue_count,
            ),
        )

    def _get_text(self, key: str, default: str) -> str:
        try:
            from shared.i18n_manager import I18nManager
            return I18nManager().get_text(key, default)
        except Exception:
            return default


__all__ = ["SimulationAscConversionPanel"]
