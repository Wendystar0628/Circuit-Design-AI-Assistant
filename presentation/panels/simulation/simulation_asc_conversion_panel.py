from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from domain.simulation.spice.ltspice_asc_to_cir_transcriber import (
    AscBatchConversionExecution,
    LtspiceAscToCirTranscriber,
)


class SimulationAscConversionPanel(QObject):
    OUTPUT_DIRECTORY_NAME = "cir"
    state_changed = pyqtSignal()
    _conversion_finished = pyqtSignal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dialog_parent = parent if isinstance(parent, QWidget) else None
        self._project_root: Optional[Path] = None
        self._selected_files_summary = ""
        self._is_running = False
        self._project_generation = 0
        self._conversion_finished.connect(self._on_conversion_finished)
        self.retranslate_ui()

    def set_project_root(self, project_root: str) -> None:
        normalized = str(project_root or "").strip()
        self._project_root = Path(normalized).resolve() if normalized else None
        self._project_generation += 1
        self._selected_files_summary = ""

    def get_web_snapshot(self) -> dict:
        return {
            "can_choose_files": self._project_root is not None and not self._is_running,
            "is_running": self._is_running,
            "selected_files_summary": self._selected_files_summary,
        }

    def choose_files_and_convert(self) -> Optional[bool]:
        if self._project_root is None:
            QMessageBox.warning(
                self._dialog_parent,
                self._get_text("dialog.warning.title", "警告"),
                self._get_text("simulation.asc_conversion.no_project", "请先打开项目，再执行 ASC 转换。"),
            )
            return None
        if self._is_running:
            return None
        file_paths, _selected_filter = QFileDialog.getOpenFileNames(
            self._dialog_parent,
            self._get_text("simulation.asc_conversion.choose_files", "选择 ASC 文件"),
            str(self._project_root),
            "LTspice ASC Files (*.asc)",
        )
        if not file_paths:
            return None
        output_root = self._project_root / self.OUTPUT_DIRECTORY_NAME
        generation = self._project_generation
        transcriber = LtspiceAscToCirTranscriber()
        self._is_running = True
        self._selected_files_summary = self._get_text(
            "simulation.asc_conversion.running",
            "正在转换 {count} 个 .asc 文件…",
        ).format(count=len(file_paths))
        self.state_changed.emit()

        def run_conversion() -> None:
            try:
                execution = transcriber.convert_files(file_paths, str(output_root))
                self._conversion_finished.emit(generation, execution, "")
            except Exception as exc:
                self._conversion_finished.emit(generation, None, str(exc))

        threading.Thread(
            target=run_conversion,
            name="asc-conversion",
            daemon=True,
        ).start()
        return True

    def _on_conversion_finished(
        self,
        generation: int,
        execution: Optional[AscBatchConversionExecution],
        error_message: str,
    ) -> None:
        # Conversion is process-wide single-flight for this panel. A project
        # switch invalidates presentation of the old result, but it cannot
        # stop the worker that may still be writing its original output root.
        # Keep the action disabled until that worker has actually finished.
        self._is_running = False
        if generation != self._project_generation:
            self._selected_files_summary = ""
            self.state_changed.emit()
            return
        if execution is None:
            self._selected_files_summary = ""
            self.state_changed.emit()
            QMessageBox.warning(
                self._dialog_parent,
                self._get_text("simulation.asc_conversion.title", "ASC 转换"),
                self._get_text(
                    "simulation.asc_conversion.failed",
                    "ASC 转换失败：{message}",
                ).format(message=error_message or "unknown error"),
            )
            return
        self._selected_files_summary = self._get_text(
            "simulation.asc_conversion.summary",
            "已处理 {total} 个 .asc 文件（成功 {success}，失败 {failed}）",
        ).format(
            total=len(execution.converted_files) + len(execution.failed_files),
            success=len(execution.converted_files),
            failed=len(execution.failed_files),
        )
        self.state_changed.emit()
        self._show_execution_result(execution)

    def clear(self) -> None:
        self._selected_files_summary = ""

    def retranslate_ui(self) -> None:
        return

    def _show_execution_result(self, execution: AscBatchConversionExecution) -> None:
        converted_count = len(execution.converted_files)
        failed_count = len(execution.failed_files)
        degraded_count = sum(1 for item in execution.converted_files if item.degraded)
        validation_issue_count = sum(len(item.validation_errors) for item in execution.converted_files)
        if failed_count:
            QMessageBox.warning(
                self._dialog_parent,
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
            self._dialog_parent,
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
