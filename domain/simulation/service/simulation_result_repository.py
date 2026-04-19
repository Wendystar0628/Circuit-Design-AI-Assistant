"""Simulation result repository — three-tier read surface.

Every ``SimulationResult`` is serialised to
``<project_root>/simulation_results/<stem>/<ts>/result.json``. That
path sits at the root of the artifact bundle produced by
``SimulationArtifactPersistence`` — ``result.json`` is the first file
written, the other artifact subdirectories (``metrics/``, ``charts/``
…) share the same parent.

Relative ``result_path`` values flowing through the codebase always use
POSIX separators and are rooted at the project directory, e.g.
``simulation_results/amp/2026-04-06_00-10-00/result.json``. The
exporter owns naming of ``<stem>/<ts>`` and collision handling; the
repository simply persists JSON at the resolved path.

Read surface — three clearly separated tiers (Step 8):

  1. :meth:`load` — by-path load (authoritative; agents, UI history
     click, project-open restore all funnel through here).
  2. :meth:`list` — flat, time-descending browse of up to ``limit``
     recent bundles. **History browsing aid only**; forbidden as a
     "what is current?" oracle.
  3. :meth:`list_by_circuit` — per-circuit aggregation. Groups the
     same scan by the authoritative ``circuit_file`` header, keeps
     the most recent ``per_circuit_limit`` bundles per group, sorts
     groups by their newest bundle. This is the single authority for
     "pick a recent result of circuit X"; the Step 16 agent read-tool
     base uses it verbatim to resolve a ``circuit_file`` parameter
     into a concrete ``result_path``.

:meth:`resolve_bundle_dir` exposes the result_path → export_root
resolution; attachment tooling, ExportPanel, and the agent read-tool
base consume it as the single authority for "where does this bundle
live on disk".

No ``get_latest`` helper exists: "which bundle is the UI/agent
currently concerned with" is answered exclusively by the panel's
displayed-triple (Step 7) or by explicit STARTED/COMPLETE payloads;
"most recent run of circuit X" is answered by ``list_by_circuit``.
A tip-of-history probe masquerading as "current result" was the
concrete failure mode that the pre-Step-7 panel shipped with; we
do not reintroduce a single-shot accessor that would tempt the
same misuse.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from domain.simulation.data.simulation_artifact_exporter import (
    CANONICAL_RESULTS_DIR,
    RESULT_JSON_FILENAME,
    simulation_artifact_exporter,
)
from domain.simulation.models.simulation_result import SimulationResult
from shared.models.load_result import LoadResult

# ``RESULT_JSON_FILENAME`` is re-exported here for backwards-compat of
# the repository's public ``__all__``; the authoritative definition
# lives in ``simulation_artifact_exporter`` as part of the canonical
# disk-layout schema (Step 15).


@dataclass(frozen=True)
class SimulationResultSummary:
    """Typed row returned by browsing APIs.

    Replaces the pre-Step-8 ``Dict[str, Any]`` shape so callers access
    ``.result_path`` / ``.timestamp`` rather than dict keys of unknown
    provenance. Every field is a verbatim projection of the on-disk
    ``result.json`` header plus the repository-computed identifiers.

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
            (that is the grouping key). A project-relative POSIX path
            most of the time, but may be absolute if the result was
            produced against a file outside the project tree.
        circuit_absolute_path: The same field resolved against
            ``project_root``. Agents and the circuit-selector tab can
            pass this straight to a file opener.
        results: Recent simulations of this circuit, newest first
            (capped to ``per_circuit_limit`` by the producing call).
    """

    circuit_file: str
    circuit_absolute_path: str
    results: List[SimulationResultSummary] = field(default_factory=list)


class SimulationResultRepository:
    def __init__(self):
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def save(
        self,
        project_root: str,
        result: SimulationResult,
        export_root: Path | None = None,
    ) -> str:
        """Persist ``result`` as ``result.json`` and return its
        project-relative POSIX path.

        Args:
            project_root: Absolute project directory.
            result: The simulation result to persist.
            export_root: Optional pre-resolved bundle directory. When
                omitted the repository materialises a fresh root via
                ``SimulationArtifactExporter.create_export_root`` so
                callers that do not own persistence still get a valid
                bundle. ``SimulationArtifactPersistence`` always passes
                its own ``export_root`` to keep the bundle single-rooted.
        """
        root = Path(project_root)
        if export_root is None:
            export_root = simulation_artifact_exporter.create_export_root(
                str(root / CANONICAL_RESULTS_DIR),
                result,
            )
        else:
            export_root.mkdir(parents=True, exist_ok=True)

        result_path = simulation_artifact_exporter.result_json_path(export_root)
        content = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
        result_path.write_text(content, encoding="utf-8")

        return self._to_project_relative(root, result_path)

    # ------------------------------------------------------------------
    # Read path — by-path load (tier 1)
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

        root = Path(project_root)
        file_path = root / result_path
        if not file_path.exists():
            return LoadResult.file_missing(result_path)

        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return LoadResult.parse_error(result_path, "文件内容为空")

            data = json.loads(content)
            result = SimulationResult.from_dict(data)
            return LoadResult.ok(result, result_path)
        except json.JSONDecodeError as e:
            return LoadResult.parse_error(result_path, f"JSON 解析失败: {e}")
        except KeyError as e:
            return LoadResult.parse_error(result_path, f"缺少必需字段: {e}")
        except Exception as e:
            return LoadResult.unknown_error(result_path, str(e))

    # ------------------------------------------------------------------
    # Read path — flat time-descending browse (tier 2)
    # ------------------------------------------------------------------

    def list(self, project_root: str, limit: int = 10) -> List[SimulationResultSummary]:
        """Return up to ``limit`` bundle summaries, newest first.

        Ordering is header-timestamp-descending with filesystem
        ``mtime`` as tiebreaker — the JSON ``timestamp`` field is the
        authoritative wall-clock at result-object construction, so two
        bundles flushed in the same filesystem second still order
        correctly when the header timestamps differ at sub-second
        granularity.

        ⚠️ **History browsing aid only.** This endpoint must not be
        consulted to answer "which bundle is the UI/agent currently
        concerned with" — that is the job of the panel's displayed-
        triple (Step 7) and of the explicit STARTED/COMPLETE event
        payload. Anything reaching for :meth:`list` as a
        "current result" oracle is a contract violation surfaced at
        review time.

        Args:
            project_root: Absolute project directory.
            limit: Soft cap on returned summaries. Callers treat this
                as "the most recent N"; the repository does not
                window or paginate further.

        Returns:
            A list of :class:`SimulationResultSummary`, newest-first.
            Empty when the ``simulation_results/`` tree is absent.
        """
        root = Path(project_root)
        results_dir = root / CANONICAL_RESULTS_DIR
        if not results_dir.exists():
            return []

        candidates = self._collect_summaries(root, results_dir)
        candidates.sort(
            key=lambda pair: (pair[0].timestamp, pair[1]),
            reverse=True,
        )
        return [summary for summary, _mtime in candidates[:limit]]

    # ------------------------------------------------------------------
    # Read path — per-circuit aggregation (tier 3)
    # ------------------------------------------------------------------

    def list_by_circuit(
        self,
        project_root: str,
        per_circuit_limit: int = 5,
    ) -> List[CircuitResultGroup]:
        """Scan once, group by authoritative ``circuit_file``, return
        groups sorted by each group's newest bundle.

        Upstream of both the history tab (flattened view) and the
        circuit-selector tab (grouped view). Because grouping keys
        come from the persisted ``result.json`` header — never from
        the on-disk ``<stem>/`` directory name — a circuit that was
        renamed or moved between runs still coalesces correctly.

        Group ordering: descending by the newest member's timestamp,
        so ``list_by_circuit(...)[0].results[0]`` is the global most
        recent bundle (same tip-of-history as
        ``list(..., limit=1)[0]``). This equivalence is what lets
        the project-open restore flow switch its entry point from
        the flat list to aggregation without changing UX semantics.

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
        root = Path(project_root)
        results_dir = root / CANONICAL_RESULTS_DIR
        if not results_dir.exists():
            return []

        buckets: dict[str, List[tuple[SimulationResultSummary, float]]] = {}
        for summary, mtime in self._collect_summaries(root, results_dir):
            key = summary.circuit_file or ""
            buckets.setdefault(key, []).append((summary, mtime))

        groups: List[CircuitResultGroup] = []
        for circuit_file, members in buckets.items():
            members.sort(
                key=lambda pair: (pair[0].timestamp, pair[1]),
                reverse=True,
            )
            trimmed = [summary for summary, _mtime in members[:per_circuit_limit]]
            if not trimmed:
                continue
            groups.append(
                CircuitResultGroup(
                    circuit_file=circuit_file,
                    circuit_absolute_path=self._resolve_circuit_absolute(root, circuit_file),
                    results=trimmed,
                )
            )

        groups.sort(
            key=lambda group: group.results[0].timestamp if group.results else "",
            reverse=True,
        )
        return groups

    # ------------------------------------------------------------------
    # Read path — bundle-dir resolution (shared by ExportPanel / agent)
    # ------------------------------------------------------------------

    def resolve_bundle_dir(self, project_root: str, result_path: str) -> Optional[Path]:
        """Resolve a ``result_path`` to its absolute bundle directory.

        A bundle's ``result.json`` always lives at
        ``<bundle_dir>/result.json`` by construction (see module
        header), so the bundle directory is exactly the parent of the
        joined path. Existence is checked to reject stale paths
        upfront — callers that only need the path shape can
        short-circuit the disk hit by building their own, but every
        production site routes through here so attachment tooling,
        ExportPanel, and agent read-tools cannot drift.

        Returns:
            The absolute ``Path`` to the bundle directory, or ``None``
            when ``project_root``/``result_path`` are empty or the
            resolved bundle directory does not exist.
        """
        if not project_root or not result_path:
            return None
        bundle_dir = (Path(project_root) / result_path.replace("\\", "/")).parent
        if not bundle_dir.is_dir():
            return None
        return bundle_dir

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def delete(self, project_root: str, result_path: str) -> bool:
        """Remove the entire bundle identified by ``result_path``.

        Deleting a result removes the whole ``<stem>/<ts>/`` directory —
        ``result.json`` and every sibling artifact share a single fate.
        """
        root = Path(project_root)
        file_path = root / result_path
        if not file_path.exists():
            return False

        bundle_dir = file_path.parent
        try:
            import shutil

            if bundle_dir.is_dir() and bundle_dir.name != CANONICAL_RESULTS_DIR:
                shutil.rmtree(bundle_dir)
            else:
                file_path.unlink()
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
        """Single filesystem scan, shared by :meth:`list` and
        :meth:`list_by_circuit`.

        Returns ``(summary, mtime)`` pairs so downstream sorters can
        break timestamp ties deterministically without re-stat'ing.
        Malformed ``result.json`` files are skipped with a debug log
        — a corrupt bundle must never take down the whole history
        view.
        """
        pairs: List[tuple[SimulationResultSummary, float]] = []
        for file_path in results_dir.rglob(RESULT_JSON_FILENAME):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                data = json.loads(content)
                mtime = file_path.stat().st_mtime
            except Exception as e:
                self._logger.debug(
                    f"Failed to read simulation result summary {file_path}: {e}"
                )
                continue
            summary = SimulationResultSummary(
                id=self._derive_bundle_id(project_root, file_path),
                result_path=self._to_project_relative(project_root, file_path),
                circuit_file=str(data.get("file_path", "") or ""),
                analysis_type=str(data.get("analysis_type", "") or ""),
                success=bool(data.get("success", False)),
                timestamp=str(data.get("timestamp", "") or ""),
            )
            pairs.append((summary, mtime))
        return pairs

    def _to_project_relative(self, project_root: Path, file_path: Path) -> str:
        try:
            relative = file_path.resolve().relative_to(project_root.resolve())
        except ValueError:
            relative = Path(file_path)
        return relative.as_posix()

    def _derive_bundle_id(self, project_root: Path, file_path: Path) -> str:
        parent = file_path.parent
        try:
            relative = parent.resolve().relative_to(project_root.resolve())
            return relative.as_posix()
        except ValueError:
            return parent.name

    def _resolve_circuit_absolute(self, project_root: Path, circuit_file: str) -> str:
        """Resolve the authoritative ``circuit_file`` header into an
        absolute filesystem path.

        Circuit files persisted inside ``result.json`` are usually
        project-relative POSIX paths, but legacy or externally-
        produced results may be absolute. Both are handled the same
        way: absolute stays absolute; relative is joined with
        ``project_root``. No stem/directory-name reverse inference.
        """
        if not circuit_file:
            return ""
        candidate = Path(circuit_file.replace("\\", "/"))
        if candidate.is_absolute():
            return str(candidate)
        return str(project_root / candidate)


simulation_result_repository = SimulationResultRepository()


__all__ = [
    "SimulationResultRepository",
    "simulation_result_repository",
    "SimulationResultSummary",
    "CircuitResultGroup",
    "RESULT_JSON_FILENAME",
]
