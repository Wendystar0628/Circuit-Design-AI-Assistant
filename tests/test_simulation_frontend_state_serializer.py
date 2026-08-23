"""Contract tests for :class:`SimulationFrontendStateSerializer`.

The simulation panel now exposes a single persisted-result browsing
surface: ``circuit_selection_view``. These tests pin down the resulting
wire contract so the deleted peer history tab cannot silently reappear:

* One by-circuit cache object feeds the card grid directly.
* ``history`` is absent from the payload's available tabs and no
  ``history_results_view`` / ``has_history`` compatibility fields
  remain.
* The circuit-selection cards preserve group order, key ``is_current``
  off ``displayed_circuit_file`` with POSIX + case-fold normalisation,
  and expose every run using the single generic loadable-result schema.
"""

import numpy as np

from domain.simulation.models.display_metric import DisplayMetric
from domain.simulation.data.noise_totals import build_noise_totals_payload
from domain.simulation.models.simulation_result import (
    NoiseTotals,
    SimulationData,
    SimulationResult,
)
from domain.simulation.service.simulation_result_repository import (
    CircuitResultGroup,
    SimulationResultSummary,
)
from presentation.panels.simulation.simulation_frontend_state_serializer import (
    ALL_TAB_IDS,
    SimulationFrontendStateSerializer,
)


def _make_summary(
    *,
    bundle: str,
    circuit_file: str,
    timestamp: str,
    analysis_type: str = "tran",
    success: bool = True,
) -> SimulationResultSummary:
    """Build a summary whose paths mirror the repository's POSIX
    project-relative convention.

    ``id`` and ``result_path`` are derived from ``bundle`` the same
    way :meth:`SimulationResultRepository.list_by_circuit` derives
    them from disk layout, so the test fixture exercises realistic
    inputs instead of ad-hoc strings.
    """
    return SimulationResultSummary(
        id=bundle,
        result_path=f"{bundle}/result.json",
        circuit_file=circuit_file,
        analysis_type=analysis_type,
        success=success,
        timestamp=timestamp,
    )


def _make_group(
    *,
    circuit_file: str,
    circuit_absolute_path: str,
    results,
) -> CircuitResultGroup:
    return CircuitResultGroup(
        circuit_file=circuit_file,
        circuit_absolute_path=circuit_absolute_path,
        results=list(results),
    )


def _build_two_circuit_fixture():
    """Two circuits, three runs total."""
    amp_new = _make_summary(
        bundle="simulation_results/amp/run_2026_04_19_12_00",
        circuit_file="circuits/amp.cir",
        timestamp="2026-04-19T12:00:00",
    )
    amp_old = _make_summary(
        bundle="simulation_results/amp/run_2026_04_18_09_00",
        circuit_file="circuits/amp.cir",
        timestamp="2026-04-18T09:00:00",
    )
    filter_mid = _make_summary(
        bundle="simulation_results/filter/run_2026_04_18_20_00",
        circuit_file="circuits/filter.cir",
        timestamp="2026-04-18T20:00:00",
        analysis_type="ac",
        success=False,
    )
    groups = [
        _make_group(
            circuit_file="circuits/amp.cir",
            circuit_absolute_path="/projects/demo/circuits/amp.cir",
            results=[amp_new, amp_old],
        ),
        _make_group(
            circuit_file="circuits/filter.cir",
            circuit_absolute_path="/projects/demo/circuits/filter.cir",
            results=[filter_mid],
        ),
    ]
    return groups, amp_new, amp_old, filter_mid


def test_surface_tabs_do_not_expose_history_tab_or_flag():
    groups, *_ = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
    )

    assert "history" not in payload["surface_tabs"]["available_tabs"]
    assert ALL_TAB_IDS.index("export") < ALL_TAB_IDS.index("asc_conversion")
    assert ALL_TAB_IDS.index("asc_conversion") < ALL_TAB_IDS.index("op_result")
    assert payload["surface_tabs"]["available_tabs"].index("export") < payload["surface_tabs"]["available_tabs"].index("asc_conversion")
    assert "has_history" not in payload["surface_tabs"]
    assert "history_results_view" not in payload
    assert payload["asc_conversion_view"] == {
        "can_choose_files": True,
        "is_running": False,
        "selected_files_summary": "",
    }


def test_runtime_exposes_exact_live_job_identity_for_cancel_requests():
    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        current_job_id="job-owned-by-this-surface",
        simulation_status="running",
        can_cancel=True,
    )

    assert payload["simulation_runtime"]["project_root"] == "/projects/demo"
    assert payload["simulation_runtime"]["current_job_id"] == "job-owned-by-this-surface"
    assert payload["simulation_runtime"]["can_cancel"] is True


def test_schema3_derives_axis_view_fields_without_persisting_duplicates():
    result = SimulationResult(
        executor="spice",
        file_path="circuits/filter.cir",
        analysis_type="ac",
        success=True,
        source_digest="0" * 64,
        data=SimulationData(
            frequency=np.array([1.0, 10.0, 100.0, 1000.0]),
            signals={
                "V(out)": np.array(
                    [1.0 + 0j, 0.5 + 0j, 0.2 + 0j, 0.1 + 0j]
                )
            },
            signal_types={"V(out)": "voltage"},
        ),
        analysis_command=".ac dec 1 1 1k",
    )

    persisted = result.to_dict()
    redundant_axis_keys = {
        "x_axis_kind",
        "x_axis_label",
        "x_axis_scale",
        "requested_x_range",
        "actual_x_range",
    }
    assert redundant_axis_keys.isdisjoint(persisted)

    loaded = SimulationResult.from_dict(persisted)
    serializer = SimulationFrontendStateSerializer()
    result_view = serializer.serialize_result(
        loaded,
        "simulation_results/filter/run/result.json",
    )
    analysis_view = serializer.serialize_analysis_info(loaded)

    for view in (result_view, analysis_view):
        assert view["x_axis_kind"] == "frequency"
        assert view["x_axis_label"] == "Frequency (Hz)"
        assert view["x_axis_scale"] == "log"
        assert view["requested_x_range"] == [1.0, 1000.0]
        assert view["actual_x_range"] == [1.0, 1000.0]


def test_serialize_loadable_result_normalizes_result_path_and_current_match():
    groups, amp_new, *_ = _build_two_circuit_fixture()
    del groups

    payload = SimulationFrontendStateSerializer().serialize_loadable_result(
        amp_new,
        current_result_path="simulation_results/amp/run_2026_04_19_12_00/result.json",
    )

    assert payload == {
        "id": amp_new.id,
        "result_path": amp_new.result_path,
        "file_path": "circuits/amp.cir",
        "file_name": "amp.cir",
        "analysis_type": "tran",
        "success": True,
        "timestamp": "2026-04-19T12:00:00",
        "is_current": True,
        "can_load": True,
    }


def test_circuit_selection_view_has_one_card_per_group_in_input_order():
    """Cards mirror ``circuit_groups`` order (repository yields them
    newest-run-first), without hiding older runs."""
    groups, amp_new, _amp_old, filter_mid = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
    )

    cards = payload["circuit_selection_view"]["items"]
    assert [card["circuit_file"] for card in cards] == [
        "circuits/amp.cir",
        "circuits/filter.cir",
    ]
    assert [card["run_count"] for card in cards] == [2, 1]
    assert [card["circuit_display_name"] for card in cards] == ["amp", "filter"]
    assert [result["id"] for result in cards[0]["results"]] == [
        amp_new.id,
        _amp_old.id,
    ]
    assert [result["id"] for result in cards[1]["results"]] == [filter_mid.id]
    assert all(not result["is_current"] for result in cards[0]["results"])


def test_circuit_selection_view_is_current_uses_case_and_separator_insensitive_match():
    """``displayed_circuit_file`` normalisation mirrors the card's own
    ``circuit_file`` normalisation — Windows-born mixed-case paths
    still flag the right card as current."""
    groups, *_ = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
        displayed_circuit_file="Circuits\\AMP.CIR",
    )

    cards = payload["circuit_selection_view"]["items"]
    current_cards = [card for card in cards if card["is_current"]]
    assert [card["circuit_file"] for card in current_cards] == ["circuits/amp.cir"]
    # Wire addresses preserve source case; only the comparison key is folded.
    assert payload["circuit_selection_view"]["selected_circuit_file"] == "Circuits/AMP.CIR"


def test_live_absolute_circuit_identity_matches_persisted_relative_card():
    groups, *_ = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
        displayed_circuit_file="/projects/demo/circuits/amp.cir",
    )

    current_cards = [
        card for card in payload["circuit_selection_view"]["items"]
        if card["is_current"]
    ]
    assert [card["circuit_file"] for card in current_cards] == ["circuits/amp.cir"]


def test_raw_data_viewport_preserves_zero_and_empty_cell_positions():
    payload = SimulationFrontendStateSerializer().serialize_raw_data_viewport({
        "dataset_id": "d1",
        "version": 1,
        "rows": [{"row_index": 0, "values": [0, "", 2.5, None]}],
    })

    assert payload["rows"][0]["values"] == ["0", "", "2.5", ""]


def test_failed_metric_wire_row_preserves_status_and_diagnostic_without_fake_value():
    payload = SimulationFrontendStateSerializer().serialize_metric(
        DisplayMetric(
            name="bandwidth",
            display_name="Bandwidth",
            value="",
            unit="Hz",
            status="FAILED",
            error_message="Error: out of interval",
            raw_value=None,
            target="> 1 MHz",
        )
    )

    assert payload == {
        "name": "bandwidth",
        "display_name": "Bandwidth",
        "value": "",
        "unit": "Hz",
        "status": "FAILED",
        "error_message": "Error: out of interval",
        "raw_value": None,
        "target": "> 1 MHz",
    }


def _noise_result(
    input_type: str,
    *,
    totals: NoiseTotals | None,
) -> SimulationResult:
    point_count = 2 if totals is not None else 1
    return SimulationResult(
        executor="spice",
        file_path="circuits/noise.cir",
        analysis_type="noise",
        success=True,
        source_digest="0" * 64,
        data=SimulationData(
            frequency=np.arange(1, point_count + 1, dtype=float),
            signals={
                "onoise_spectrum": np.full(point_count, 2e-9),
                "inoise_spectrum": np.full(point_count, 1e-9),
            },
            signal_types={
                "onoise_spectrum": "voltage",
                "inoise_spectrum": input_type,
            },
            noise_totals=totals,
        ),
        analysis_command=(
            f".noise V(out) {'V1' if input_type == 'voltage' else 'I1'} "
            f"lin {point_count} 1 2"
        ),
    )


def test_noise_totals_are_separate_read_only_scalars_with_base_rms_units():
    serializer = SimulationFrontendStateSerializer()
    for input_type, expected_units, expected_source in (
        ("voltage", ["V", "V"], "V1"),
        ("current", ["V", "A"], "I1"),
    ):
        result = _noise_result(
            input_type,
            totals=NoiseTotals(output_rms=3e-9, input_referred_rms=1.5e-9),
        )
        result = SimulationResult.from_dict(result.to_dict())
        assert f" V(out) {expected_source} " in result.analysis_command
        state = serializer.serialize_main_state(current_result=result)
        raw_document = serializer.serialize_raw_data_document(
            {"has_data": True, "columns": [{"key": "x", "label": "Frequency", "width_px": 100}]},
            result,
        )
        expected = state["metrics_view"]["noise_totals"]

        assert expected["applicable"] is True
        assert expected["available"] is True
        assert [item["key"] for item in expected["items"]] == [
            "output_rms",
            "input_referred_rms",
        ]
        assert [item["value"] for item in expected["items"]] == [3e-9, 1.5e-9]
        assert [item["unit"] for item in expected["items"]] == expected_units
        assert state["analysis_info_view"]["noise_totals"] == expected
        assert raw_document["noise_totals"] == expected
        assert all("√Hz" not in item["unit"] for item in expected["items"])


def test_noise_totals_null_does_not_invent_values_or_units():
    unavailable = build_noise_totals_payload(
        _noise_result("voltage", totals=None)
    )

    assert unavailable == {
        "applicable": True,
        "available": False,
        "source": "ngspice_noise_totals",
        "items": [],
    }


def test_card_results_share_the_generic_loadable_result_schema():
    """Every card run uses the generic persisted-result load schema."""
    groups, amp_new, *_ = _build_two_circuit_fixture()

    serializer = SimulationFrontendStateSerializer()
    payload = serializer.serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
    )

    loadable_result = serializer.serialize_loadable_result(
        amp_new,
        current_result_path=amp_new.result_path.lower(),
    )
    card_latest = payload["circuit_selection_view"]["items"][0]["results"][0]
    assert set(card_latest.keys()) == set(loadable_result.keys())
    for key in loadable_result:
        if key != "is_current":
            assert card_latest[key] == loadable_result[key], key


def test_older_loaded_run_is_marked_exactly_current_in_its_card():
    groups, _amp_new, amp_old, _filter_mid = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
        displayed_circuit_file="circuits/amp.cir",
        current_result_path=amp_old.result_path,
    )

    amp_results = payload["circuit_selection_view"]["items"][0]["results"]
    assert [result["is_current"] for result in amp_results] == [False, True]


def test_empty_circuit_groups_produce_empty_views():
    """No groups => the card grid is empty and no deleted history view returns."""
    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=[],
    )
    assert payload["circuit_selection_view"]["items"] == []
    assert payload["circuit_selection_view"]["selected_circuit_file"] == ""
    assert "history_results_view" not in payload


def test_group_with_no_results_is_skipped_from_circuit_selection():
    """Defensive: a group with an empty ``results`` list has no
    newest bundle to show, so the card grid skips it rather than
    rendering a blank card."""
    groups = [
        _make_group(
            circuit_file="circuits/empty.cir",
            circuit_absolute_path="/projects/demo/circuits/empty.cir",
            results=[],
        ),
    ]
    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
    )
    assert payload["circuit_selection_view"]["items"] == []
    assert "history_results_view" not in payload
