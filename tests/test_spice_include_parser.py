from pathlib import Path

from domain.simulation.spice.include_parser import IncludeParser


def test_include_parser_handles_quoted_paths_comments_and_incpslt() -> None:
    parsed = IncludeParser().parse_content(
        '.include "models/vendor parts.lib" ; comment\n'
        ".inc models/short-form.lib // comment\n"
        ".incpslt 'models/protected library.lib' $ comment\n"
    )

    assert [(item.statement_type, item.raw_path) for item in parsed] == [
        ("include", "models/vendor parts.lib"),
        ("include", "models/short-form.lib"),
        ("incpslt", "models/protected library.lib"),
    ]


def test_lib_parser_distinguishes_file_selection_from_section_definition() -> None:
    parsed = IncludeParser().parse_content(
        '.lib "models/process.lib" TT\n'
        ".lib FAST\n"
        ".endl FAST\n"
    )

    assert len(parsed) == 1
    assert parsed[0].statement_type == "lib"
    assert parsed[0].raw_path == "models/process.lib"
    assert parsed[0].library_section == "TT"


def test_resolve_path_is_relative_to_containing_file_not_process_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    model = project / "models" / "part.lib"
    model.parent.mkdir(parents=True)
    model.write_text("* model\n", encoding="utf-8")
    parsed = IncludeParser().parse_line(".include models/part.lib", 1)
    assert parsed is not None

    parsed.resolve_path(project, project)

    assert parsed.exists is True
    assert parsed.resolved_path == str(Path("models") / "part.lib")
