"""Tests for ``SimulationService`` — the stateless execution unit.

Step 3 of the job-manager rollout reduces this class to a reentrant
"pick executor → run → persist → return tuple" function and strips
every trace of lifecycle state and event publishing. These tests
lock that contract in place so any regression (resurrecting
``_is_running``, re-importing ``EventBus``, dropping the second
tuple element) fails loudly the moment it's reintroduced.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from domain.services.simulation_service import SimulationService
from domain.simulation.data.simulation_artifact_persistence import (
    BundlePersistenceResult,
)
from domain.simulation.executor.simulation_executor import SimulationExecutor
from domain.simulation.models.simulation_error import (
    ErrorSeverity,
    SimulationError,
    SimulationErrorType,
)
from domain.simulation.models.simulation_result import (
    SimulationData,
    SimulationResult,
    create_error_result,
    create_success_result,
)


# ---------------------------------------------------------------------------
# Fakes — deliberately tiny so test failures point at the service, not the
# test scaffolding.
# ---------------------------------------------------------------------------


class _FakeExecutor(SimulationExecutor):
    def __init__(
        self,
        *,
        extension: str = ".fake",
        success: bool = True,
        raise_exc: Optional[Exception] = None,
    ) -> None:
        self._extension = extension
        self._success = success
        self._raise_exc = raise_exc
        self.execute_calls: List[Tuple[str, Dict[str, Any]]] = []

    def get_name(self) -> str:
        return "fake"

    def get_supported_extensions(self) -> List[str]:
        return [self._extension]

    def get_available_analyses(self) -> List[str]:
        return ["tran"]

    def execute(
        self,
        file_path: str,
        analysis_config: Optional[Dict[str, Any]] = None,
    ) -> SimulationResult:
        self.execute_calls.append((file_path, dict(analysis_config or {})))
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._success:
            return create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=(analysis_config or {}).get("analysis_type", "tran"),
                data=SimulationData(),
            )
        err = SimulationError(
            code="E_FAKE",
            type=SimulationErrorType.PARAMETER_INVALID,
            severity=ErrorSeverity.HIGH,
            message="fake failure",
            file_path=file_path,
        )
        return create_error_result(
            executor=self.get_name(),
            file_path=file_path,
            analysis_type="tran",
            error=err,
        )


class _FakeRegistry:
    def __init__(self, executor: Optional[_FakeExecutor]) -> None:
        self._executor = executor

    def get_executor_for_file(self, file_path: str):
        if self._executor is None:
            return None
        suffix = Path(file_path).suffix.lower()
        if suffix in (e.lower() for e in self._executor.get_supported_extensions()):
            return self._executor
        return None

    def get_all_supported_extensions(self) -> List[str]:
        return list(self._executor.get_supported_extensions()) if self._executor else []


class _FakePersistence:
    def __init__(
        self,
        *,
        raise_on_persist: Optional[Exception] = None,
    ) -> None:
        self._raise = raise_on_persist
        self.calls: List[Tuple[str, SimulationResult]] = []

    def persist_bundle(
        self,
        project_root: str,
        result: SimulationResult,
        metric_targets=None,
    ) -> BundlePersistenceResult:
        self.calls.append((project_root, result))
        if self._raise is not None:
            raise self._raise
        stem = Path(result.file_path).stem or "circuit"
        export_root = Path(project_root) / "simulation_results" / stem / "ts"
        return BundlePersistenceResult(
            export_root=export_root,
            result_path=f"simulation_results/{stem}/ts/result.json",
            written_files=[str(export_root / "result.json")],
        )


# ---------------------------------------------------------------------------
# Surface contract: no lifecycle state, no event-publishing symbols
# ---------------------------------------------------------------------------


def test_service_has_no_lifecycle_state_attributes():
    """Step 3 explicitly forbids ``_is_running`` / ``_last_simulation_file``
    and every ``is_running`` / ``get_last_simulation_file`` query
    method. If any of them come back (even as a benign ``@property``
    returning a constant), this test fails — forcing a deliberate
    design review rather than a drive-by resurrection.
    """
    forbidden_attrs = {
        "_is_running",
        "_last_simulation_file",
        "is_running",
        "get_last_simulation_file",
    }
    service_attrs = set(dir(SimulationService))
    instance = SimulationService(
        registry=_FakeRegistry(_FakeExecutor()),
        artifact_persistence=_FakePersistence(),
    )
    instance_attrs = set(dir(instance))

    leaked = (service_attrs | instance_attrs) & forbidden_attrs
    assert not leaked, (
        f"SimulationService leaked lifecycle-state attributes: {sorted(leaked)}"
    )


def test_service_module_does_not_import_event_bus_or_event_types():
    """The service must have **no** knowledge of ``EventBus`` or any
    ``EVENT_SIM_*`` constant — the manager is the sole publisher.

    We parse the module with :mod:`ast` rather than grepping text so
    the check inspects real import bindings (a docstring mentioning
    ``EventBus`` in a "this module is NOT an event publisher" note
    must not trip the guard). Any actual ``import``/``from`` that
    pulls in the forbidden names fails the test immediately.
    """
    module_path = inspect.getsourcefile(SimulationService)
    assert module_path is not None
    tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))

    forbidden_modules = {"shared.event_bus", "shared.event_types"}
    forbidden_names = {
        "EventBus",
        "EVENT_SIM_STARTED",
        "EVENT_SIM_COMPLETE",
        "EVENT_SIM_ERROR",
    }
    violations: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_modules:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module in forbidden_modules:
                violations.append(
                    f"from {node.module} import "
                    f"{', '.join(a.name for a in node.names)}"
                )
            for alias in node.names:
                if alias.name in forbidden_names:
                    violations.append(
                        f"from {node.module} import {alias.name}"
                    )

    assert not violations, (
        "simulation_service.py must not import EventBus or EVENT_SIM_* "
        f"constants — the manager owns lifecycle events. Got: {violations}"
    )


# ---------------------------------------------------------------------------
# Return contract: always a 2-tuple (SimulationResult, str)
# ---------------------------------------------------------------------------


def test_successful_run_returns_tuple_with_result_and_path():
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    service = SimulationService(
        registry=_FakeRegistry(executor),
        artifact_persistence=persistence,
    )

    outcome = service.run_simulation(
        file_path="amp.fake",
        analysis_config={"analysis_type": "tran"},
        project_root="/tmp/project",
    )

    assert isinstance(outcome, tuple) and len(outcome) == 2, (
        "run_simulation must return a (SimulationResult, result_path) "
        "tuple — never a bare result."
    )
    result, result_path = outcome
    assert isinstance(result, SimulationResult)
    assert result.success is True
    assert result_path == "simulation_results/amp/ts/result.json"
    assert len(persistence.calls) == 1


def test_empty_project_root_skips_persistence_and_yields_empty_path():
    """Headless unit tests may skip persistence by omitting ``project_root``.

    The return shape stays the same — only ``result_path`` is ``""``.
    This is the single exception to "a completed call means a bundle
    on disk"; production callers always pass a project_root.
    """
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    service = SimulationService(
        registry=_FakeRegistry(executor),
        artifact_persistence=persistence,
    )

    result, result_path = service.run_simulation(
        file_path="amp.fake",
        analysis_config={"analysis_type": "tran"},
        project_root=None,
    )
    assert result.success is True
    assert result_path == ""
    assert persistence.calls == []


def test_missing_executor_returns_error_result_without_raising():
    """No-matching-executor is a user error, not a programming error —
    the service reports it via an error-shaped ``SimulationResult``
    (and still persists a bundle for post-mortem)."""
    service = SimulationService(
        registry=_FakeRegistry(None),  # nothing registered
        artifact_persistence=_FakePersistence(),
    )

    result, result_path = service.run_simulation(
        file_path="amp.fake",
        project_root="/tmp/project",
    )
    assert result.success is False
    assert "No executor supports" in (
        result.error.message if isinstance(result.error, SimulationError) else ""
    )
    # Error bundles are still persisted.
    assert result_path == "simulation_results/amp/ts/result.json"


def test_executor_exception_is_captured_into_error_result():
    """Executor crashes must not propagate — the manager relies on
    every call returning a tuple so it can decide lifecycle status
    uniformly."""
    executor = _FakeExecutor(raise_exc=RuntimeError("segfault"))
    service = SimulationService(
        registry=_FakeRegistry(executor),
        artifact_persistence=_FakePersistence(),
    )

    result, result_path = service.run_simulation(
        file_path="amp.fake",
        project_root="/tmp/project",
    )
    assert result.success is False
    assert isinstance(result.error, SimulationError)
    assert "segfault" in result.error.message
    assert result_path == "simulation_results/amp/ts/result.json"


def test_persistence_exception_propagates_to_caller():
    """Persistence failures, unlike executor failures, are not
    shape-compatible with a ``SimulationResult`` — they mean the
    bundle isn't on disk. The service raises so the caller (the
    manager) can mark the job FAILED with a clear error message;
    silently returning an empty ``result_path`` here would let
    completed-looking jobs chase a missing file.
    """
    executor = _FakeExecutor()
    persistence = _FakePersistence(raise_on_persist=OSError("disk full"))
    service = SimulationService(
        registry=_FakeRegistry(executor),
        artifact_persistence=persistence,
    )

    with pytest.raises(OSError, match="disk full"):
        service.run_simulation(
            file_path="amp.fake",
            project_root="/tmp/project",
        )


# ---------------------------------------------------------------------------
# Reentrancy: no hidden shared mutable state
# ---------------------------------------------------------------------------


def test_service_is_reentrant_across_interleaved_calls():
    """Two back-to-back calls with **different** files/configs must
    produce two independent results. Any smuggled state on the service
    (e.g. caching the last file, rebinding analysis_type on self)
    would corrupt the second return value."""
    executor = _FakeExecutor()
    service = SimulationService(
        registry=_FakeRegistry(executor),
        artifact_persistence=_FakePersistence(),
    )

    result_a, path_a = service.run_simulation(
        file_path="amp.fake",
        analysis_config={"analysis_type": "tran"},
        project_root="/tmp/project",
        version=1,
        session_id="session-a",
    )
    result_b, path_b = service.run_simulation(
        file_path="filter.fake",
        analysis_config={"analysis_type": "ac"},
        project_root="/tmp/project",
        version=2,
        session_id="session-b",
    )

    assert result_a.file_path == "amp.fake"
    assert result_a.analysis_type == "tran"
    assert result_a.version == 1
    assert result_a.session_id == "session-a"

    assert result_b.file_path == "filter.fake"
    assert result_b.analysis_type == "ac"
    assert result_b.version == 2
    assert result_b.session_id == "session-b"

    assert path_a != path_b
