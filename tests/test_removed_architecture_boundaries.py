"""Static boundaries for architecture prototypes removed from the runtime."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REMOVED_MODULES = (
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
    "presentation/panels/bottom_panel.py",
    "presentation/panels/simulation/analysis_info_panel.py",
    "presentation/panels/simulation/chart_signal_tree.py",
    "presentation/panels/simulation/tuning_panel.py",
)

REMOVED_PACKAGES = (
    "domain/search",
    "domain/dependency",
    "domain/design",
    "shared/tracing",
)


def test_removed_architecture_modules_have_no_python_implementation():
    for relative_path in REMOVED_MODULES:
        assert not (PROJECT_ROOT / relative_path).exists(), relative_path

    for relative_path in REMOVED_PACKAGES:
        package_path = PROJECT_ROOT / relative_path
        assert not list(package_path.rglob("*.py")), relative_path


def test_removed_services_and_events_are_not_exported():
    service_names = (PROJECT_ROOT / "shared/service_names.py").read_text(
        encoding="utf-8"
    )
    event_types = (PROJECT_ROOT / "shared/event_types.py").read_text(
        encoding="utf-8"
    )

    for symbol in (
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
        "SVC_CPU_TASK_EXECUTOR",
        "SVC_INFO_CARD_PERSISTENCE",
        "SVC_TOOL_EXECUTOR",
        "SVC_SIMULATION_SERVICE",
        "SVC_WAVEFORM_DATA_SERVICE",
    ):
        assert symbol not in service_names

    for symbol in (
        "EVENT_WORKER_STARTED",
        "EVENT_WORKER_PROGRESS",
        "EVENT_WORKER_COMPLETE",
        "EVENT_WORKER_ERROR",
        "EVENT_TASK_STARTED",
        "EVENT_TASK_COMPLETED",
        "EVENT_TASK_FAILED",
        "EVENT_TASK_CANCELLED",
        "EVENT_SIM_RESULT_FILE_CREATED",
        "EVENT_ASYNC_SLOT_ERROR",
        "EVENT_DEPENDENCY_SCAN_STARTED",
        "EVENT_DEPENDENCY_SCAN_COMPLETE",
        "EVENT_DEPENDENCY_REPORT_UPDATED",
        "EVENT_DEPENDENCY_RESOLUTION_REQUESTED",
        "EVENT_DEPENDENCY_RESOLUTION_COMPLETE",
        "EVENT_SERVICE_CIRCUIT_OPEN",
        "EVENT_SERVICE_CIRCUIT_CLOSE",
        "EVENT_INFO_CARD_ADDED",
        "EVENT_INFO_CARD_UPDATED",
        "EVENT_INFO_CARD_REMOVED",
        "EVENT_INFO_CARD_PINNED",
        "EVENT_INFO_CARDS_LOADED",
        "EVENT_INFO_PANEL_CATEGORY_CHANGED",
        "EVENT_INFO_PANEL_CLEARED",
        "EVENT_STATE_ITERATION_UPDATED",
        "EVENT_DESIGN_COMPLETED",
        "EVENT_DESIGN_ACCEPTED",
        "EVENT_DESIGN_STOPPED",
        "EVENT_REQUEST_RESIMULATION",
    ):
        assert symbol not in event_types


def test_bootstrap_and_packaging_do_not_reference_removed_modules():
    bootstrap = (PROJECT_ROOT / "application/bootstrap.py").read_text(
        encoding="utf-8"
    )
    spec_path = PROJECT_ROOT / "CircuitDesignAI.spec"
    spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""

    for module_name in (
        "domain.llm.external_service_manager",
        "domain.search",
        "domain.dependency",
        "domain.design",
        "domain.simulation.service.simulation_result_watcher",
        "domain.simulation.data.resolution_pyramid",
        "domain.simulation.executor.circuit_analyzer",
        "domain.simulation.executor.executor_registry",
        "domain.simulation.executor.python_executor",
        "domain.simulation.executor.simulation_executor",
        "domain.simulation.service.parameter_extractor",
        "domain.simulation.service.bundled_spice_library_injector",
        "domain.simulation.service.tuning_service",
        "infrastructure.persistence.async_file_ops",
        "presentation.panels.bottom_panel",
        "presentation.panels.simulation.analysis_info_panel",
        "presentation.panels.simulation.chart_signal_tree",
        "presentation.panels.simulation.tuning_panel",
        "shared.async_task_registry",
        "shared.tracing",
        "shared.worker_manager",
    ):
        assert module_name not in bootstrap
        assert module_name not in spec


def test_removed_thread_bridge_is_not_exported():
    async_runtime = (PROJECT_ROOT / "shared/async_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "run_coroutine_threadsafe" not in async_runtime


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
    for symbol in (
        "compute_spice_source_closure",
        "SpiceSourceClosureIdentity",
    ):
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


def test_qt_tests_use_one_nonempty_process_argv_fixture():
    empty_application_argv = "QApplication(" + "[]" + ")"
    for test_path in (PROJECT_ROOT / "tests").rglob("*.py"):
        assert empty_application_argv not in test_path.read_text(encoding="utf-8"), test_path

    shared_fixture = (PROJECT_ROOT / "tests/conftest.py").read_text(
        encoding="utf-8"
    )
    assert 'QApplication(["circuit-design-ai-tests"])' in shared_fixture
