"""Contract tests for :class:`SimulationFrontendStateSerializer`.

Step 11 collapsed the pre-flattened ``history_results=`` input into a
single ``circuit_groups=`` entry point, with both the flat history-
results view and the grouped circuit-selection view derived inside
the serializer. These tests pin down the resulting wire contract so
the two surfaces cannot drift independently:

* One cache object feeds both views (no hidden second disk scan, no
  caller-side pre-flattening).
* The flat history ``items`` stay timestamp-descending across
  circuits, matching the pre-Step-11 ordering.
* The circuit-selection cards preserve group order, key ``is_current``
  off ``displayed_circuit_file`` with POSIX + case-fold normalisation,
  and embed each group's newest summary as ``latest_result`` using
  the exact same schema as the flat history row (the field-level
  deduplication invariant from the plan).
"""

from domain.simulation.service.simulation_result_repository import (
    CircuitResultGroup,
    SimulationResultSummary,
)
from presentation.panels.simulation.simulation_frontend_state_serializer import (
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
    """Two circuits, three runs total.

    Group ``amp`` has two runs (newest first, per repository contract)
    and ``amp``'s newest run is globally newer than ``filter``'s single
    run — so the flat history must interleave groups purely by
    timestamp, not by group identity.
    """
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


def test_history_results_view_flattens_groups_newest_first():
    """Flat view ordering is global timestamp-desc, independent of
    group traversal order."""
    groups, amp_new, amp_old, filter_mid = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
    )

    history_items = payload["history_results_view"]["items"]
    assert [item["id"] for item in history_items] == [
        amp_new.id,
        filter_mid.id,
        amp_old.id,
    ]
    assert payload["history_results_view"]["can_load"] is True
    # No project_root => no history loads are meaningful.
    empty_payload = SimulationFrontendStateSerializer().serialize_main_state(
        circuit_groups=groups,
    )
    assert empty_payload["history_results_view"]["can_load"] is False


def test_history_row_is_current_matches_current_result_path_case_insensitively():
    """``is_current`` on flat-view rows uses the same POSIX + lowercase
    normalisation as the stored ``result_path`` — Windows-born
    separators or case differences must still match the selection."""
    groups, amp_new, _amp_old, _filter_mid = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
        # Caller passed a Windows-style mixed-case path: must still
        # resolve to the ``amp_new`` row as current.
        current_result_path="Simulation_Results\\AMP\\run_2026_04_19_12_00\\result.json",
    )
    history_items = payload["history_results_view"]["items"]
    current_rows = [item for item in history_items if item["is_current"]]
    assert [row["id"] for row in current_rows] == [amp_new.id]
    # The canonicalised path is echoed back to the frontend verbatim.
    assert payload["history_results_view"]["selected_result_path"] == amp_new.result_path.lower()


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
    payload is emitted by the same :meth:`serialize_history_item`
    used for the flat history row, so the two surfaces share one
    schema on the wire."""
    groups, amp_new, *_ = _build_two_circuit_fixture()

    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=groups,
    )

    history_row = next(
        item for item in payload["history_results_view"]["items"]
        if item["id"] == amp_new.id
    )
    card_latest = payload["circuit_selection_view"]["items"][0]["latest_result"]
    assert set(card_latest.keys()) == set(history_row.keys())
    # ``is_current`` is the one field whose value legitimately differs
    # (see the card-level rationale in
    # :meth:`serialize_circuit_selection_view`). Every other field
    # describes the bundle itself and must agree verbatim.
    shared_keys = set(history_row.keys()) - {"is_current"}
    for key in shared_keys:
        assert card_latest[key] == history_row[key], key


def test_empty_circuit_groups_produce_empty_views():
    """No groups => both derived views are empty but well-formed."""
    payload = SimulationFrontendStateSerializer().serialize_main_state(
        project_root="/projects/demo",
        circuit_groups=[],
    )
    assert payload["history_results_view"]["items"] == []
    assert payload["circuit_selection_view"]["items"] == []
    assert payload["circuit_selection_view"]["selected_circuit_file"] == ""


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
    assert payload["history_results_view"]["items"] == []
