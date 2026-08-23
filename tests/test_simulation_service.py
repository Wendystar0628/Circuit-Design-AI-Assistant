"""Tests for ``SimulationService`` — the stateless execution unit.

The service is a reentrant "pick executor → run → persist → return exact
path" function with no lifecycle state or event publishing. These tests lock
that contract in place so any regression (resurrecting
``_is_running``, re-importing ``EventBus``, or returning a second
in-memory authority) fails loudly the moment it's reintroduced.
"""

from __future__ import annotations

import ast
import inspect
import json
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
import pytest

from domain.services.simulation_service import SimulationService
from domain.simulation.data.simulation_artifact_persistence import (
    BundlePersistenceResult,
)
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


_FAKE_SOURCE_DIGEST = "0" * 64
_UNSET = object()


def _fake_simulation_data(analysis_type: str) -> SimulationData:
    if analysis_type in {"ac", "noise"}:
        return SimulationData(
            frequency=np.array([1.0, 10.0]),
            signals={"V(out)": np.array([1.0, 0.5])},
            signal_types={"V(out)": "voltage"},
        )
    if analysis_type == "dc":
        return SimulationData(
            sweep=np.array([0.0, 1.0]),
            signals={"V(out)": np.array([0.0, 1.0])},
            signal_types={"V(out)": "voltage"},
        )
    return SimulationData(
        time=np.array([0.0, 1e-3]),
        signals={"V(out)": np.array([0.0, 1.0])},
        signal_types={"V(out)": "voltage"},
    )


# ---------------------------------------------------------------------------
# Fakes — deliberately tiny so test failures point at the service, not the
# test scaffolding.
# ---------------------------------------------------------------------------


class _FakeExecutor:
    def __init__(
        self,
        *,
        extension: str = ".fake",
        success: bool = True,
        raise_exc: Optional[Exception] = None,
        returned: Any = _UNSET,
    ) -> None:
        self._extension = extension
        self._success = success
        self._raise_exc = raise_exc
        self._returned = returned
        self.execute_calls: List[Tuple[str, Optional[threading.Event]]] = []

    def get_name(self) -> str:
        return "spice"

    def get_supported_extensions(self) -> List[str]:
        return [self._extension]

    def can_handle(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() == self._extension.lower()

    def execute(
        self,
        file_path: str,
        *,
        cancel_signal: Optional[threading.Event] = None,
    ) -> Any:
        self.execute_calls.append((file_path, cancel_signal))
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._returned is not _UNSET:
            return self._returned
        if self._success:
            analysis_type = "tran"
            return create_success_result(
                executor=self.get_name(),
                file_path=file_path,
                analysis_type=analysis_type,
                analysis_command=".tran 1e-4 1e-3",
                data=_fake_simulation_data(analysis_type),
                source_digest=_FAKE_SOURCE_DIGEST,
            )
        err = SimulationError(
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
    ) -> BundlePersistenceResult:
        self.calls.append((project_root, result))
        if self._raise is not None:
            raise self._raise
        stem = Path(result.file_path).stem or "circuit"
        export_root = Path(project_root) / "simulation_results" / stem / "ts"
        return BundlePersistenceResult(
            export_root=export_root,
            result_path=f"simulation_results/{stem}/ts/result.json",
        )


# ---------------------------------------------------------------------------
# Surface contract: no lifecycle state, no event-publishing symbols
# ---------------------------------------------------------------------------


def test_service_has_no_lifecycle_state_attributes():
    """The service forbids ``_is_running`` / ``_last_simulation_file`` and
    every ``is_running`` / ``get_last_simulation_file`` query method. If any
    of them come back, this test forces a deliberate design review rather
    than accepting a second lifecycle authority.
    """
    forbidden_attrs = {
        "_is_running",
        "_last_simulation_file",
        "is_running",
        "get_last_simulation_file",
    }
    service_attrs = set(dir(SimulationService))
    instance = SimulationService(
        executor=_FakeExecutor(),
        artifact_persistence=_FakePersistence(),
    )
    instance_attrs = set(dir(instance))

    leaked = (service_attrs | instance_attrs) & forbidden_attrs
    assert not leaked, (
        f"SimulationService leaked lifecycle-state attributes: {sorted(leaked)}"
    )


def test_service_exposes_only_the_explicit_cancellation_channel():
    parameters = inspect.signature(SimulationService.run_simulation).parameters
    assert "analysis_config" not in parameters
    assert "cancel_signal" in parameters


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
# Return contract: only the exact persisted result_path
# ---------------------------------------------------------------------------


def test_successful_run_returns_only_authoritative_result_path(tmp_path):
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    service = SimulationService(
        executor=executor,
        artifact_persistence=persistence,
    )

    outcome = service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
    )

    assert outcome == "simulation_results/amp/ts/result.json"
    assert len(persistence.calls) == 1
    persisted_input = persistence.calls[0][1]
    assert isinstance(persisted_input, SimulationResult)
    assert persisted_input.success is True
    assert Path(persisted_input.file_path) == (tmp_path / "amp.fake").resolve()
    assert persisted_input.source_digest == _FAKE_SOURCE_DIGEST
    assert executor.execute_calls == [
        (str((tmp_path / "amp.fake").resolve()), None)
    ]


def test_cancel_signal_uses_the_explicit_executor_channel(tmp_path):
    executor = _FakeExecutor()
    service = SimulationService(
        executor=executor,
        artifact_persistence=_FakePersistence(),
    )
    cancel_signal = threading.Event()

    service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
        cancel_signal=cancel_signal,
    )

    assert executor.execute_calls == [
        (str((tmp_path / "amp.fake").resolve()), cancel_signal)
    ]


def test_source_digest_survives_the_real_persistence_roundtrip(tmp_path):
    service = SimulationService(executor=_FakeExecutor())

    result_path = service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
    )

    payload = json.loads((tmp_path / result_path).read_text(encoding="utf-8"))
    persisted = SimulationResult.from_dict(payload)
    assert persisted.file_path == "amp.fake"
    assert persisted.source_digest == _FAKE_SOURCE_DIGEST


@pytest.mark.parametrize("project_root", [None, "", "   "])
def test_project_root_is_mandatory_for_every_result_bundle(project_root):
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    service = SimulationService(
        executor=executor,
        artifact_persistence=persistence,
    )

    with pytest.raises(ValueError, match="project_root is required"):
        service.run_simulation(
            file_path="amp.fake",
            project_root=project_root,
        )
    assert persistence.calls == []


def test_project_root_must_be_an_absolute_existing_directory(tmp_path):
    service = SimulationService(
        executor=_FakeExecutor(),
        artifact_persistence=_FakePersistence(),
    )

    with pytest.raises(ValueError, match="absolute directory"):
        service.run_simulation(
            file_path="amp.fake",
            project_root="relative-project",
        )

    missing = tmp_path / "missing-project"
    with pytest.raises(ValueError, match="existing directory"):
        service.run_simulation(
            file_path="amp.fake",
            project_root=str(missing),
        )


def test_executor_is_mandatory_at_composition_boundary():
    with pytest.raises(TypeError, match="executor is required"):
        SimulationService(
            executor=None,
            artifact_persistence=_FakePersistence(),
        )


def test_circuit_path_cannot_escape_the_project_root(tmp_path):
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    service = SimulationService(
        executor=executor,
        artifact_persistence=persistence,
    )

    with pytest.raises(ValueError, match="inside project_root"):
        service.run_simulation(
            file_path="../outside.fake",
            project_root=str(tmp_path),
        )

    assert executor.execute_calls == []
    assert persistence.calls == []


def test_unsupported_extension_returns_error_result_without_raising(tmp_path):
    """A non-SPICE extension is a user error, not a programming error —
    the service reports it via an error-shaped ``SimulationResult``
    (and still persists a bundle for post-mortem)."""
    persistence = _FakePersistence()
    service = SimulationService(
        executor=_FakeExecutor(extension=".other"),
        artifact_persistence=persistence,
    )

    result_path = service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
    )
    result = persistence.calls[0][1]
    assert result.success is False
    assert result.analysis_type == "unknown"
    assert "Unsupported circuit file type" in (
        result.error.message if isinstance(result.error, SimulationError) else ""
    )
    # Error bundles are still persisted.
    assert result_path == "simulation_results/amp/ts/result.json"


def test_executor_exception_is_captured_into_error_result(tmp_path):
    """Executor crashes must not propagate — the manager relies on
    every call committing a diagnostic result so it can decide lifecycle
    status from the repository."""
    executor = _FakeExecutor(raise_exc=RuntimeError("segfault"))
    persistence = _FakePersistence()
    service = SimulationService(
        executor=executor,
        artifact_persistence=persistence,
    )

    result_path = service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
    )
    result = persistence.calls[0][1]
    assert result.success is False
    assert isinstance(result.error, SimulationError)
    assert "segfault" in result.error.message
    assert result_path == "simulation_results/amp/ts/result.json"


def test_empty_executor_exception_still_commits_a_diagnostic_result(tmp_path):
    executor = _FakeExecutor(raise_exc=RuntimeError())
    persistence = _FakePersistence()
    service = SimulationService(
        executor=executor,
        artifact_persistence=persistence,
    )

    result_path = service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
    )
    result = persistence.calls[0][1]

    assert result.success is False
    assert isinstance(result.error, SimulationError)
    assert result.error.message == (
        "RuntimeError raised without an error message"
    )
    assert result_path == "simulation_results/amp/ts/result.json"


def test_persistence_exception_propagates_to_caller(tmp_path):
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
        executor=executor,
        artifact_persistence=persistence,
    )

    with pytest.raises(OSError, match="disk full"):
        service.run_simulation(
            file_path="amp.fake",
            project_root=str(tmp_path),
        )


def test_non_result_from_executor_is_rejected_without_publishing(tmp_path):
    persistence = _FakePersistence()
    service = SimulationService(
        executor=_FakeExecutor(returned={"success": True}),
        artifact_persistence=persistence,
    )

    with pytest.raises(TypeError, match="SimulationResult"):
        service.run_simulation(
            file_path="amp.fake",
            project_root=str(tmp_path),
        )

    assert persistence.calls == []


def test_result_for_different_circuit_is_rejected_without_publishing(tmp_path):
    wrong_result = create_success_result(
        executor="fake",
        file_path=str(tmp_path / "other.fake"),
        analysis_type="tran",
        analysis_command=".tran 1e-4 1e-3",
        data=_fake_simulation_data("tran"),
        source_digest=_FAKE_SOURCE_DIGEST,
    )
    persistence = _FakePersistence()
    service = SimulationService(
        executor=_FakeExecutor(returned=wrong_result),
        artifact_persistence=persistence,
    )

    with pytest.raises(ValueError, match="different circuit"):
        service.run_simulation(
            file_path="amp.fake",
            project_root=str(tmp_path),
        )

    assert persistence.calls == []


def test_schema_invalid_result_creates_no_persistence_tree(tmp_path):
    invalid_result = create_success_result(
        executor="fake",
        file_path=str(tmp_path / "amp.fake"),
        analysis_type="tran",
        analysis_command=".tran 1e-4 1e-3",
        data=_fake_simulation_data("tran"),
        source_digest=_FAKE_SOURCE_DIGEST,
    )
    invalid_result.source_digest = "not-a-sha256"
    service = SimulationService(
        executor=_FakeExecutor(returned=invalid_result),
    )

    with pytest.raises(ValueError, match="source_digest"):
        service.run_simulation(
            file_path="amp.fake",
            project_root=str(tmp_path),
        )

    assert not (tmp_path / "simulation_results").exists()


# ---------------------------------------------------------------------------
# Reentrancy: no hidden shared mutable state
# ---------------------------------------------------------------------------


def test_service_is_reentrant_across_interleaved_calls(tmp_path):
    """Two back-to-back calls with different files and job identities must
    produce two independent results. Any smuggled state on the service
    (for example caching the last file or session)
    would corrupt the second return value."""
    executor = _FakeExecutor()
    persistence = _FakePersistence()
    service = SimulationService(
        executor=executor,
        artifact_persistence=persistence,
    )

    path_a = service.run_simulation(
        file_path="amp.fake",
        project_root=str(tmp_path),
        version=1,
        session_id="session-a",
    )
    path_b = service.run_simulation(
        file_path="filter.fake",
        project_root=str(tmp_path),
        version=2,
        session_id="session-b",
    )

    result_a = persistence.calls[0][1]
    result_b = persistence.calls[1][1]

    assert Path(result_a.file_path) == (tmp_path / "amp.fake").resolve()
    assert result_a.analysis_type == "tran"
    assert result_a.version == 1
    assert result_a.session_id == "session-a"

    assert Path(result_b.file_path) == (tmp_path / "filter.fake").resolve()
    assert result_b.analysis_type == "tran"
    assert result_b.version == 2
    assert result_b.session_id == "session-b"

    assert path_a != path_b
