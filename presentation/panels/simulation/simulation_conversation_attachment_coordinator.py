import hashlib
from pathlib import Path
from typing import Any, List

from domain.simulation.data.simulation_artifact_exporter import simulation_artifact_exporter
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.service.simulation_result_repository import simulation_result_repository
from shared.event_types import (
    EVENT_UI_ACTIVATE_CONVERSATION_TAB,
    EVENT_UI_ATTACH_FILES_TO_CONVERSATION,
)
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_EVENT_BUS


class SimulationConversationAttachmentCoordinator:
    """Render conversation-only derivatives outside immutable result bundles.

    ``result_path`` is resolved through the repository before any file is
    created. Generated JSON/text/PNG files live under the project's ignored
    ``.circuit_ai/temp`` tree; attachment clicks therefore cannot add files to
    or rewrite the canonical simulation bundle.
    """

    def __init__(self, chart_viewer, waveform_widget):
        self._chart_viewer = chart_viewer
        self._waveform_widget = waveform_widget
        self._event_bus = None

    @property
    def event_bus(self):
        if self._event_bus is None:
            self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
        return self._event_bus

    def attach_metrics(
        self,
        project_root: str,
        result_path: str,
        metrics: List[Any],
    ) -> str:
        """Render current metrics into a temporary attachment and publish it.

        The caller is responsible for building ``metrics`` from a
        ``DisplayMetric`` list whose ``target`` fields have already been
        populated by ``MetricTargetService``. We intentionally
        re-export on every call (even if a stale file already exists)
        so the agent never sees outdated target strings after the user
        tweaks them between simulation runs.
        """
        root, result = self._load_attachment_context(project_root, result_path)
        simulation_artifact_exporter.export_metrics(root, result, metrics)
        target_path = simulation_artifact_exporter.metrics_paths(root).json_path
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def attach_output_log(
        self,
        project_root: str,
        result_path: str,
    ) -> str:
        root, result = self._load_attachment_context(project_root, result_path)
        target_path = simulation_artifact_exporter.output_log_paths(root).text_path
        simulation_artifact_exporter.export_output_log(root, result)
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def attach_op_result(
        self,
        project_root: str,
        result_path: str,
    ) -> str:
        root, result = self._load_attachment_context(project_root, result_path)
        op_paths = simulation_artifact_exporter.op_result_paths(root)
        text_path = op_paths.text_path
        json_path = op_paths.json_path
        simulation_artifact_exporter.export_op_result(root, result)
        self._ensure_file(text_path)
        self._ensure_file(json_path)
        self._publish([str(text_path), str(json_path)])
        return str(json_path)

    def attach_chart_image(
        self,
        project_root: str,
        result_path: str,
    ) -> str:
        root, result = self._load_attachment_context(project_root, result_path)
        charts_paths = simulation_artifact_exporter.charts_paths(root)
        charts_paths.directory.mkdir(parents=True, exist_ok=True)
        target_path = charts_paths.conversation_snapshot_png_path
        if not self._chart_viewer.export_current_image(str(target_path)):
            raise ValueError("No chart image available for conversation attachment")
        simulation_artifact_exporter.inject_png_linkage(target_path, result, "chart")
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def attach_waveform_image(
        self,
        project_root: str,
        result_path: str,
    ) -> str:
        root, result = self._load_attachment_context(project_root, result_path)
        waveforms_paths = simulation_artifact_exporter.waveforms_paths(root)
        waveforms_paths.directory.mkdir(parents=True, exist_ok=True)
        target_path = waveforms_paths.conversation_snapshot_png_path
        if not self._waveform_widget.export_image(str(target_path)):
            raise ValueError("No waveform image available for conversation attachment")
        simulation_artifact_exporter.inject_png_linkage(target_path, result, "waveforms")
        self._ensure_file(target_path)
        self._publish([str(target_path)])
        return str(target_path)

    def _load_attachment_context(
        self,
        project_root: str,
        result_path: str,
    ) -> tuple[Path, SimulationResult]:
        # Conversation attachments are views of an already-persisted result,
        # never a second persistence path. The old fallback silently created a
        # new directory with no result.json when the displayed bundle was
        # stale, producing orphan artifacts that looked authoritative.
        loaded = simulation_result_repository.load(project_root, result_path)
        if not loaded.success or loaded.data is None:
            raise ValueError(
                loaded.error_message or "The displayed simulation bundle no longer exists"
            )
        bundle_root = simulation_result_repository.resolve_bundle_dir(project_root, result_path)
        if bundle_root is None:
            raise ValueError("The displayed simulation bundle no longer exists")
        result_json_path = simulation_artifact_exporter.result_json_path(bundle_root)
        if not result_json_path.is_file():
            raise ValueError("The displayed simulation bundle is incomplete")
        # Attachments are mutable, user-session derivatives. Keep them outside
        # the canonical result.json-only bundle so previews cannot mutate the
        # committed result identity or contents.
        result_key = hashlib.sha256(str(result_path).encode("utf-8")).hexdigest()[:16]
        attachment_root = (
            Path(project_root).resolve()
            / ".circuit_ai"
            / "temp"
            / "simulation_attachments"
            / result_key
        )
        attachment_root.mkdir(parents=True, exist_ok=True)
        return attachment_root, loaded.data

    def _ensure_file(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(str(path))

    def _publish(self, paths: List[str]) -> None:
        if self.event_bus is None:
            raise RuntimeError("Event bus is unavailable")
        payload = {"paths": list(paths)}
        self.event_bus.publish(EVENT_UI_ATTACH_FILES_TO_CONVERSATION, payload)
        self.event_bus.publish(EVENT_UI_ACTIVATE_CONVERSATION_TAB, {})


__all__ = ["SimulationConversationAttachmentCoordinator"]
