from presentation.panels.simulation.output_log_viewer import OutputLogViewer


def test_output_log_viewer_snapshot_tracks_search_filter_and_selection(qapp):
    viewer = OutputLogViewer()
    viewer.load_log_from_text(
        "Starting analysis\n"
        "warning: floating node detected\n"
        "error: singular matrix\n"
        "analysis completed\n"
    )

    initial_snapshot = viewer.get_web_snapshot()

    assert initial_snapshot["has_log"] is True
    assert initial_snapshot["search_keyword"] == ""
    assert initial_snapshot["selected_line_number"] is None
    assert initial_snapshot["total_line_count"] == 4
    assert initial_snapshot["is_truncated"] is False
    assert "first_error" not in initial_snapshot
    assert "can_refresh" not in initial_snapshot

    viewer.search("singular")
    searched_snapshot = viewer.get_web_snapshot(max_lines=0)

    assert searched_snapshot["search_keyword"] == "singular"
    assert searched_snapshot["selected_line_number"] == 3

    viewer.filter_by_level("error")
    filtered_snapshot = viewer.get_web_snapshot()

    assert filtered_snapshot["current_filter"] == "error"
    assert filtered_snapshot["selected_line_number"] == 3
    assert [line["line_number"] for line in filtered_snapshot["lines"]] == [3]
    assert viewer.get_filtered_text() == "error: singular matrix"

    viewer.clear()
    cleared_snapshot = viewer.get_web_snapshot()

    assert cleared_snapshot["has_log"] is False
    assert cleared_snapshot["search_keyword"] == ""
    assert "first_error" not in cleared_snapshot
    assert cleared_snapshot["selected_line_number"] is None


def test_output_log_copy_source_is_not_limited_to_render_window(qapp):
    viewer = OutputLogViewer()
    viewer.load_log_from_text("\n".join(f"line {index}" for index in range(10_050)))

    snapshot = viewer.get_web_snapshot(max_lines=1000)

    assert snapshot["visible_line_count"] == 1000
    assert snapshot["total_line_count"] == 10_050
    assert snapshot["is_truncated"] is True
    copied_lines = viewer.get_filtered_text().splitlines()
    assert len(copied_lines) == 10_050
    assert copied_lines[-1] == "line 10049"
