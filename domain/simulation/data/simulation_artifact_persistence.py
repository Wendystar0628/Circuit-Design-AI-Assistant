"""Headless simulation artifact persistence.

This service owns the **disk side-effect** of every simulation, no
matter who triggered it. It takes a fully-populated
``SimulationResult`` plus the project root, resolves the canonical
bundle location (``<project_root>/simulation_results/<stem>/<ts>/``),
and writes the ``result.json`` root plus every headless artifact
category (see ``HEADLESS_ARTIFACT_CATEGORIES`` in
``simulation_artifact_exporter``) and a bundle-root
``export_manifest.json`` summary.

Concrete file layout — including per-category filenames — is owned
by ``simulation_artifact_exporter`` (Step 15 canonical layout schema);
this service only decides **which** categories to emit and **in what
order**. It never constructs artifact paths itself.

UI chart/waveform PNG rendering is intentionally **not** performed
here — that still runs in the display layer because it needs the
user's current viewport / signal-visibility state. Agents that want
waveform or chart files invoke dedicated read tools which render
matplotlib PNGs on demand; those tools reuse the same bundle directory
so nothing moves around.

The service is deliberately free of Qt, EventBus, and ServiceLocator
dependencies: every input flows through function arguments so the
same call site is exercised by the UI's simulation pipeline, the
agent's job manager, and standalone unit tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from domain.simulation.data.op_result_data_builder import op_result_data_builder
from domain.simulation.data.simulation_artifact_exporter import (
    ARTIFACT_TYPE_EXPORT_MANIFEST,
    CATEGORY_ANALYSIS_INFO,
    CATEGORY_METRICS,
    CATEGORY_OP_RESULT,
    CATEGORY_OUTPUT_LOG,
    CATEGORY_RAW_DATA,
    HEADLESS_ARTIFACT_CATEGORIES,
    RESULT_JSON_FILENAME,
    simulation_artifact_exporter,
)
from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.service.display_metric_builder import display_metric_builder
from domain.simulation.service.simulation_result_repository import (
    simulation_result_repository,
)


_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Artifact categories
# ---------------------------------------------------------------------------
#
# Write order: ``HEADLESS_ARTIFACT_CATEGORIES`` declared by the
# exporter is the single source of truth. ``op_result`` is conditional
# on ``op_result_data_builder.is_available(result)``. Exposed as
# ``ARTIFACT_CATEGORY_ORDER`` purely for the (unchanged) public
# ``__all__`` contract of this module.

ARTIFACT_CATEGORY_ORDER = HEADLESS_ARTIFACT_CATEGORIES


@dataclass
class BundlePersistenceResult:
    """Outcome of a single ``persist_bundle`` call."""

    export_root: Path
    """Resolved bundle directory (``simulation_results/<stem>/<ts>/``)."""

    result_path: str
    """``result.json`` path, POSIX, relative to ``project_root``."""

    written_files: List[str] = field(default_factory=list)
    """All successfully-written file paths (absolute)."""

    category_files: Dict[str, List[str]] = field(default_factory=dict)
    """Per-category mapping of written files (relative to export_root)."""

    errors: List[Dict[str, str]] = field(default_factory=list)
    """Per-category failures; empty when everything succeeded."""

    @property
    def success(self) -> bool:
        return not self.errors


class SimulationArtifactPersistence:
    """Write the full bundle for a simulation result in one call."""

    def persist_bundle(
        self,
        project_root: str,
        result: SimulationResult,
        metric_targets: Optional[Mapping[str, str]] = None,
    ) -> BundlePersistenceResult:
        """Create the bundle directory and flush every pure-data artifact.

        Args:
            project_root: Absolute project directory.
            result: Fully-populated simulation result.
            metric_targets: ``{metric_name: target_text}`` map. The UI
                caller passes ``MetricTargetService.get_targets_for_file``;
                headless callers (agent job manager) pass ``{}``.
        """
        if not project_root:
            raise ValueError("project_root is required for bundle persistence")

        export_root = simulation_artifact_exporter.build_project_export_root(
            project_root, result
        )
        export_root.mkdir(parents=True, exist_ok=True)

        result_rel_path = simulation_result_repository.save(
            project_root=project_root,
            result=result,
            export_root=export_root,
        )
        result_abs_path = simulation_artifact_exporter.result_json_path(export_root)

        outcome = BundlePersistenceResult(
            export_root=export_root,
            result_path=result_rel_path,
            written_files=[str(result_abs_path)],
            category_files={RESULT_JSON_FILENAME: [RESULT_JSON_FILENAME]},
        )

        metrics = self._build_display_metrics(result, metric_targets)

        for category in ARTIFACT_CATEGORY_ORDER:
            if category == CATEGORY_OP_RESULT and not op_result_data_builder.is_available(result):
                continue
            try:
                files = self._export_category(export_root, result, category, metrics)
            except Exception as exc:  # pragma: no cover - defensive
                _LOGGER.warning(
                    "Bundle category '%s' failed to persist: %s", category, exc
                )
                outcome.errors.append({"artifact_type": category, "message": str(exc)})
                continue
            outcome.written_files.extend(files)
            outcome.category_files[category] = self._as_relative(export_root, files)

        manifest_path = self._write_manifest(export_root, result, outcome)
        outcome.written_files.append(str(manifest_path))
        outcome.category_files[ARTIFACT_TYPE_EXPORT_MANIFEST] = [manifest_path.name]

        return outcome

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_display_metrics(
        self,
        result: SimulationResult,
        metric_targets: Optional[Mapping[str, str]],
    ) -> List[DisplayMetric]:
        return display_metric_builder.build(result, metric_targets or {})

    def _export_category(
        self,
        export_root: Path,
        result: SimulationResult,
        category: str,
        metrics: Sequence[DisplayMetric],
    ) -> List[str]:
        """Dispatch one category to its exporter method.

        Every entry in the dispatch table below uses the same
        ``(export_root, result, metrics)`` signature so there is no
        ``kind: str`` polymorphism — the category string is used once,
        as a dict key, and never again. Adding a category is an entry
        in the table plus a helper in ``simulation_artifact_exporter``.
        """
        runner = self._CATEGORY_RUNNERS.get(category)
        if runner is None:
            raise ValueError(f"Unknown artifact category: {category}")
        return runner(export_root, result, metrics)

    # Dispatch table: each runner accepts ``(export_root, result,
    # metrics)`` and returns the list of written file paths. Runners
    # that do not consume ``metrics`` simply ignore the argument — the
    # uniform signature is what lets us avoid kind-string branching.
    _CATEGORY_RUNNERS = {
        CATEGORY_METRICS:       lambda root, result, metrics:
            simulation_artifact_exporter.export_metrics(root, result, list(metrics)),
        CATEGORY_ANALYSIS_INFO: lambda root, result, metrics:
            simulation_artifact_exporter.export_analysis_info(root, result),
        CATEGORY_RAW_DATA:      lambda root, result, metrics:
            simulation_artifact_exporter.export_raw_data(root, result),
        CATEGORY_OUTPUT_LOG:    lambda root, result, metrics:
            simulation_artifact_exporter.export_output_log(root, result),
        CATEGORY_OP_RESULT:     lambda root, result, metrics:
            simulation_artifact_exporter.export_op_result(root, result),
    }

    def _write_manifest(
        self,
        export_root: Path,
        result: SimulationResult,
        outcome: BundlePersistenceResult,
    ) -> Path:
        manifest_path = simulation_artifact_exporter.export_manifest_path(export_root)
        persisted_categories = [
            category
            for category in (RESULT_JSON_FILENAME, *ARTIFACT_CATEGORY_ORDER)
            if category in outcome.category_files
        ]
        payload = simulation_artifact_exporter.build_artifact_payload(
            result,
            ARTIFACT_TYPE_EXPORT_MANIFEST,
            summary={
                "category_count": len(persisted_categories),
                "exported_file_count": len(outcome.written_files) + 1,
                "error_count": len(outcome.errors),
            },
            files={
                "categories": {
                    category: outcome.category_files.get(category, [])
                    for category in persisted_categories
                },
                "manifest": manifest_path.name,
            },
            data={
                "persisted_categories": persisted_categories,
                "exported_files": self._as_relative(
                    export_root, [*outcome.written_files, str(manifest_path)]
                ),
                "errors": outcome.errors,
            },
        )
        manifest_path.write_text(
            simulation_artifact_exporter.dumps_json(payload),
            encoding="utf-8",
        )
        return manifest_path

    def _as_relative(self, export_root: Path, file_paths: Sequence[str]) -> List[str]:
        root = export_root.resolve()
        relative: List[str] = []
        for file_path in file_paths:
            path = Path(file_path)
            try:
                relative.append(
                    path.resolve().relative_to(root).as_posix()
                )
            except Exception:
                relative.append(path.name)
        return relative


simulation_artifact_persistence = SimulationArtifactPersistence()


__all__ = [
    "SimulationArtifactPersistence",
    "simulation_artifact_persistence",
    "BundlePersistenceResult",
    "ARTIFACT_CATEGORY_ORDER",
]
