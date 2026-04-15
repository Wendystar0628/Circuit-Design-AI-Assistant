from PyQt6.QtWidgets import QApplication
import pytest

from presentation.panels.simulation.output_log_viewer import OutputLogViewer


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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
    assert initial_snapshot["first_error"] == "error: singular matrix"

    viewer.search("singular")
    searched_snapshot = viewer.get_web_snapshot(max_lines=0)

    assert searched_snapshot["search_keyword"] == "singular"
    assert searched_snapshot["selected_line_number"] == 3

    viewer.filter_by_level("error")
    filtered_snapshot = viewer.get_web_snapshot()

    assert filtered_snapshot["current_filter"] == "error"
    assert filtered_snapshot["selected_line_number"] == 3
    assert [line["line_number"] for line in filtered_snapshot["lines"]] == [3]

    viewer.filter_by_level("all")
    assert viewer.jump_to_error() is True
    jumped_snapshot = viewer.get_web_snapshot(max_lines=0)

    assert jumped_snapshot["selected_line_number"] == 3

    viewer.clear()
    cleared_snapshot = viewer.get_web_snapshot()

    assert cleared_snapshot["has_log"] is False
    assert cleared_snapshot["search_keyword"] == ""
    assert cleared_snapshot["first_error"] is None
    assert cleared_snapshot["selected_line_number"] is None
