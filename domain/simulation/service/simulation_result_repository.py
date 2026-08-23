"""Project-isolated storage for complete simulation bundles.

``result.json`` is addressed only by the exact, canonical POSIX handle
returned when a bundle is committed, for example
``simulation_results/amp/<run>/result.json``.  Loading, resolving and
deleting all pass through the same containment and reparse-point checks.
History APIs exist only for the UI's browse screen; agents never guess a
"latest" result and must keep using the exact handle returned by their run.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import List, Optional

from domain.simulation.data.simulation_artifact_exporter import (
    CANONICAL_RESULTS_DIR,
    RESULT_JSON_FILENAME,
)
from domain.simulation.models.simulation_result import SimulationResult
from shared.models.load_result import LoadResult


def _reject_nonstandard_json_constant(token: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant is forbidden: {token}")


@dataclass(frozen=True)
class SimulationResultSummary:
    """Typed row returned by browsing APIs.

    Every field is a projection of a strictly loaded ``result.json`` plus
    the repository-computed bundle identifiers.

    Attributes:
        id: Project-relative POSIX path of the bundle **directory**.
            Stable across renames/moves only insofar as the bundle
            directory itself is not moved; used as the history-tab
            list key.
        result_path: Project-relative POSIX path to the bundle's
            ``result.json``. The single authoritative handle for
            :meth:`SimulationResultRepository.load`.
        circuit_file: The authoritative circuit-file field persisted
            inside ``result.json``. Read verbatim; never reverse-
            inferred from the on-disk ``<stem>/`` directory name.
        analysis_type: ``"op"``, ``"tran"``, ``"ac"``, …
        success: Whether the simulation run itself succeeded.
        timestamp: ISO-ish header timestamp captured at result-object
            construction time. Used for intra-group ordering in
            aggregation views (independent of filesystem ``mtime``).
    """

    id: str
    result_path: str
    circuit_file: str
    analysis_type: str
    success: bool
    timestamp: str


@dataclass(frozen=True)
class CircuitResultGroup:
    """Per-circuit aggregation of recent simulation bundles.

    Attributes:
        circuit_file: Authoritative circuit-file field from the most
            recent bundle in the group — all members share this value
            (that is the grouping key). It is a canonical project-relative
            POSIX path.
        circuit_absolute_path: Existing source file resolved inside the
            current project, or an empty string when the source disappeared.
        results: Immutable snapshot of recent simulations of this circuit,
            newest first (capped to ``per_circuit_limit`` by the producing
            call).
    """

    circuit_file: str
    circuit_absolute_path: str
    results: tuple[SimulationResultSummary, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))


class SimulationResultRepository:
    def __init__(self):
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Exact result loading
    # ------------------------------------------------------------------

    def load(self, project_root: str, result_path: str) -> LoadResult[SimulationResult]:
        """Load a bundle's ``SimulationResult`` by project-relative path.

        This is the **only** authoritative way to turn a ``result_path``
        into a ``SimulationResult``. Agents, the UI history-click
        branch, the project-open restore path, and the STARTED/COMPLETE
        display branch all funnel through here — no parallel JSON
        parser exists anywhere in the codebase.
        """
        if not result_path:
            return LoadResult.path_empty()

        try:
            root = self._require_project_root(project_root)
        except ValueError as exc:
            return LoadResult.parse_error(result_path, str(exc))
        file_path = self._resolve_result_path(root, result_path, require_existing=False)
        if file_path is None:
            return LoadResult.parse_error(
                result_path,
                "结果路径必须位于当前项目的 simulation_results/<circuit>/<run>/result.json",
            )
        if not file_path.is_file():
            return LoadResult.file_missing(result_path)

        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return LoadResult.parse_error(result_path, "文件内容为空")

            data = json.loads(
                content,
                parse_constant=_reject_nonstandard_json_constant,
            )
            result = SimulationResult.from_dict(data)
            return LoadResult.ok(result, result_path)
        except PermissionError:
            return LoadResult.permission_denied(result_path)
        except json.JSONDecodeError as e:
            return LoadResult.parse_error(result_path, f"JSON 解析失败: {e}")
        except KeyError as e:
            return LoadResult.parse_error(result_path, f"缺少必需字段: {e}")
        except (TypeError, ValueError) as e:
            return LoadResult.parse_error(result_path, f"结果结构无效: {e}")
        except Exception as e:
            return LoadResult.unknown_error(result_path, str(e))

    # ------------------------------------------------------------------
    # UI history browsing
    # ------------------------------------------------------------------

    def list_by_circuit(
        self,
        project_root: str,
        per_circuit_limit: int = 5,
    ) -> List[CircuitResultGroup]:
        """Scan once, group by authoritative ``circuit_file``, return
        groups sorted by each group's newest bundle.

        Grouping uses the project-relative source identity stored in
        ``result.json``, not the bundle folder name. A later circuit rename
        therefore starts a new group.

        Groups and their members are ordered by parsed timestamps, descending,
        with result paths as deterministic tiebreakers.

        Args:
            project_root: Absolute project directory.
            per_circuit_limit: Cap on how many recent results each
                group keeps. Applied after per-group sorting, so
                it is always "the newest ``per_circuit_limit`` runs
                of this circuit".

        Returns:
            A list of :class:`CircuitResultGroup`, group-newest-first.
            Empty when the ``simulation_results/`` tree is absent.
        """
        if per_circuit_limit <= 0:
            return []
        try:
            root = self._require_project_root(project_root)
        except ValueError:
            return []
        results_dir = root / CANONICAL_RESULTS_DIR
        if not results_dir.is_dir() or self._is_reparse_point(results_dir):
            return []

        buckets: dict[str, List[tuple[SimulationResultSummary, float]]] = {}
        for summary, sort_time in self._collect_summaries(root, results_dir):
            key = self._circuit_group_key(summary.circuit_file)
            buckets.setdefault(key, []).append((summary, sort_time))

        groups_with_time: List[tuple[CircuitResultGroup, float]] = []
        for _group_key, members in buckets.items():
            members.sort(
                key=lambda pair: (pair[1], pair[0].result_path.casefold()),
                reverse=True,
            )
            trimmed = tuple(
                summary for summary, _sort_time in members[:per_circuit_limit]
            )
            if not trimmed:
                continue
            circuit_file = trimmed[0].circuit_file
            groups_with_time.append(
                (
                    CircuitResultGroup(
                        circuit_file=circuit_file,
                        circuit_absolute_path=self._resolve_circuit_absolute(root, circuit_file),
                        results=trimmed,
                    ),
                    members[0][1],
                )
            )

        groups_with_time.sort(
            key=lambda item: (item[1], item[0].results[0].result_path.casefold()),
            reverse=True,
        )
        return [group for group, _sort_time in groups_with_time]

    # ------------------------------------------------------------------
    # Exact bundle/source resolution
    # ------------------------------------------------------------------

    def resolve_bundle_dir(self, project_root: str, result_path: str) -> Optional[Path]:
        """Resolve a ``result_path`` to its absolute bundle directory.

        The exact result must exist and pass the same containment checks as
        :meth:`load`; callers cannot use this method to legitimize a guessed
        or stale bundle path.

        Returns:
            The absolute ``Path`` to the bundle directory, or ``None``
            when ``project_root``/``result_path`` are empty or the
            resolved bundle directory does not exist.
        """
        if not project_root or not result_path:
            return None
        try:
            root = self._require_project_root(project_root)
        except ValueError:
            return None
        result_file = self._resolve_result_path(root, result_path, require_existing=True)
        if result_file is None or not result_file.is_file():
            return None
        return result_file.parent

    def resolve_circuit_path(
        self,
        project_root: str,
        circuit_file: str,
    ) -> Optional[Path]:
        """Resolve a persisted circuit identity to an existing project file."""
        if not isinstance(circuit_file, str) or not circuit_file.strip():
            return None
        if "\\" in circuit_file:
            return None
        portable = PurePosixPath(circuit_file)
        if (
            portable.is_absolute()
            or circuit_file != portable.as_posix()
            or any(
                part in {"", ".", ".."} or ":" in part
                for part in portable.parts
            )
        ):
            return None
        try:
            root = self._require_project_root(project_root)
        except ValueError:
            return None
        raw_candidate = root.joinpath(*portable.parts)
        if self._path_has_reparse_component(root, raw_candidate):
            return None
        resolved = raw_candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            return None
        if not resolved.is_file() or self._path_has_reparse_component(root, resolved):
            return None
        return resolved

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def delete(self, project_root: str, result_path: str) -> bool:
        """Remove the entire bundle identified by ``result_path``.

        Deleting a result removes its immutable ``<stem>/<ts>/`` directory.
        """
        try:
            root = self._require_project_root(project_root)
        except ValueError:
            return False
        file_path = self._resolve_result_path(root, result_path, require_existing=True)
        if file_path is None or not file_path.is_file():
            return False

        bundle_dir = file_path.parent
        try:
            import shutil

            shutil.rmtree(bundle_dir)
            return True
        except Exception as e:
            self._logger.error(f"删除仿真结果失败: {e}")
            return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _collect_summaries(
        self,
        project_root: Path,
        results_dir: Path,
    ) -> List[tuple[SimulationResultSummary, float]]:
        """Scan strictly loadable bundles for :meth:`list_by_circuit`.

        Returns ``(summary, sort_time)`` pairs. ``sort_time`` is the parsed
        ISO timestamp normalized to UTC. Missing/invalid timestamps are
        skipped because they cannot participate in a truthful "latest" view.
        Malformed ``result.json`` files are skipped with a debug log
        — a corrupt bundle must never take down the whole history
        view.
        """
        pairs: List[tuple[SimulationResultSummary, float]] = []
        for file_path in results_dir.rglob(RESULT_JSON_FILENAME):
            try:
                lexical_relative = file_path.relative_to(project_root).as_posix()
            except ValueError:
                continue
            loaded = self.load(str(project_root), lexical_relative)
            if not loaded.success or loaded.data is None:
                self._logger.debug(
                    "Skipping invalid simulation result summary %s: %s",
                    file_path,
                    loaded.error_message or "unknown repository error",
                )
                continue
            result = loaded.data
            summary = SimulationResultSummary(
                id=PurePosixPath(lexical_relative).parent.as_posix(),
                result_path=lexical_relative,
                circuit_file=result.file_path,
                analysis_type=result.analysis_type,
                success=result.success,
                timestamp=result.timestamp,
            )
            sort_time = self._timestamp_sort_value(summary.timestamp)
            if sort_time is None:
                self._logger.debug(
                    "Skipping result with invalid timestamp: %s",
                    file_path,
                )
                continue
            pairs.append((summary, sort_time))
        return pairs

    def _resolve_circuit_absolute(self, project_root: Path, circuit_file: str) -> str:
        resolved = self.resolve_circuit_path(str(project_root), circuit_file)
        return str(resolved) if resolved is not None else ""

    def _require_project_root(self, project_root: str) -> Path:
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError("project_root is required")
        raw_root = Path(project_root)
        if not raw_root.is_absolute():
            raise ValueError("project_root must be an absolute path")
        if not raw_root.is_dir():
            raise ValueError("project_root must be an existing directory")
        if self._is_reparse_point(raw_root):
            raise ValueError("project_root must not be a symlink or junction")
        return raw_root.resolve(strict=True)

    def _resolve_result_path(
        self,
        project_root: Path,
        result_path: str,
        *,
        require_existing: bool,
    ) -> Optional[Path]:
        """Resolve a result handle without permitting project escape.

        Absolute paths, ``..`` traversal, alternate filenames, symlinks and
        Windows junctions/reparse points are rejected.  This method is shared
        by load/resolve/delete/history so every result read has one sandbox.
        """
        if not isinstance(result_path, str) or not result_path.strip():
            return None
        if "\\" in result_path:
            return None
        posix_path = PurePosixPath(result_path)
        parts = posix_path.parts
        if (
            posix_path.is_absolute()
            or result_path != posix_path.as_posix()
            or any(part in {"", ".", ".."} or ":" in part for part in parts)
            or len(parts) != 4
            or parts[0] != CANONICAL_RESULTS_DIR
            or parts[-1] != RESULT_JSON_FILENAME
        ):
            return None

        results_root = (project_root / CANONICAL_RESULTS_DIR).resolve(strict=False)
        raw_candidate = project_root.joinpath(*parts)
        if self._path_has_reparse_component(project_root, raw_candidate):
            return None
        candidate = raw_candidate.resolve(strict=False)
        try:
            within_results = candidate.relative_to(results_root)
        except ValueError:
            return None
        if any(part.startswith(".__bundle_tmp__") for part in within_results.parts[:-1]):
            return None
        if require_existing and not candidate.is_file():
            return None
        return candidate

    def _path_has_reparse_component(self, base: Path, candidate: Path) -> bool:
        try:
            relative = candidate.relative_to(base)
        except ValueError:
            return True
        cursor = base
        if cursor.exists() and self._is_reparse_point(cursor):
            return True
        for part in relative.parts:
            cursor = cursor / part
            if cursor.exists() and self._is_reparse_point(cursor):
                return True
        return False

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        return path.is_symlink() or bool(
            getattr(os.path, "isjunction", lambda _path: False)(path)
        )

    def _circuit_group_key(self, circuit_file: str) -> str:
        return str(circuit_file or "").casefold()

    @staticmethod
    def _timestamp_sort_value(timestamp: str) -> Optional[float]:
        candidate = str(timestamp or "").strip()
        if not candidate:
            return None
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                return None
            return parsed.astimezone(timezone.utc).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

simulation_result_repository = SimulationResultRepository()


__all__ = [
    "SimulationResultRepository",
    "simulation_result_repository",
    "SimulationResultSummary",
    "CircuitResultGroup",
]
