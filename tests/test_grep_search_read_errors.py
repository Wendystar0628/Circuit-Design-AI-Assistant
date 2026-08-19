import asyncio
import builtins
import os
from pathlib import Path

from domain.llm.agent.tools.grep_search import GrepSearchTool
from domain.llm.agent.types import ToolContext


def _run_grep(project_root: Path, **params):
    return asyncio.run(
        GrepSearchTool().execute(
            tool_call_id="call-grep",
            params=params,
            context=ToolContext(project_root=str(project_root)),
        )
    )


def _deny_binary_reads(monkeypatch, denied_paths, message="access denied"):
    denied = {os.path.normcase(os.path.abspath(str(path))) for path in denied_paths}
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        try:
            identity = os.path.normcase(os.path.abspath(os.fspath(file)))
        except TypeError:
            identity = ""
        if identity in denied and "rb" in str(mode):
            raise PermissionError(message)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)


def test_grep_search_matches_utf16_spice_file(tmp_path):
    circuit = tmp_path / "utf16.cir"
    circuit.write_text("R1 in out 1k\n* TARGET_TOKEN\n.end\n", encoding="utf-16")

    result = _run_grep(
        tmp_path,
        pattern="TARGET_TOKEN",
        path="utf16.cir",
        fixed_strings=True,
    )

    assert result.is_error is False
    assert "utf16.cir:2:" in result.content
    assert "TARGET_TOKEN" in result.content
    assert result.details["candidate_files"] == 1
    assert result.details["files_searched"] == 1
    assert result.details["read_error_count"] == 0
    assert result.details["skipped_binary"] == 0
    assert result.details["incomplete"] is False


def test_specified_unreadable_file_is_an_error_with_bounded_summary(
    tmp_path,
    monkeypatch,
):
    denied = tmp_path / "denied.cir"
    denied.write_text("PRIVATE_FILE_CONTENT", encoding="utf-8")
    _deny_binary_reads(monkeypatch, [denied], message="x" * 1000)

    result = _run_grep(
        tmp_path,
        pattern="PRIVATE_FILE_CONTENT",
        path="denied.cir",
        fixed_strings=True,
    )

    assert result.is_error is True
    assert "could not scan any readable text files" in result.content
    assert "denied.cir" in result.content
    assert "PermissionError" in result.content
    assert "PRIVATE_FILE_CONTENT" not in result.content
    assert len(result.content) < 800
    assert len(result.details["read_errors"][0]["message"]) <= 160
    assert result.details["candidate_files"] == 1
    assert result.details["files_searched"] == 0
    assert result.details["read_error_count"] == 1
    assert result.details["incomplete"] is True


def test_directory_where_all_candidates_fail_is_an_error(tmp_path, monkeypatch):
    first = tmp_path / "first.cir"
    second = tmp_path / "second.cir"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    _deny_binary_reads(monkeypatch, [first, second])

    result = _run_grep(
        tmp_path,
        pattern="anything",
        glob="*.cir",
    )

    assert result.is_error is True
    assert "candidates=2" in result.content
    assert "read_errors=2" in result.content
    assert result.details["files_searched"] == 0
    assert result.details["read_error_count"] == 2


def test_partial_read_failure_marks_matching_results_incomplete(
    tmp_path,
    monkeypatch,
):
    readable = tmp_path / "readable.cir"
    denied = tmp_path / "denied.cir"
    readable.write_text("R_TARGET in out 1k\n", encoding="utf-8")
    denied.write_text("not exposed", encoding="utf-8")
    _deny_binary_reads(monkeypatch, [denied])

    result = _run_grep(
        tmp_path,
        pattern="R_TARGET",
        glob="*.cir",
        fixed_strings=True,
    )

    assert result.is_error is False
    assert "readable.cir:1:" in result.content
    assert "search incomplete" in result.content
    assert "denied.cir" in result.content
    assert result.details["candidate_files"] == 2
    assert result.details["files_searched"] == 1
    assert result.details["read_error_count"] == 1
    assert result.details["incomplete"] is True


def test_partial_read_failure_is_not_reported_as_complete_no_match(
    tmp_path,
    monkeypatch,
):
    readable = tmp_path / "readable.cir"
    denied = tmp_path / "denied.cir"
    readable.write_text("R1 in out 1k\n", encoding="utf-8")
    denied.write_text("not exposed", encoding="utf-8")
    _deny_binary_reads(monkeypatch, [denied])

    result = _run_grep(
        tmp_path,
        pattern="ABSENT_TOKEN",
        glob="*.cir",
        fixed_strings=True,
    )

    assert result.is_error is False
    assert result.content.startswith(
        "No matches found in the files that were successfully scanned."
    )
    assert "search incomplete" in result.content
    assert result.content != "No matches found."
    assert result.details["files_searched"] == 1
    assert result.details["read_error_count"] == 1
    assert result.details["incomplete"] is True


def test_binary_files_are_counted_without_becoming_decode_errors(tmp_path):
    readable = tmp_path / "readable.cir"
    binary = tmp_path / "image.png"
    readable.write_text("nothing here\n", encoding="utf-8")
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")

    result = _run_grep(tmp_path, pattern="missing")

    assert result.is_error is False
    assert result.content == "No matches found."
    assert result.details["candidate_files"] == 2
    assert result.details["files_searched"] == 1
    assert result.details["read_error_count"] == 0
    assert result.details["skipped_binary"] == 1
    assert result.details["incomplete"] is False


def test_binary_only_target_is_skipped_without_a_false_read_error(tmp_path):
    binary = tmp_path / "image.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")

    result = _run_grep(tmp_path, pattern="missing", path="image.png")

    assert result.is_error is False
    assert result.content == "No matches found."
    assert result.details["candidate_files"] == 1
    assert result.details["files_searched"] == 0
    assert result.details["read_error_count"] == 0
    assert result.details["skipped_binary"] == 1
    assert result.details["incomplete"] is False
