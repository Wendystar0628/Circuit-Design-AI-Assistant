from __future__ import annotations

import hashlib
import posixpath
from pathlib import Path

import pytest

from domain.simulation.spice.source_closure import (
    SPICE_SOURCE_CLOSURE_ALGORITHM,
    SpiceSourceClosureError,
    build_spice_source_closure,
    collect_spice_source_closure,
    snapshot_spice_source_closure,
)


def _memory_graph(blobs: dict[str, bytes], main_key: str = "circuits/main.cir"):
    reads: dict[str, int] = {}

    def load_bytes(key: str) -> bytes:
        reads[key] = reads.get(key, 0) + 1
        return blobs[key]

    def resolve_reference(parent_key: str, raw_path: str) -> str:
        return posixpath.normpath(
            posixpath.join(posixpath.dirname(parent_key), raw_path)
        )

    main_dir = posixpath.dirname(main_key)

    def identify_source(
        _parent_key: str,
        _parent_id: str,
        target_key: str,
        _raw_path: str,
    ) -> str:
        return posixpath.relpath(target_key, main_dir)

    graph = build_spice_source_closure(
        main_key,
        load_bytes=load_bytes,
        resolve_reference=resolve_reference,
        identify_source=identify_source,
    )
    return graph, reads


def test_pure_builder_has_one_canonical_digest_vector_and_reads_each_blob_once():
    blobs = {
        "circuits/main.cir": (
            b"closure vector\n.include ../models/a.lib\n.op\n.end\n"
        ),
        "models/a.lib": b".include nested/b.inc\n.model DTEST D\n",
        "models/nested/b.inc": b".param rval=1k\n",
    }

    graph, reads = _memory_graph(blobs)

    assert graph.digest == (
        "41df6e40109d477d08ce2e112964ecab"
        "95f2751560477cc90276e31dd7e87cf5"
    )
    assert SPICE_SOURCE_CLOSURE_ALGORITHM == "spice-source-closure-v1"
    assert reads == {key: 1 for key in blobs}
    assert [blob.source_id for blob in graph.blobs] == [
        "../models/a.lib",
        "../models/nested/b.inc",
        "@main",
    ]
    assert [
        (
            edge.parent_id,
            edge.line_number,
            edge.statement_type,
            edge.target_id,
            edge.library_section,
        )
        for edge in graph.references
    ] == [
        ("../models/a.lib", 1, "include", "../models/nested/b.inc", ""),
        ("@main", 2, "include", "../models/a.lib", ""),
    ]


def test_main_bytes_injection_prevents_a_second_main_read():
    main = b"injected main\n.include dep.lib\n.op\n.end\n"
    blobs = {"circuits/dep.lib": b".param x=1\n"}
    reads: list[str] = []

    graph = build_spice_source_closure(
        "circuits/main.cir",
        load_bytes=lambda key: (reads.append(key), blobs[key])[1],
        resolve_reference=lambda _parent, _raw: "circuits/dep.lib",
        identify_source=lambda _pk, _pid, _tk, _raw: "dep.lib",
        main_bytes=main,
    )

    assert reads == ["circuits/dep.lib"]
    assert graph.main_key == "circuits/main.cir"


@pytest.mark.parametrize("end_card", [".end", ".end ; done", ".end $ done"])
def test_main_physical_scan_ignores_include_after_structural_end(end_card: str):
    blobs = {
        "circuits/main.cir": (
            f"end boundary\n.op\n{end_card}\n.include missing.inc\n".encode()
        )
    }

    graph, reads = _memory_graph(blobs)

    assert graph.source_keys == ("circuits/main.cir",)
    assert reads == {"circuits/main.cir": 1}


def test_end_with_extra_token_is_not_treated_as_a_structural_terminator():
    blobs = {
        "circuits/main.cir": (
            b"malformed end\n.end extra\n.include dep.inc\n.op\n"
        ),
        "circuits/dep.inc": b".param x=1\n",
    }

    graph, reads = _memory_graph(blobs)

    assert reads == {key: 1 for key in blobs}
    assert graph.main_analysis_commands[0].analysis_type == "op"


def test_dependency_change_changes_effective_digest(tmp_path: Path):
    dependency = tmp_path / "model.lib"
    dependency.write_text(".param rload=1k\n", encoding="utf-8")
    main = tmp_path / "main.cir"
    main.write_text(
        'closure change\n.include "model.lib"\n.op\n.end\n',
        encoding="utf-8",
    )

    first = collect_spice_source_closure(main)
    dependency.write_text(".param rload=3k\n", encoding="utf-8")
    second = collect_spice_source_closure(main)

    assert first.digest != second.digest
    assert set(first.source_keys) == {str(main.resolve()), str(dependency.resolve())}


def test_snapshot_rewrites_recursive_include_and_lib_section_then_cleans_up(
    tmp_path: Path,
):
    nested = tmp_path / "nested.inc"
    nested.write_text(".param x=1\n", encoding="utf-8")
    library = tmp_path / "process.lib"
    library.write_text(
        '.lib TT\n.include "nested.inc"\n.endl TT\n',
        encoding="utf-8",
    )
    main = tmp_path / "main.cir"
    main.write_text(
        'mirror\n.lib "process.lib" TT\n.op\n.end\n',
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    snapshot_root = closure.snapshot_root
    with closure:
        assert snapshot_root.is_dir()
        assert str(tmp_path.resolve()).replace("\\", "/") not in closure.main_text
        assert ".lib " in closure.main_text
        assert closure.main_text.rstrip().splitlines()[1].endswith('" TT')
        mirrored_texts = [
            path.read_text(encoding="utf-8")
            for path in (snapshot_root / "sources").iterdir()
            if path.suffix in {".cir", ".lib", ".inc"}
        ]
        assert any(".include" in text for text in mirrored_texts)
        assert all(
            str(tmp_path.resolve()).replace("\\", "/") not in text
            for text in mirrored_texts
        )
    assert not snapshot_root.exists()


def test_snapshot_mirrors_include_from_unselected_library_section(tmp_path: Path):
    inactive = tmp_path / "inactive.inc"
    inactive.write_text(".model DUNUSED D\n", encoding="utf-8")
    library = tmp_path / "process.lib"
    library.write_text(
        ".lib TT\n.model DGOOD D\n.endl TT\n"
        ".lib FF\n.include inactive.inc\n.endl FF\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.cir"
    main.write_text(
        "physical include preprocessing\n.lib process.lib TT\n.op\n.end\n",
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        assert str(inactive.resolve()) in closure.graph.source_keys
        assert all(
            view.key != str(inactive.resolve())
            for view in closure.graph.active_views
        )
        mirrored_library = next(
            path
            for path in (closure.snapshot_root / "sources").iterdir()
            if path.name.endswith("_process.lib")
        )
        mirrored_text = mirrored_library.read_text(encoding="utf-8")
        include_line = next(
            line for line in mirrored_text.splitlines() if line.startswith(".include")
        )
        mirrored_target = Path(include_line.split('"', 2)[1])
        assert mirrored_target.is_file()
        assert mirrored_target.parent == mirrored_library.parent


def test_lib_selection_loads_inactive_include_but_excludes_inactive_semantics():
    blobs = {
        "circuits/main.cir": (
            b"selected corner\n.lib ../models/process.lib TT\n.op\n.end\n"
        ),
        "models/process.lib": (
            b".lib TT\n.model DGOOD D\n.endl TT\n"
            b".lib BROKEN\n.include inactive.inc\n.tran 1n 10n\n"
            b".control\nrun\n.endc\n.endl BROKEN\n"
        ),
        "models/inactive.inc": (
            b".include nested.inc\n.ac dec 10 1 1Meg\n"
            b".control\nrun\n.endc\n"
        ),
        "models/nested.inc": b".measure tran hidden MAX V(out)\n",
    }

    graph, reads = _memory_graph(blobs)

    assert reads == {key: 1 for key in blobs}
    assert graph.dependency_analysis_commands == ()
    assert graph.control_commands == ()
    dependency_views = [
        view for view in graph.active_views if view.source_id != "@main"
    ]
    assert len(dependency_views) == 1
    assert dependency_views[0].library_section == "tt"
    assert [line.text for line in dependency_views[0].lines] == [
        ".model DGOOD D"
    ]
    assert "models/inactive.inc" in graph.source_keys
    assert "models/nested.inc" in graph.source_keys


def test_inactive_lib_section_missing_include_fails_like_ngspice_preprocessor():
    blobs = {
        "circuits/main.cir": (
            b"selected corner\n.lib ../models/process.lib TT\n.op\n.end\n"
        ),
        "models/process.lib": (
            b".lib TT\n.model DGOOD D\n.endl TT\n"
            b".lib BROKEN\n.include missing.inc\n.endl BROKEN\n"
        ),
    }

    with pytest.raises(SpiceSourceClosureError, match="missing|读取|解析"):
        _memory_graph(blobs)


def test_library_physical_scan_does_not_stop_at_end_before_include():
    blobs = {
        "circuits/main.cir": (
            b"selected corner\n.lib ../models/process.lib TT\n.op\n.end\n"
        ),
        "models/process.lib": (
            b".lib TT\n.model DGOOD D\n.end\n"
            b".include missing.inc\n.endl TT\n"
        ),
    }

    with pytest.raises(SpiceSourceClosureError, match="missing|读取|解析"):
        _memory_graph(blobs)


def test_main_deck_inline_library_section_definition_fails_closed():
    blobs = {
        "circuits/main.cir": (
            b"unsupported inline library\n"
            b".lib hidden\n"
            b".tran 1n 10n\n"
            b".endl hidden\n"
            b".op\n.end\n"
        )
    }

    with pytest.raises(
        SpiceSourceClosureError,
        match=r"主网表不支持内联 \.lib section",
    ):
        _memory_graph(blobs)


def test_selected_lib_section_keeps_recursive_fail_closed_boundary():
    blobs = {
        "circuits/main.cir": (
            b"broken corner\n.lib ../models/process.lib BROKEN\n.op\n.end\n"
        ),
        "models/process.lib": (
            b".lib TT\n.model DGOOD D\n.endl TT\n"
            b".lib BROKEN\n.include missing.inc\n.endl BROKEN\n"
        ),
    }

    with pytest.raises(SpiceSourceClosureError, match="missing|读取|解析"):
        _memory_graph(blobs)


def test_same_library_two_selected_sections_create_two_active_views_but_one_read():
    blobs = {
        "circuits/main.cir": (
            b"two corners\n.lib ../models/process.lib TT\n"
            b".lib ../models/process.lib FF\n.op\n.end\n"
        ),
        "models/process.lib": (
            b".lib TT\n.param corner=1\n.endl TT\n"
            b".lib FF\n.param corner=2\n.endl FF\n"
        ),
    }

    graph, reads = _memory_graph(blobs)

    assert reads["models/process.lib"] == 1
    dependency_views = [
        view for view in graph.active_views if view.source_id != "@main"
    ]
    assert [view.library_section for view in dependency_views] == ["ff", "tt"]
    assert [
        [line.text for line in view.lines]
        for view in dependency_views
    ] == [[".param corner=2"], [".param corner=1"]]


def test_duplicate_active_include_fails_closed_instead_of_expanding_twice():
    blobs = {
        "circuits/main.cir": (
            b"duplicate\n.include dep.lib\n.include dep.lib\n.op\n.end\n"
        ),
        "circuits/dep.lib": b".param x=1\n",
    }

    with pytest.raises(
        SpiceSourceClosureError,
        match="重复 active SPICE source expansion",
    ):
        _memory_graph(blobs)


def test_same_active_include_reached_through_different_parents_fails_closed():
    blobs = {
        "circuits/main.cir": (
            b"duplicate routes\n.include left.inc\n.include right.inc\n.op\n.end\n"
        ),
        "circuits/left.inc": b".include shared.inc\n",
        "circuits/right.inc": b".include shared.inc\n",
        "circuits/shared.inc": b".measure tran peak MAX V(out)\n",
    }

    with pytest.raises(
        SpiceSourceClosureError,
        match="重复 active SPICE source expansion",
    ):
        _memory_graph(blobs)


def test_missing_dependency_and_cycle_fail_closed(tmp_path: Path):
    missing = tmp_path / "missing.cir"
    missing.write_text(
        "missing\n.include absent.lib\n.op\n.end\n",
        encoding="utf-8",
    )
    with pytest.raises(SpiceSourceClosureError, match="不存在|读取|解析"):
        collect_spice_source_closure(missing)

    first = tmp_path / "first.cir"
    second = tmp_path / "second.inc"
    first.write_text("cycle\n.include second.inc\n.op\n.end\n", encoding="utf-8")
    second.write_text(".include first.cir\n", encoding="utf-8")
    with pytest.raises(SpiceSourceClosureError, match="循环"):
        collect_spice_source_closure(first)


def test_malformed_reference_fails_instead_of_escaping_the_closure(tmp_path: Path):
    main = tmp_path / "malformed.cir"
    main.write_text(
        "malformed\n.include dep.lib unexpected\n.op\n.end\n",
        encoding="utf-8",
    )

    with pytest.raises(SpiceSourceClosureError, match="无法安全解析"):
        collect_spice_source_closure(main)


def test_dependency_analysis_cards_are_exposed_for_executor_rejection(tmp_path: Path):
    dependency = tmp_path / "analyses.inc"
    dependency.write_text(".tran 1n 10n\n", encoding="utf-8")
    main = tmp_path / "main.cir"
    main.write_text(
        "analysis boundary\n.include analyses.inc\n.ac lin 3 1 3\n.end\n",
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        assert closure.graph.dependency_analysis_commands == (
            ("analyses.inc", 1, ".tran 1n 10n"),
        )


def test_main_analysis_command_merges_physical_continuations_with_first_line_identity(
    tmp_path: Path,
):
    main = tmp_path / "continued.cir"
    main.write_text(
        "continued analysis\n"
        "V1 in 0 1\n"
        ".tran 10n\n"
        "+ {tend}\n"
        "+ 0\n"
        ".end\n",
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        commands = closure.graph.main_analysis_commands

    assert len(commands) == 1
    assert commands[0].source_id == "@main"
    assert commands[0].line_number == 3
    assert commands[0].analysis_type == "tran"
    assert commands[0].statement == ".tran 10n {tend} 0"


def test_dependency_analysis_continuation_retains_dependency_location(tmp_path: Path):
    dependency = tmp_path / "analysis.inc"
    dependency.write_text("* dependency\n.ac dec 10\n+ 1 1Meg\n", encoding="utf-8")
    main = tmp_path / "main.cir"
    main.write_text(
        "dependency continuation\n.include analysis.inc\n.op\n.end\n",
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        dependency_commands = closure.graph.dependency_analysis_commands

    assert dependency_commands == (("analysis.inc", 2, ".ac dec 10 1 1Meg"),)


def test_incpslt_is_decoded_and_scanned_instead_of_becoming_an_opaque_escape(
    tmp_path: Path,
):
    dependency = tmp_path / "pspice.inc"
    dependency.write_text(
        ".include nested.inc\n.ac lin 3 1 3\n",
        encoding="utf-8",
    )
    nested = tmp_path / "nested.inc"
    nested.write_text(".param gain=2\n", encoding="utf-8")
    main = tmp_path / "main.cir"
    main.write_text(
        "incpslt closure\n.incpslt pspice.inc\n.op\n.end\n",
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        assert set(closure.source_paths) == {
            str(main.resolve()),
            str(dependency.resolve()),
            str(nested.resolve()),
        }
        assert closure.graph.dependency_analysis_commands == (
            ("pspice.inc", 2, ".ac lin 3 1 3"),
        )


@pytest.mark.parametrize("statement", [".control", ".endc"])
def test_control_cards_are_recorded_with_stable_source_and_line(
    tmp_path: Path,
    statement: str,
):
    dependency = tmp_path / "script.lib"
    dependency.write_text(f"* dependency\n{statement}\n", encoding="utf-8")
    main = tmp_path / "main.cir"
    main.write_text(
        "control closure\n.include script.lib\n.op\n.end\n",
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        assert closure.graph.control_commands == (
            ("script.lib", 2, statement),
        )


def test_digest_manifest_never_contains_a_literal_absolute_source_id(tmp_path: Path):
    external = tmp_path / "external.lib"
    external.write_text(".param x=1\n", encoding="utf-8")
    main = tmp_path / "main.cir"
    main.write_text(
        f'absolute\n.include "{external.as_posix()}"\n.op\n.end\n',
        encoding="utf-8",
    )

    closure = snapshot_spice_source_closure(main)
    with closure:
        dependency_ids = [
            blob.source_id
            for blob in closure.graph.blobs
            if blob.key != closure.graph.main_key
        ]
        assert len(dependency_ids) == 1
        assert dependency_ids[0].startswith("absolute/")
        assert str(tmp_path).replace("\\", "/") not in dependency_ids[0]


def test_single_file_digest_is_manifest_digest_not_raw_file_hash(tmp_path: Path):
    main = tmp_path / "single.cir"
    raw = b"single\nV1 in 0 1\n.op\n.end\n"
    main.write_bytes(raw)

    identity = collect_spice_source_closure(main)

    assert identity.digest != hashlib.sha256(raw).hexdigest()
