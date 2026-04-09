from domain.rag.file_extractor import (
    ATTACHMENT_TEXT_EXTENSIONS,
    extract_attachment_text,
    get_file_index_rule,
    is_image_attachment_path,
    resolve_attachment_type,
)


def test_csv_is_readable_for_attachments_but_excluded_from_indexing(tmp_path):
    csv_path = tmp_path / "dataset.csv"
    csv_path.write_text("time,value\n0,1\n", encoding="utf-8")

    rule = get_file_index_rule(str(csv_path))

    assert rule is not None
    assert rule.should_index is False
    assert extract_attachment_text(str(csv_path)) == "time,value\n0,1\n"


def test_simulation_results_directory_is_excluded_from_indexing(tmp_path):
    result_json_path = tmp_path / "simulation_results" / "amp" / "result.json"
    result_json_path.parent.mkdir(parents=True)
    result_json_path.write_text('{"ok": true}', encoding="utf-8")

    rule = get_file_index_rule(str(result_json_path))

    assert rule is not None
    assert rule.should_index is False
    assert "simulation_results" in rule.exclude_reason


def test_regular_json_outside_simulation_results_stays_indexable(tmp_path):
    doc_path = tmp_path / "docs" / "design.json"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text('{"title": "design"}', encoding="utf-8")

    rule = get_file_index_rule(str(doc_path))

    assert rule is not None
    assert rule.should_index is True


def test_attachment_text_registry_contains_required_text_extensions():
    assert ".txt" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".json" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".cpp" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".py" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".spice" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".pdf" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".docx" in ATTACHMENT_TEXT_EXTENSIONS
    assert ".csv" in ATTACHMENT_TEXT_EXTENSIONS


def test_attachment_image_detection_uses_path_or_mime_type():
    assert is_image_attachment_path("diagram.png") is True
    assert is_image_attachment_path("photo.jpeg") is True
    assert is_image_attachment_path("unknown.bin", "image/png") is True
    assert is_image_attachment_path("notes.txt") is False


def test_resolve_attachment_type_upgrades_image_like_files():
    assert resolve_attachment_type("diagram.png", "image/png") == "image"
    assert resolve_attachment_type("photo.jpeg", "") == "image"
    assert resolve_attachment_type("report.pdf", "application/pdf") == "file"
