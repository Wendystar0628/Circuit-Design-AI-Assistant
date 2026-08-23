from __future__ import annotations

from types import SimpleNamespace
import threading
import time
import logging

import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from domain.simulation.models.simulation_result import SimulationResult
from presentation.panels.simulation.simulation_tab import SimulationTab
from presentation.panels.simulation import simulation_tab as simulation_tab_module
from presentation.panels.simulation.simulation_asc_conversion_panel import (
    SimulationAscConversionPanel,
)
from domain.simulation.spice.ltspice_asc_to_cir_transcriber import (
    AscBatchConversionExecution,
)
from domain.simulation.spice.source_closure import collect_spice_source_closure
from presentation.panels.simulation.simulation_view_model import (
    SimulationStatus,
    SimulationViewModel,
)
from presentation.panels.simulation.simulation_web_bridge import SimulationWebBridge
from presentation.panels.simulation import spice_schematic_document as schematic_document_module
from presentation.panels.simulation.spice_schematic_document import SpiceSchematicDocument
from shared.file_change import FileChange
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_METRIC_TARGET_SERVICE, SVC_SIMULATION_JOB_MANAGER


def test_bridge_rejects_non_finite_and_inverted_viewports(qapp):
    bridge = SimulationWebBridge()
    received = []
    bridge.chart_viewport_changed.connect(received.append)

    bridge.setChartViewport({
        "xMin": float("nan"),
        "xMax": 1.0,
        "leftYMin": 0.0,
        "leftYMax": 1.0,
    })
    bridge.setChartViewport({
        "xMin": 2.0,
        "xMax": 1.0,
        "leftYMin": 0.0,
        "leftYMax": 1.0,
    })

    assert received == []

    bridge.setChartViewport({
        "xMin": 0.0,
        "xMax": 1.0,
        "leftYMin": -1.0,
        "leftYMax": 1.0,
    })
    assert received == [{
        "x_min": 0.0,
        "x_max": 1.0,
        "left_y_min": -1.0,
        "left_y_max": 1.0,
        "right_y_min": None,
        "right_y_max": None,
    }]


def test_bridge_requires_exact_identity_for_stateful_actions(qapp):
    bridge = SimulationWebBridge()
    loaded = []
    cancelled = []
    exported = []
    attached = []
    metric_target_updates = []
    bridge.load_result_by_path_requested.connect(loaded.append)
    bridge.cancel_simulation_requested.connect(cancelled.append)
    bridge.export_requested.connect(exported.append)
    bridge.add_to_conversation_requested.connect(attached.append)
    bridge.update_metric_targets_requested.connect(metric_target_updates.append)

    # Missing or partial identities fail closed.
    bridge.loadResultByPath({"resultPath": "simulation_results/amp/run/result.json"})
    bridge.cancelSimulation({"projectRoot": "/new"})
    bridge.requestExport({"projectRoot": "/new", "resultPath": ""})
    bridge.addToConversation({
        "projectRoot": "/new",
        "resultPath": "simulation_results/amp/run/result.json",
        "target": "unknown",
    })
    bridge.updateMetricTargets({
        "resultPath": "simulation_results/amp/run/result.json",
        "sourceFilePath": "circuits/amp.cir",
        "targets": {"gain": "> 10"},
    })
    assert loaded == cancelled == exported == attached == metric_target_updates == []

    bridge.loadResultByPath({
        "projectRoot": "/old",
        "resultPath": "simulation_results/amp/run/result.json",
    })
    bridge.cancelSimulation({"projectRoot": "/new", "jobId": "job-new"})
    bridge.requestExport({
        "projectRoot": "/new",
        "resultPath": "simulation_results/amp/run/result.json",
    })
    bridge.addToConversation({
        "projectRoot": "/new",
        "resultPath": "simulation_results/amp/run/result.json",
        "target": "metrics",
    })
    bridge.updateMetricTargets({
        "projectRoot": "/new",
        "resultPath": "simulation_results/amp/run/result.json",
        "sourceFilePath": "circuits/amp.cir",
        "targets": {"gain": " > 10 dB "},
    })

    assert loaded == [{
        "project_root": "/old",
        "result_path": "simulation_results/amp/run/result.json",
    }]
    assert cancelled == [{"project_root": "/new", "job_id": "job-new"}]
    assert exported == [{
        "project_root": "/new",
        "result_path": "simulation_results/amp/run/result.json",
    }]
    assert attached == [{
        "project_root": "/new",
        "result_path": "simulation_results/amp/run/result.json",
        "target": "metrics",
    }]
    assert metric_target_updates == [{
        "project_root": "/new",
        "result_path": "simulation_results/amp/run/result.json",
        "source_file_path": "circuits/amp.cir",
        "targets": {"gain": "> 10 dB"},
    }]


def test_old_project_metric_target_action_cannot_write_same_relative_source():
    writes = []
    errors = []

    class _MetricTargetService:
        def set_targets_for_file(self, source_file_path, targets):
            writes.append((source_file_path, targets))

    fake_tab = SimpleNamespace(
        _project_root="/new-project",
        _displayed_result_path="simulation_results/amp/run/result.json",
        _view_model=SimpleNamespace(
            current_result=SimpleNamespace(file_path="circuits/amp.cir"),
            metrics_list=[SimpleNamespace(name="gain")],
            refresh_metric_targets=lambda: None,
        ),
        _backend_runtime=SimpleNamespace(
            export_panel=SimpleNamespace(set_metrics=lambda _metrics: None),
        ),
        _set_metric_target_error=errors.append,
        _update_frontend_payloads=lambda: None,
        _panel_error_message="",
        _logger=logging.getLogger("test.stale-metric-target-action"),
    )
    fake_tab._request_targets_current_project = (
        lambda payload: SimulationTab._request_targets_current_project(fake_tab, payload)
    )
    fake_tab._request_targets_displayed_result = (
        lambda payload: SimulationTab._request_targets_displayed_result(fake_tab, payload)
    )

    service = _MetricTargetService()
    ServiceLocator.register(SVC_METRIC_TARGET_SERVICE, service)
    try:
        stale_payload = {
            "project_root": "/old-project",
            "result_path": "simulation_results/amp/run/result.json",
            "source_file_path": "circuits/amp.cir",
            "targets": {"gain": "> 10 dB"},
        }
        SimulationTab._on_update_metric_targets_requested(fake_tab, stale_payload)
        assert writes == []

        current_payload = {**stale_payload, "project_root": "/new-project"}
        SimulationTab._on_update_metric_targets_requested(fake_tab, current_payload)
    finally:
        ServiceLocator.unregister(SVC_METRIC_TARGET_SERVICE)

    assert len(errors) == 1
    assert writes == [("circuits/amp.cir", {"gain": "> 10 dB"})]


def test_old_project_result_card_cannot_resolve_same_relative_path_in_new_project():
    loaded_paths = []
    fake_tab = SimpleNamespace(
        _project_root="/new-project",
        _logger=logging.getLogger("test.stale-result-card"),
        load_result_by_path=loaded_paths.append,
    )
    fake_tab._request_targets_current_project = (
        lambda payload: SimulationTab._request_targets_current_project(fake_tab, payload)
    )

    shared_relative_path = "simulation_results/amp/run/result.json"
    SimulationTab._on_load_result_by_path_requested(fake_tab, {
        "project_root": "/old-project",
        "result_path": shared_relative_path,
    })
    assert loaded_paths == []

    SimulationTab._on_load_result_by_path_requested(fake_tab, {
        "project_root": "/new-project",
        "result_path": shared_relative_path,
    })
    assert loaded_paths == [shared_relative_path]


def test_stale_snapshot_cannot_cancel_export_or_attach_current_result():
    export_calls = []
    attachment_calls = []
    cancel_calls = []
    fake_tab = SimpleNamespace(
        _project_root="/new-project",
        _displayed_job_id="job-new",
        _displayed_result_path="simulation_results/amp/new/result.json",
        _view_model=SimpleNamespace(current_result=object()),
        _backend_runtime=SimpleNamespace(
            export_panel=SimpleNamespace(
                export_selected=lambda: export_calls.append(True),
            ),
        ),
        _logger=logging.getLogger("test.stale-result-actions"),
        _on_add_metrics_to_conversation_clicked=lambda: attachment_calls.append(True),
    )
    fake_tab._request_targets_current_project = (
        lambda payload: SimulationTab._request_targets_current_project(fake_tab, payload)
    )
    fake_tab._request_targets_displayed_result = (
        lambda payload: SimulationTab._request_targets_displayed_result(fake_tab, payload)
    )

    SimulationTab._on_export_requested(fake_tab, {
        "project_root": "/old-project",
        "result_path": "simulation_results/amp/old/result.json",
    })
    SimulationTab._on_bridge_add_to_conversation_requested(fake_tab, {
        "project_root": "/new-project",
        "result_path": "simulation_results/amp/old/result.json",
        "target": "metrics",
    })

    class FakeManager:
        def request_cancel(self, job_id):
            cancel_calls.append(job_id)
            return True

    ServiceLocator.register(SVC_SIMULATION_JOB_MANAGER, FakeManager())
    try:
        SimulationTab._on_cancel_simulation_requested(fake_tab, {
            "project_root": "/new-project",
            "job_id": "job-old",
        })
    finally:
        ServiceLocator.unregister(SVC_SIMULATION_JOB_MANAGER)

    assert export_calls == []
    assert attachment_calls == []
    assert cancel_calls == []


def test_result_card_cannot_orphan_an_active_ui_job(monkeypatch):
    fake_tab = SimpleNamespace(
        _project_root="/project",
        _displayed_job_id="job-live",
        _can_cancel_current_job=lambda: True,
        _logger=logging.getLogger("test.live-job-result-card"),
    )
    monkeypatch.setattr(
        simulation_tab_module.simulation_result_repository,
        "load",
        lambda *_args: pytest.fail("active job must reject result load before disk access"),
    )

    loaded = SimulationTab.load_result_by_path(
        fake_tab,
        "simulation_results/amp/old/result.json",
    )

    assert loaded is False
    assert fake_tab._displayed_job_id == "job-live"


def test_result_card_waits_for_terminal_lifecycle_event_before_loading(monkeypatch):
    """A terminal manager state cannot clear UI ownership before COMPLETE."""
    fake_tab = SimpleNamespace(
        _project_root="/project",
        _displayed_job_id="job-terminal-before-event",
        _can_cancel_current_job=lambda: False,
        _logger=logging.getLogger("test.terminal-before-event-result-card"),
    )
    monkeypatch.setattr(
        simulation_tab_module.simulation_result_repository,
        "load",
        lambda *_args: pytest.fail(
            "the lifecycle event must release UI ownership before history can load"
        ),
    )

    loaded = SimulationTab.load_result_by_path(
        fake_tab,
        "simulation_results/amp/old/result.json",
    )

    assert loaded is False
    assert fake_tab._displayed_job_id == "job-terminal-before-event"


def test_failed_result_without_error_object_never_reuses_previous_error(qapp):
    view_model = SimulationViewModel()
    view_model._error_message = "stale failure"
    result = SimulationResult(
        executor="spice",
        file_path="/project/amp.cir",
        analysis_type="tran",
        success=False,
    )

    view_model.load_result(result)

    assert view_model.simulation_status is SimulationStatus.ERROR
    assert view_model.error_message == "Simulation result is incomplete or failed"


def test_unavailable_persisted_circuit_source_is_explicit_and_read_only(qapp):
    document = SpiceSchematicDocument()

    document.load_unavailable_source(
        "circuits/missing.cir",
        "源电路文件在当前项目中不可用，历史结果原理图不可用。",
    )

    state = document.get_authoritative_schematic_document()
    assert state["file_path"] == "circuits/missing.cir"
    assert state["components"] == []
    assert state["parse_errors"]
    assert "不可用" in state["parse_errors"][0]["message"]


def test_historical_schematic_requires_exact_source_digest(qapp, tmp_path):
    source_path = tmp_path / "amp.cir"
    source_path.write_bytes(b"title\nR1 out 0 1k\n.end\n")
    source_digest = collect_spice_source_closure(source_path).digest
    document = SpiceSchematicDocument()

    assert document.load_from_result_file(str(source_path), source_digest) is True
    assert document.get_authoritative_schematic_document()["has_schematic"] is True

    source_path.write_bytes(b"title\nR1 out 0 2k\n.end\n")
    changed_document = SpiceSchematicDocument()
    assert changed_document.load_from_result_file(str(source_path), source_digest) is False
    changed_state = changed_document.get_authoritative_schematic_document()
    assert changed_state["has_schematic"] is False
    assert "源电路已改变" in changed_state["parse_errors"][0]["message"]


def test_history_result_reload_rechecks_changed_source_at_the_same_path(qapp, tmp_path):
    source_path = tmp_path / "amp.cir"
    source_path.write_bytes(b"title\nR1 out 0 1k\n.end\n")
    source_digest = collect_spice_source_closure(source_path).digest
    document = SpiceSchematicDocument()
    fake_tab = SimpleNamespace(
        _project_root=str(tmp_path),
        _backend_runtime=SimpleNamespace(spice_schematic_document=document),
        _get_text=lambda _key, default: default,
    )
    historical_result = SimpleNamespace(
        file_path="amp.cir",
        source_digest=source_digest,
    )

    assert SimulationTab._load_result_schematic(fake_tab, historical_result) is True
    assert document.get_authoritative_schematic_document()["has_schematic"] is True

    source_path.write_bytes(b"title\nR1 out 0 2k\n.end\n")
    assert SimulationTab._load_result_schematic(fake_tab, historical_result) is False
    changed_state = document.get_authoritative_schematic_document()
    assert changed_state["has_schematic"] is False
    assert "源电路已改变" in changed_state["parse_errors"][0]["message"]


def test_historical_schematic_rejects_recursive_include_change(
    qapp,
    tmp_path,
):
    source_path = tmp_path / "amp.cir"
    include_path = tmp_path / "device.lib"
    nested_path = tmp_path / "models.lib"
    source_path.write_bytes(
        b"title\n.include device.lib\nR1 out 0 1k\n.end\n"
    )
    include_path.write_bytes(b".include models.lib\n")
    nested_path.write_bytes(b".model DTEST D(Is=1e-12)\n")
    main_bytes = source_path.read_bytes()
    source_digest = collect_spice_source_closure(source_path).digest
    document = SpiceSchematicDocument()

    assert document.load_from_result_file(str(source_path), source_digest) is True
    assert document._watched_file_keys == {
        document._normalize_watch_key(str(source_path)),
        document._normalize_watch_key(str(include_path)),
        document._normalize_watch_key(str(nested_path)),
    }

    document._file_manager = SimpleNamespace(
        get_work_dir=lambda: tmp_path,
        project_generation=7,
    )
    nested_path.write_bytes(b".model DTEST D(Is=2e-12)\n")
    assert source_path.read_bytes() == main_bytes
    document._on_file_changed(
        FileChange(
            operation="update",
            path=str(nested_path),
            dest_path="",
            is_directory=False,
            origin="test",
            project_root=str(tmp_path),
            generation=7,
            revision="nested-model-update",
        )
    )
    assert document._refresh_timer.isActive() is True
    document._refresh_timer.stop()
    document._flush_debounced_refresh()

    changed_state = document.get_authoritative_schematic_document()
    assert changed_state["has_schematic"] is False
    assert "依赖已改变" in changed_state["parse_errors"][0]["message"]


def test_historical_schematic_keeps_recursive_watch_after_dependency_disappears(
    qapp,
    tmp_path,
):
    source_path = tmp_path / "amp.cir"
    include_path = tmp_path / "device.lib"
    nested_path = tmp_path / "models.lib"
    source_path.write_bytes(
        b"title\n.include device.lib\nR1 out 0 1k\n.end\n"
    )
    include_path.write_bytes(b".include models.lib\n")
    nested_path.write_bytes(b".model DTEST D(Is=1e-12)\n")
    source_digest = collect_spice_source_closure(source_path).digest
    document = SpiceSchematicDocument()
    assert document.load_from_result_file(str(source_path), source_digest) is True
    nested_watch_key = document._normalize_watch_key(str(nested_path))

    nested_path.unlink()
    assert document._refresh_document(reason="dependency_deleted") is False

    unavailable = document.get_authoritative_schematic_document()
    assert unavailable["has_schematic"] is False
    assert "依赖不可用" in unavailable["parse_errors"][0]["message"]
    assert nested_watch_key in document._watched_file_keys


def test_historical_schematic_uses_one_atomic_closure_snapshot(
    qapp,
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "amp.cir"
    include_path = tmp_path / "device.lib"
    source_path.write_bytes(
        b"title\n.include device.lib\nR1 out 0 1k\n.end\n"
    )
    dependency_before = b".model DTEST D(Is=1e-12)\n"
    dependency_after = b".model DTEST D(Is=2e-12)\n"
    include_path.write_bytes(dependency_after)
    captured_after = collect_spice_source_closure(source_path)
    include_path.write_bytes(dependency_before)

    def collect_while_dependency_changes(_source_path):
        # This is the old two-read race: the dependency changes after an
        # earlier consumer could have read it but before provenance returns.
        # The UI must consume captured_after for both digest and presentation,
        # and must not read the now-live file a second time.
        include_path.write_bytes(dependency_after)
        return captured_after

    monkeypatch.setattr(
        schematic_document_module,
        "collect_spice_source_closure",
        collect_while_dependency_changes,
    )
    document = SpiceSchematicDocument()

    assert document.load_from_result_file(
        str(source_path),
        captured_after.digest,
    ) is True
    dependency_view = next(
        view for view in captured_after.active_views if not view.is_main_deck
    )
    captured_active_text = "\n".join(
        f"{line.line_number}:{line.text}"
        for line in dependency_view.lines
    )
    expected_edit_token = (
        document._make_edit_revision_dependency_snapshot_value(
            captured_active_text
        )
    )
    assert document._latest_dependency_snapshots == {
        document._normalize_watch_key(str(include_path)): expected_edit_token,
    }
    assert include_path.read_bytes() == dependency_after


def test_schematic_watches_physical_lib_closure_but_snapshots_active_view_only(
    qapp,
    tmp_path,
):
    source_path = tmp_path / "amp.cir"
    library_path = tmp_path / "process.lib"
    inactive_include = tmp_path / "inactive.inc"
    source_path.write_text(
        "title\n"
        ".lib process.lib TT\n"
        "M1 drain gate 0 0 PROCESS_DEVICE\n"
        ".op\n"
        ".end\n",
        encoding="utf-8",
    )
    library_path.write_text(
        ".lib TT\n"
        ".model PROCESS_DEVICE NMOS(level=1)\n"
        ".endl TT\n"
        ".lib FF\n"
        ".include inactive.inc\n"
        ".model PROCESS_DEVICE PMOS(level=1)\n"
        ".endl FF\n",
        encoding="utf-8",
    )
    inactive_include.write_text(
        ".model PHYSICAL_ONLY PNP(Is=3e-12)\n",
        encoding="utf-8",
    )
    closure = collect_spice_source_closure(source_path)
    document = SpiceSchematicDocument()

    assert document.load_from_result_file(
        str(source_path),
        closure.digest,
    ) is True
    assert document._watched_file_keys == {
        document._normalize_watch_key(path)
        for path in closure.source_keys
    }
    active_snapshot_keys = set(document._latest_dependency_snapshots)
    assert active_snapshot_keys == {
        f"{document._normalize_watch_key(str(library_path))}#lib:tt"
    }
    assert all(
        document._normalize_watch_key(str(inactive_include)) not in key
        for key in active_snapshot_keys
    )
    rendered = document.get_authoritative_schematic_document()
    main_mos = next(
        component
        for component in rendered["components"]
        if component["instance_name"] == "M1"
    )
    assert main_mos["symbol_variant"] == "nmos"
    assert not rendered["parse_errors"]

    source_path.write_text(
        "title\n"
        ".lib process.lib FF\n"
        "M1 drain gate 0 0 PROCESS_DEVICE\n"
        ".op\n"
        ".end\n",
        encoding="utf-8",
    )
    ff_closure = collect_spice_source_closure(source_path)
    ff_document = SpiceSchematicDocument()
    assert ff_document.load_from_result_file(
        str(source_path),
        ff_closure.digest,
    ) is True
    ff_rendered = ff_document.get_authoritative_schematic_document()
    ff_mos = next(
        component
        for component in ff_rendered["components"]
        if component["instance_name"] == "M1"
    )
    assert ff_mos["symbol_variant"] == "pmos"
    assert not ff_rendered["parse_errors"]


def test_active_dependency_subcircuits_drive_schematic_but_remain_readonly(
    qapp,
    tmp_path,
):
    source_path = tmp_path / "amp.cir"
    dependency_path = tmp_path / "active.lib"
    source_path.write_text(
        "title\n"
        ".include active.lib\n"
        "XAMP plus minus out vcc vee ACTIVE_OPAMP\n"
        "XFILTER in out ACTIVE_FILTER\n"
        ".op\n"
        ".end\n",
        encoding="utf-8",
    )
    dependency_path.write_text(
        ".subckt ACTIVE_OPAMP plus minus out vcc vee\n"
        "ECORE out 0 plus minus 1e6\n"
        ".ends ACTIVE_OPAMP\n"
        ".subckt ACTIVE_FILTER in out\n"
        "RDEPENDENCY in out 10k\n"
        ".ends ACTIVE_FILTER\n",
        encoding="utf-8",
    )
    source_before = source_path.read_bytes()
    dependency_before = dependency_path.read_bytes()
    closure = collect_spice_source_closure(source_path)
    document = SpiceSchematicDocument()

    assert document.load_from_result_file(str(source_path), closure.digest) is True
    rendered = document.get_authoritative_schematic_document()
    opamp = next(
        component
        for component in rendered["components"]
        if component["instance_name"] == "XAMP"
    )
    dependency_resistor = next(
        component
        for component in rendered["components"]
        if component["instance_name"] == "RDEPENDENCY"
    )
    assert opamp["symbol_kind"] == "opamp"
    assert opamp["primitive_source"] == "explicit_subckt_ports"
    assert dependency_resistor["source_file"] == str(dependency_path)
    assert dependency_resistor["editable_fields"] == [
        {
            "field_key": "value",
            "label": "数值",
            "raw_text": "10k",
            "display_text": "10k",
            "editable": False,
            "readonly_reason": "依赖源文件中的字段不能从主电路历史结果直接写回",
            "value_kind": "literal",
        }
    ]

    document.request_value_update({
        "document_id": rendered["document_id"],
        "revision": rendered["revision"],
        "request_id": "dependency-write",
        "component_id": dependency_resistor["id"],
        "field_key": "value",
        "new_text": "22k",
    })

    write_result = document.get_authoritative_schematic_write_result()
    assert write_result["success"] is False
    assert "依赖源文件" in write_result["error_message"]
    assert source_path.read_bytes() == source_before
    assert dependency_path.read_bytes() == dependency_before


def test_successful_schematic_write_immediately_invalidates_historical_view(
    qapp,
    tmp_path,
):
    source_path = tmp_path / "amp.cir"
    source_path.write_bytes(b"title\nR1 out 0 1k\n.end\n")
    source_digest = collect_spice_source_closure(source_path).digest
    document = SpiceSchematicDocument()
    assert document.load_from_result_file(str(source_path), source_digest) is True
    before = document.get_authoritative_schematic_document()
    component = before["components"][0]

    document.request_value_update({
        "document_id": before["document_id"],
        "revision": before["revision"],
        "request_id": "request-write-1",
        "component_id": component["id"],
        "field_key": "value",
        "new_text": "2k",
    })

    assert b"2k" in source_path.read_bytes()
    assert document.get_authoritative_schematic_write_result()["success"] is True
    invalidated = document.get_authoritative_schematic_document()
    assert invalidated["has_schematic"] is False
    assert "源电路已改变" in invalidated["parse_errors"][0]["message"]
    assert document._latest_spice_document is None


def test_new_run_clears_previous_result_identity(qapp):
    view_model = SimulationViewModel()
    view_model._current_result = object()
    view_model._metrics_list = [object()]
    view_model._error_message = "old"

    view_model.mark_running()

    assert view_model.current_result is None
    assert view_model.metrics_list == []
    assert view_model.error_message == ""
    assert view_model.simulation_status is SimulationStatus.RUNNING


def test_project_restore_never_overwrites_a_live_ui_job():
    loaded_paths = []
    fake_tab = SimpleNamespace(
        _project_root="/project",
        _displayed_job_id="job_live",
        _displayed_result_path=None,
        _view_model=SimpleNamespace(current_result=None),
        _circuit_result_index_cache=[
            SimpleNamespace(results=[SimpleNamespace(result_path="simulation_results/amp/run/result.json")])
        ],
        load_result_by_path=loaded_paths.append,
    )

    SimulationTab._restore_project_result_after_project_opened(fake_tab)

    assert loaded_paths == []


def test_asc_conversion_runs_off_the_ui_thread(qapp, tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class FakeTranscriber:
        def convert_files(self, _file_paths, output_root):
            entered.set()
            release.wait(timeout=2)
            finished.set()
            return AscBatchConversionExecution(
                output_root=output_root,
                converted_files=(),
                failed_files=(),
            )

    monkeypatch.setattr(
        "presentation.panels.simulation.simulation_asc_conversion_panel.LtspiceAscToCirTranscriber",
        FakeTranscriber,
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(tmp_path / "demo.asc")], ""),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)

    panel = SimulationAscConversionPanel()
    panel.set_project_root(str(tmp_path))

    assert panel.choose_files_and_convert() is True
    assert entered.wait(timeout=1)
    assert panel.get_web_snapshot()["is_running"] is True

    release.set()
    assert finished.wait(timeout=1)
    deadline = time.monotonic() + 1.0
    while panel.get_web_snapshot()["is_running"] and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert panel.get_web_snapshot()["is_running"] is False


def test_asc_conversion_remains_single_flight_across_project_switches(
    qapp,
    tmp_path,
    monkeypatch,
):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    dialog_calls = []
    completion_dialogs = []

    class FakeTranscriber:
        def convert_files(self, _file_paths, output_root):
            entered.set()
            release.wait(timeout=2)
            finished.set()
            return AscBatchConversionExecution(
                output_root=output_root,
                converted_files=(),
                failed_files=(),
            )

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    monkeypatch.setattr(
        "presentation.panels.simulation.simulation_asc_conversion_panel.LtspiceAscToCirTranscriber",
        FakeTranscriber,
    )

    def choose_files(*_args, **_kwargs):
        dialog_calls.append(True)
        return [str(project_a / "demo.asc")], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", choose_files)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: completion_dialogs.append("information"),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: completion_dialogs.append("warning"),
    )

    panel = SimulationAscConversionPanel()
    panel.set_project_root(str(project_a))
    assert panel.choose_files_and_convert() is True
    assert entered.wait(timeout=1)

    panel.set_project_root(str(project_b))
    assert panel.get_web_snapshot()["is_running"] is True
    assert panel.get_web_snapshot()["can_choose_files"] is False
    assert panel.choose_files_and_convert() is None
    panel.set_project_root(str(project_a))
    assert panel.choose_files_and_convert() is None
    assert len(dialog_calls) == 1

    release.set()
    assert finished.wait(timeout=1)
    deadline = time.monotonic() + 1.0
    while panel.get_web_snapshot()["is_running"] and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)

    assert panel.get_web_snapshot()["is_running"] is False
    assert panel.get_web_snapshot()["can_choose_files"] is True
    assert completion_dialogs == []


def test_synchronous_cancel_completion_is_not_overwritten_by_cancelling(qapp):
    view_model = SimulationViewModel()
    view_model.mark_running()
    fake_tab = SimpleNamespace(
        _project_root="/project",
        _displayed_job_id="job-queued",
        _panel_error_message="",
        _runtime_status_message="",
        _view_model=view_model,
        _payload_job_belongs_to_current_project=lambda _job_id: True,
        _get_text=lambda _key, default: default,
        _update_frontend_payloads=lambda: None,
    )
    fake_tab._request_targets_current_project = (
        lambda payload: SimulationTab._request_targets_current_project(fake_tab, payload)
    )
    terminal_job = SimpleNamespace(is_terminal=True)

    class FakeManager:
        def request_cancel(self, _job_id):
            # Mirrors a synchronous manager/EventBus terminal callback.
            fake_tab._displayed_job_id = None
            fake_tab._view_model.mark_cancelled()
            return True

    fake_tab._current_job = lambda: terminal_job
    ServiceLocator.register(SVC_SIMULATION_JOB_MANAGER, FakeManager())
    try:
        SimulationTab._on_cancel_simulation_requested(fake_tab, {
            "project_root": "/project",
            "job_id": "job-queued",
        })
    finally:
        ServiceLocator.unregister(SVC_SIMULATION_JOB_MANAGER)

    assert view_model.simulation_status is SimulationStatus.CANCELLED
    assert fake_tab._displayed_job_id is None


def test_failed_job_loads_exact_persisted_diagnostics(monkeypatch):
    failed_result = SimulationResult(
        executor="spice",
        file_path="circuits/amp.cir",
        analysis_type="tran",
        success=False,
        raw_output="Error: singular matrix",
    )
    rendered = []
    monkeypatch.setattr(
        simulation_tab_module.simulation_result_repository,
        "load",
        lambda project_root, result_path: SimpleNamespace(
            success=project_root == "/project" and result_path == "simulation_results/amp/run/result.json",
            data=failed_result,
            error_message="",
        ),
    )
    fake_tab = SimpleNamespace(
        _project_root="/project",
        _displayed_result_path=None,
        _displayed_circuit_file=None,
        _render_result=lambda result, **kwargs: rendered.append((result, kwargs)),
        _fail_current_result_load=lambda reason: pytest.fail(reason),
    )

    handled = SimulationTab._load_error_result_bundle(
        fake_tab,
        {
            "result_path": "simulation_results/amp/run/result.json",
            "circuit_file": "/project/circuits/amp.cir",
        },
        "singular matrix",
    )

    assert handled is True
    assert fake_tab._displayed_result_path == "simulation_results/amp/run/result.json"
    assert fake_tab._displayed_circuit_file == "circuits/amp.cir"
    assert rendered == [(
        failed_result,
        {"activate_op_tab": False, "error_message_override": "singular matrix"},
    )]
