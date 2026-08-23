"""Atomically persist the one authoritative simulation result document.

A committed bundle contains exactly ``result.json``.  Metrics, logs, raw-data
tables, OP reports and images are views derived from that document and are
created only by the manual exporter or in the bundle-external attachment cache.
Keeping the committed bundle this small removes duplicate authorities and makes
the directory rename below a real all-or-nothing publication boundary.
"""

from __future__ import annotations

import json
import errno
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from domain.simulation.data.simulation_artifact_exporter import (
    CANONICAL_RESULTS_DIR,
    RESULT_JSON_FILENAME,
    simulation_artifact_exporter,
)
from domain.simulation.models.simulation_error import SimulationError
from domain.simulation.models.simulation_result import SimulationResult


def _reject_nonstandard_json_constant(token: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant is forbidden: {token}")


@dataclass
class BundlePersistenceResult:
    """Published bundle identity returned after the atomic rename."""

    export_root: Path
    result_path: str


class SimulationArtifactPersistence:
    """Publish one portable ``result.json`` in a new immutable bundle."""

    def persist_bundle(
        self,
        project_root: str,
        result: SimulationResult,
    ) -> BundlePersistenceResult:
        project = self._require_project_root(project_root)
        persisted_result = self._build_persisted_result(project, result)
        final_hint = simulation_artifact_exporter.build_project_export_root(
            project,
            persisted_result,
        )
        staging_root = self._create_staging_root(project, final_hint.name)
        committed_root: Path | None = None

        try:
            simulation_artifact_exporter.write_json(
                simulation_artifact_exporter.result_json_path(staging_root),
                persisted_result.to_dict(),
            )
            self._validate_staged_bundle(staging_root)
            committed_root = self._commit_staged_bundle(
                project,
                persisted_result,
                staging_root,
            )
            result_path = (
                simulation_artifact_exporter.result_json_path(committed_root)
                .relative_to(project)
                .as_posix()
            )
        except Exception:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            self._remove_empty_staging_parent(staging_root.parent)
            if committed_root is not None:
                self._remove_failed_commit(project, committed_root)
            raise

        return BundlePersistenceResult(
            export_root=committed_root,
            result_path=result_path,
        )

    def _build_persisted_result(
        self,
        project_root: Path,
        result: SimulationResult,
    ) -> SimulationResult:
        """Build and strictly validate the sole portable disk representation.

        Request identity belongs to ``SimulationService``.  This persistence
        boundary alone translates an already-approved result into canonical
        project-relative paths, then performs the same strict round-trip used
        by repository reads before any staging/results directory is created.
        """
        if not isinstance(result, SimulationResult):
            raise TypeError("result must be a SimulationResult")
        raw_file = Path(str(result.file_path or "").replace("\\", "/"))
        resolved_file = (
            raw_file.resolve(strict=False)
            if raw_file.is_absolute()
            else (project_root / raw_file).resolve(strict=False)
        )
        try:
            portable_file_path = resolved_file.relative_to(project_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "Simulation artifacts cannot reference a circuit outside the current project"
            ) from exc

        persisted_error = result.error
        if isinstance(persisted_error, SimulationError):
            if persisted_error.file_path is not None:
                raw_error_file = Path(
                    str(persisted_error.file_path).replace("\\", "/")
                )
                resolved_error_file = (
                    raw_error_file.resolve(strict=False)
                    if raw_error_file.is_absolute()
                    else (project_root / raw_error_file).resolve(strict=False)
                )
                if os.path.normcase(str(resolved_error_file)) != os.path.normcase(
                    str(resolved_file)
                ):
                    raise ValueError(
                        "Simulation error circuit identity must match its result"
                    )
            persisted_error = replace(
                persisted_error,
                file_path=(
                    portable_file_path
                    if persisted_error.file_path is not None
                    else None
                ),
            )

        portable_result = replace(
            result,
            file_path=portable_file_path,
            error=persisted_error,
        )
        return SimulationResult.from_dict(portable_result.to_dict())

    def _validate_staged_bundle(self, staging_root: Path) -> None:
        expected_file = simulation_artifact_exporter.result_json_path(staging_root)
        files = {
            path.relative_to(staging_root).as_posix()
            for path in staging_root.rglob("*")
            if path.is_file()
        }
        if files != {RESULT_JSON_FILENAME} or not expected_file.is_file():
            raise RuntimeError(
                f"Staged simulation bundle must contain only {RESULT_JSON_FILENAME}"
            )
        try:
            payload = json.loads(
                expected_file.read_text(encoding="utf-8"),
                parse_constant=_reject_nonstandard_json_constant,
            )
            SimulationResult.from_dict(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError("Staged result.json failed strict validation") from exc

    def _commit_staged_bundle(
        self,
        project_root: Path,
        result: SimulationResult,
        staging_root: Path,
    ) -> Path:
        """Atomically publish a complete directory, retrying name collisions."""
        while True:
            destination = simulation_artifact_exporter.build_project_export_root(
                project_root,
                result,
            )
            self._ensure_safe_destination_parent(project_root, destination.parent)
            try:
                staging_root.rename(destination)
                self._remove_empty_staging_parent(staging_root.parent)
                return destination
            except OSError as exc:
                if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                    continue
                raise

    def _create_staging_root(self, project_root: Path, run_name: str) -> Path:
        results_root = project_root / CANONICAL_RESULTS_DIR
        results_root.mkdir(parents=True, exist_ok=True)
        if self._is_reparse_point(results_root):
            raise ValueError("simulation_results must not be a symlink or junction")
        staging_parent = results_root / ".__bundle_tmp__"
        staging_parent.mkdir(exist_ok=True)
        if self._is_reparse_point(staging_parent):
            raise ValueError(
                "simulation bundle staging directory must not be a symlink or junction"
            )
        return Path(tempfile.mkdtemp(prefix=f"{run_name}-", dir=str(staging_parent)))

    def _ensure_safe_destination_parent(
        self,
        project_root: Path,
        parent: Path,
    ) -> None:
        results_root = (project_root / CANONICAL_RESULTS_DIR).resolve(strict=False)
        if parent.exists() and self._is_reparse_point(parent):
            raise ValueError("simulation bundle destination must not be a symlink or junction")
        parent.mkdir(parents=True, exist_ok=True)
        if self._is_reparse_point(parent):
            raise ValueError("simulation bundle destination must not be a symlink or junction")
        try:
            parent.resolve(strict=False).relative_to(results_root)
        except ValueError as exc:
            raise ValueError("simulation bundle destination escaped the project") from exc

    def _remove_failed_commit(self, project_root: Path, bundle_root: Path) -> None:
        """Remove only the exact directory this transaction just published."""
        results_root = (project_root / CANONICAL_RESULTS_DIR).resolve(strict=False)
        try:
            relative = bundle_root.resolve(strict=False).relative_to(results_root)
        except ValueError:
            return
        if len(relative.parts) < 2 or self._is_reparse_point(bundle_root):
            return
        shutil.rmtree(bundle_root, ignore_errors=True)

    def _require_project_root(self, project_root: str) -> Path:
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError("project_root is required for bundle persistence")
        raw_root = Path(project_root)
        if not raw_root.is_absolute():
            raise ValueError("project_root must be an absolute path")
        if not raw_root.is_dir():
            raise ValueError("project_root must be an existing directory")
        if self._is_reparse_point(raw_root):
            raise ValueError("project_root must not be a symlink or junction")
        return raw_root.resolve(strict=True)

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        return path.is_symlink() or bool(
            getattr(os.path, "isjunction", lambda _path: False)(path)
        )

    @staticmethod
    def _remove_empty_staging_parent(path: Path) -> None:
        try:
            path.rmdir()
        except OSError:
            pass


simulation_artifact_persistence = SimulationArtifactPersistence()


__all__ = [
    "SimulationArtifactPersistence",
    "simulation_artifact_persistence",
    "BundlePersistenceResult",
]
