from pathlib import Path

from domain.simulation.measure.measure_authority import (
    MeasureAuthority,
)
from domain.simulation.spice.source_closure import (
    SpiceSourceCommand,
    SpiceSourceLine,
    SpiceSourceView,
    collect_spice_source_closure,
)


def _analysis(statement: str) -> SpiceSourceCommand:
    analysis_type = statement.split(None, 1)[0].lstrip(".").casefold()
    return SpiceSourceCommand(
        source_id="@main",
        line_number=1,
        statement=statement,
        analysis_type=analysis_type,
    )


def _view(
    text: str,
    *,
    source_id: str = "@main",
    is_main_deck: bool = False,
    library_section: str = "",
) -> SpiceSourceView:
    return SpiceSourceView(
        key=source_id,
        source_id=source_id,
        library_section=library_section,
        is_main_deck=is_main_deck,
        lines=tuple(
            SpiceSourceLine(line_number=index, text=line)
            for index, line in enumerate(text.splitlines(), start=1)
        ),
    )


def test_native_measure_expressions_are_preserved_for_ngspice():
    authority = MeasureAuthority()
    documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text=(
                "native measures\n"
                "V1 in 0 1\n"
                ".measure tran product FIND par('v(in) * v(out)') AT=500n\n"
                ".measure tran delay TRIG v(in) VAL={threshold} RISE=1\n"
                "+ TARG v(out) VAL={threshold} RISE=1\n"
                ".tran 1n 1u\n"
                ".end\n"
            ),
        ),
    )

    requests, errors = authority.validate_source_views(
        documents,
        _analysis(".tran 1n 1u"),
    )

    assert errors == []
    assert [request.name for request in requests] == ["product", "delay"]
    assert requests[1].statement.endswith(
        "TARG v(out) VAL={threshold} RISE=1"
    )


def test_main_title_control_and_end_are_not_measurement_sources():
    authority = MeasureAuthority()
    documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text=(
                ".measure tran title_only MAX V(in)\n"
                "V1 in 0 1\n"
                ".measure ac gain MAX V(in)\n"
                ".control\n"
                ".measure tran interactive_only MAX V(in)\n"
                ".endc\n"
                ".end\n"
                ".measure dc after_end MAX V(in)\n"
            ),
        ),
    )

    requests, errors = authority.validate_source_views(
        documents,
        _analysis(".ac dec 10 1 1Meg"),
    )

    assert errors == []
    assert [(item.name, item.line_number) for item in requests] == [("gain", 3)]


def test_measure_scan_uses_the_same_strict_structural_end_boundary():
    documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text=(
                "strict end\n"
                ".end extra\n"
                ".measure tran retained MAX V(out)\n"
                ".end $ comment\n"
                ".measure tran ignored MAX V(out)\n"
            ),
        ),
    )

    requests, errors = MeasureAuthority().validate_source_views(
        documents,
        _analysis(".tran 1n 1u"),
    )

    assert errors == []
    assert [(request.name, request.line_number) for request in requests] == [
        ("retained", 3)
    ]


def test_closure_validation_rejects_dependency_mismatch_and_cross_file_duplicate():
    authority = MeasureAuthority()
    documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text="main\n.measure ac gain MAX V(out)\n.ac dec 10 1 1Meg\n.end\n",
        ),
        _view(
            source_id="deps/analyses.inc",
            text=(
                ".measure tran hidden_peak MAX V(out)\n"
                ".measure ac GAIN MIN V(out)\n"
            ),
        ),
    )

    requests, errors = authority.validate_source_views(
        documents,
        _analysis(".ac dec 10 1 1Meg"),
    )

    assert [request.source_id for request in requests] == [
        "@main",
        "deps/analyses.inc",
        "deps/analyses.inc",
    ]
    assert [error.error_type for error in errors] == [
        "ANALYSIS_TYPE_MISMATCH",
        "DUPLICATE_RESULT_NAME",
    ]
    assert [(error.source_id, error.line_number) for error in errors] == [
        ("deps/analyses.inc", 1),
        ("deps/analyses.inc", 2),
    ]


def test_op_and_noise_results_reject_top_level_measure_cards():
    authority = MeasureAuthority()
    op_documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text="op\n.measure tran peak MAX V(out)\n.op\n.end\n",
        ),
    )
    noise_documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text=(
                "noise\n.measure ac peak MAX V(out)\n"
                ".noise V(out) Vin dec 10 1 1Meg\n.end\n"
            ),
        ),
    )

    _, op_errors = authority.validate_source_views(
        op_documents,
        _analysis(".op"),
    )
    _, noise_errors = authority.validate_source_views(
        noise_documents,
        _analysis(".noise V(out) Vin dec 10 1 1Meg"),
    )

    assert [error.error_type for error in op_errors] == [
        "UNSUPPORTED_FINAL_ANALYSIS"
    ]
    assert [error.error_type for error in noise_errors] == [
        "UNSUPPORTED_FINAL_ANALYSIS"
    ]


def test_malformed_native_measure_header_is_not_silently_ignored():
    authority = MeasureAuthority()
    documents = (
        _view(
            source_id="deps/bad.inc",
            text=".measure ac missing_body\n",
        ),
    )

    requests, errors = authority.validate_source_views(
        documents,
        _analysis(".ac dec 10 1 1Meg"),
    )

    assert requests == ()
    assert [error.error_type for error in errors] == [
        "INVALID_MEASURE_HEADER"
    ]
    assert errors[0].source_id == "deps/bad.inc"
    assert errors[0].line_number == 1
    assert errors[0].message.startswith("deps/bad.inc:1:")


def test_measure_card_analysis_type_is_limited_to_ngspice_top_level_domains():
    authority = MeasureAuthority()
    documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text="demo\n.measure sp peak MAX VDB(out)\n.ac dec 10 1 1Meg\n.end\n",
        ),
    )

    _, errors = authority.validate_source_views(
        documents,
        _analysis(".ac dec 10 1 1Meg"),
    )

    assert [error.error_type for error in errors] == ["INVALID_ANALYSIS_TYPE"]


def test_unselected_library_section_cannot_publish_or_conflict_with_metrics(
    tmp_path: Path,
):
    library = tmp_path / "metrics.lib"
    library.write_text(
        ".lib TT\n.measure ac gain MAX V(out)\n.endl TT\n"
        ".lib UNUSED\n.measure tran GAIN MAX V(out)\n.endl UNUSED\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.cir"
    main.write_text(
        "selected metric\n.lib metrics.lib TT\n.ac dec 10 1 1Meg\n.end\n",
        encoding="utf-8",
    )

    graph = collect_spice_source_closure(main)
    requests, errors = MeasureAuthority().validate_source_views(
        graph.active_views,
        graph.main_analysis_commands[0],
    )

    assert errors == []
    assert [(request.name, request.source_id, request.line_number) for request in requests] == [
        ("gain", "metrics.lib", 2)
    ]


def test_nested_dc_measure_is_rejected_without_outer_sweep_identity():
    documents = (
        _view(
            source_id="@main",
            is_main_deck=True,
            text=(
                "nested dc\n"
                "V1 out 0 0\n"
                "V2 aux 0 0\n"
                ".measure dc ambiguous FIND V(aux) AT={inner / 2}\n"
                ".dc V1 0 {inner} 1 V2 0 {outer max} 1\n"
                ".end\n"
            ),
        ),
    )

    requests, errors = MeasureAuthority().validate_source_views(
        documents,
        _analysis(".dc V1 0 {inner} 1 V2 0 {outer max} 1"),
    )

    assert [request.name for request in requests] == ["ambiguous"]
    assert [error.error_type for error in errors] == [
        "NESTED_DC_MEASURE_UNSUPPORTED"
    ]
    assert "外层扫描值" in errors[0].message
