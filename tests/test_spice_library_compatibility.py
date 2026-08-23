from pathlib import Path

from domain.simulation.spice.runtime_compatibility import (
    analyze_spice_library_file,
)


def test_library_compatibility_rejects_ltspice_only_behavioral_tokens(
    tmp_path: Path,
) -> None:
    lib_path = tmp_path / "lt_only.lib"
    lib_path.write_text(
        ".subckt LT1001 1 2 3 4 5\n"
        "A1 0 0 0 0 0 0 0 0 OTA g=1\n"
        ".ends LT1001\n",
        encoding="utf-8",
    )

    compatibility = analyze_spice_library_file(lib_path)

    assert compatibility.is_compatible is False
    assert "lt1001" in compatibility.subckt_names
    assert "OTA" in compatibility.incompatible_reasons


def test_library_compatibility_is_recomputed_after_user_edits(
    tmp_path: Path,
) -> None:
    lib_path = tmp_path / "edited.lib"
    lib_path.write_text(
        "A1 0 0 0 0 0 0 0 0 OTA g=1\n",
        encoding="utf-8",
    )
    assert analyze_spice_library_file(lib_path).is_compatible is False

    lib_path.write_text(".model DGOOD D(Is=1e-14)\n", encoding="utf-8")

    refreshed = analyze_spice_library_file(lib_path)
    assert refreshed.is_compatible is True
    assert refreshed.model_names == ("dgood",)
