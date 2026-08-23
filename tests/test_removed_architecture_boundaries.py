"""Static boundaries for the Electron plus headless-Python architecture."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

LEGACY_RUNTIME_PATHS = (
    "presentation",
    "application/bootstrap.py",
    "shared/async_runtime.py",
    "domain/llm/llm_executor.py",
    "frontend/conversation-panel",
    "frontend/simulation-panel",
    "frontend/workspace-panel",
    "frontend/menu-bar",
    "resources/conversation",
    "resources/simulation",
    "resources/workspace",
    "resources/menu",
    "resources/editor",
    "resources/icons",
    "resources/styles",
    "resources/i18n",
    "resources/katex",
    "resources/prompts",
    "resources/theme.py",
    "resources/resources.qrc",
    "main.py",
    "CircuitDesignAI.spec",
)

PRESERVED_RUNTIME_PATHS = (
    "resources/models",
    "resources/resource_loader.py",
    "resources/__init__.py",
    "vendor/ngspice",
    "frontend/desktop",
    "desktop_backend",
    "application/runtime.py",
    "desktop_backend.spec",
)

REMOVED_PROTOTYPES = (
    "domain/llm/external_service_manager.py",
    "domain/simulation/data/resolution_pyramid.py",
    "domain/simulation/executor/circuit_analyzer.py",
    "domain/simulation/executor/executor_registry.py",
    "domain/simulation/executor/python_executor.py",
    "domain/simulation/executor/simulation_executor.py",
    "domain/simulation/measure/measure_injector.py",
    "domain/simulation/models/simulation_config.py",
    "domain/simulation/service/parameter_extractor.py",
    "domain/simulation/service/bundled_spice_library_injector.py",
    "domain/simulation/service/simulation_result_watcher.py",
    "domain/simulation/service/tuning_service.py",
    "domain/simulation/spice/analysis_directive_authority.py",
    "shared/worker_manager.py",
    "shared/worker_types.py",
    "shared/async_task_registry.py",
    "infrastructure/persistence/async_file_ops.py",
    "shared/error_handler.py",
    "shared/error_types.py",
    "shared/i18n_manager.py",
    "infrastructure/utils/markdown_renderer.py",
)

REMOVED_PACKAGES = (
    "domain/search",
    "domain/dependency",
    "domain/design",
    "shared/tracing",
)

CORE_PYTHON_ROOTS = (
    "application",
    "domain",
    "infrastructure",
    "shared",
    "desktop_backend",
    "resources",
)

FORBIDDEN_PRODUCTION_TEXT = (
    "PyQt",
    "PySide",
    "qasync",
    "QApplication",
    "QObject",
    "pyqtSignal",
    "application.bootstrap",
    "shared.async_runtime",
    "domain.llm.llm_executor",
)


def _python_sources():
    for relative_root in CORE_PYTHON_ROOTS:
        yield from sorted((PROJECT_ROOT / relative_root).rglob("*.py"))


def _import_targets(source: str) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def test_legacy_desktop_runtime_paths_are_physically_absent():
    for relative_path in LEGACY_RUNTIME_PATHS:
        assert not (PROJECT_ROOT / relative_path).exists(), relative_path


def test_required_modern_runtime_paths_are_preserved():
    for relative_path in PRESERVED_RUNTIME_PATHS:
        assert (PROJECT_ROOT / relative_path).exists(), relative_path


def test_removed_prototypes_have_no_python_implementation():
    for relative_path in REMOVED_PROTOTYPES:
        assert not (PROJECT_ROOT / relative_path).exists(), relative_path

    for relative_path in REMOVED_PACKAGES:
        package_path = PROJECT_ROOT / relative_path
        assert not list(package_path.rglob("*.py")), relative_path


def test_core_python_has_no_qt_or_retired_runtime_imports():
    for path in _python_sources():
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        imports = _import_targets(source)

        for target in imports:
            assert target != "presentation" and not target.startswith("presentation."), (
                relative_path,
                target,
            )
            assert target not in {"PyQt5", "PyQt6", "PySide2", "PySide6", "qasync"}, (
                relative_path,
                target,
            )
            assert not target.startswith(("PyQt5.", "PyQt6.", "PySide2.", "PySide6.")), (
                relative_path,
                target,
            )

        for retired_text in FORBIDDEN_PRODUCTION_TEXT:
            assert retired_text not in source, (relative_path, retired_text)


def test_removed_services_and_ui_events_are_not_exported():
    service_names = (PROJECT_ROOT / "shared/service_names.py").read_text(encoding="utf-8")
    event_types = (PROJECT_ROOT / "shared/event_types.py").read_text(encoding="utf-8")

    for symbol in (
        "SVC_ERROR_HANDLER",
        "SVC_I18N_MANAGER",
        "SVC_LLM_EXECUTOR",
        "SVC_WORKER_MANAGER",
        "SVC_ASYNC_TASK_REGISTRY",
        "SVC_ASYNC_FILE_OPS",
        "SVC_UNIFIED_SEARCH_SERVICE",
        "SVC_IN_FILE_SEARCH_SERVICE",
        "SVC_UI_STATE",
        "SVC_DESIGN_WORKFLOW",
        "SVC_TRACING_STORE",
        "SVC_TRACING_LOGGER",
        "SVC_EXTERNAL_SERVICE_MANAGER",
        "SVC_DEPENDENCY_HEALTH_SERVICE",
    ):
        assert symbol not in service_names

    for symbol in (
        "EVENT_INIT_PHASE_COMPLETE",
        "EVENT_INIT_COMPLETE",
        "EVENT_UI_SEND_MESSAGE",
        "EVENT_UI_ATTACH_FILES_TO_CONVERSATION",
        "EVENT_UI_ACTIVATE_CONVERSATION_TAB",
        "EVENT_PANEL_VISIBILITY_CHANGED",
        "EVENT_TAB_CHANGED",
        "EVENT_MODEL_CHANGED",
        "EVENT_EMBEDDING_PROVIDER_CHANGED",
        "EVENT_EMBEDDING_MODEL_READY",
        "EVENT_WEB_SEARCH_STARTED",
        "EVENT_WEB_SEARCH_COMPLETE",
        "EVENT_WEB_SEARCH_ERROR",
        "EVENT_ERROR_OCCURRED",
        "EVENT_ERROR_RECOVERED",
        "EVENT_FILE_LOCKED",
        "EVENT_FILE_UNLOCKED",
        "EVENT_FILE_CONFLICT_DETECTED",
        "EVENT_FILE_SEARCH_INDEX_UPDATED",
        "EVENT_SYMBOL_LOCATED",
        "EVENT_REFERENCES_FOUND",
        "EVENT_LANGUAGE_CHANGED",
        "EVENT_ITERATION_AWAITING_CONFIRMATION",
        "EVENT_ITERATION_USER_CONFIRMED",
        "EVENT_ITERATION_USER_STOPPED",
        "EVENT_ACTIVE_FILE_CHANGED",
    ):
        assert symbol not in event_types


def test_resource_loader_has_no_desktop_visual_authority():
    source = (PROJECT_ROOT / "resources/resource_loader.py").read_text(encoding="utf-8")
    for symbol in ("QIcon", "QApplication", "load_stylesheet", "get_stylesheet", "main.qss"):
        assert symbol not in source


def test_removed_spice_compatibility_layers_are_not_reintroduced():
    runtime_compatibility = (
        PROJECT_ROOT / "domain/simulation/spice/runtime_compatibility.py"
    ).read_text(encoding="utf-8")
    source_closure = (
        PROJECT_ROOT / "domain/simulation/spice/source_closure.py"
    ).read_text(encoding="utf-8")

    for symbol in (
        "NetlistRuntimeCompatibilityNormalizer",
        "RuntimeNormalizedNetlist",
        "rewrite_library_directives_for_runtime",
    ):
        assert symbol not in runtime_compatibility
    for symbol in ("compute_spice_source_closure", "SpiceSourceClosureIdentity"):
        assert symbol not in source_closure


def test_removed_measurement_convenience_api_is_not_reintroduced():
    measure_metadata = (
        PROJECT_ROOT / "domain/simulation/measure/measure_metadata.py"
    ).read_text(encoding="utf-8")
    simulation_result = (
        PROJECT_ROOT / "domain/simulation/models/simulation_result.py"
    ).read_text(encoding="utf-8")

    for definition in (
        "def extract_numeric_metric_values",
        "def resolve_result_metric_values",
        "def get_result_metric_value",
    ):
        assert definition not in measure_metadata
    for definition in ("def metric_values", "def get_metric"):
        assert definition not in simulation_result


def test_regenerable_evaluation_and_transcription_outputs_are_ignored():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "evaluation/reports/" in gitignore
    assert "TestCircuit/transcribed_circuits/" in gitignore
