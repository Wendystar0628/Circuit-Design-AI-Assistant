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
  and embed each group's newest summary as ``latest_result`` using the
  single generic loadable-result schema.
"""

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
        "selected_files_summary": "",
    }


def test_serialize_loadable_result_normalizes_result_path_and_current_match():
    groups, amp_new, *_ = _build_two_circuit_fixture()
    del groups

    payload = SimulationFrontendStateSerializer().serialize_loadable_result(
        amp_new,
        current_result_path="simulation_results/amp/run_2026_04_19_12_00/result.json",
    )

    assert payload == {
        "id": amp_new.id,
        "result_path": amp_new.result_path.lower(),
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
    newest-run-first), and each card embeds its group's newest summary
    as ``latest_result``."""
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
    assert cards[0]["latest_result"]["id"] == amp_new.id
    assert cards[1]["latest_result"]["id"] == filter_mid.id
    # The embedded latest-result row deliberately sets ``is_current``
    # to False even if it is the newest run — card-level currency is
    # decided above via ``displayed_circuit_file``, never by whether
    # the specific bundle happens to be loaded right now.
    assert cards[0]["latest_result"]["is_current"] is False


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
    assert payload["circuit_selection_view"]["selected_circuit_file"] == "circuits/amp.cir"


def test_latest_result_shares_schema_with_history_row():
    """Field-level deduplication invariant: the latest-result card
    payload uses the single generic persisted-result load-target
    schema on the wire."""
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
    card_latest = payload["circuit_selection_view"]["items"][0]["latest_result"]
    assert set(card_latest.keys()) == set(loadable_result.keys())
    # ``is_current`` is the one field whose value legitimately differs
    # (see the card-level rationale in
    # :meth:`serialize_circuit_selection_view`). Every other field
    # describes the bundle itself and must agree verbatim.
    shared_keys = set(loadable_result.keys()) - {"is_current"}
    for key in shared_keys:
        assert card_latest[key] == loadable_result[key], key


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
