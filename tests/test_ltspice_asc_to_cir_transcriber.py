from pathlib import Path

import pytest

from domain.simulation.spice.ltspice_asc_to_cir_transcriber import LtspiceAscToCirTranscriber


AMPLIFIER_ASC = """Version 4
SHEET 1 880 680
WIRE 400 -176 256 -176
WIRE 400 -144 400 -176
WIRE 256 -112 256 -176
WIRE 448 32 160 32
WIRE 608 32 528 32
WIRE 256 96 256 -32
WIRE -224 112 -352 112
WIRE 160 112 160 32
WIRE 160 112 -144 112
WIRE 224 112 160 112
WIRE 608 128 608 32
WIRE 608 128 288 128
WIRE 224 144 96 144
WIRE 96 208 96 144
WIRE -352 272 -352 112
WIRE 256 288 256 160
WIRE -352 384 -352 352
WIRE 256 400 256 368
FLAG 96 208 0
FLAG 256 400 0
FLAG 400 -144 0
FLAG -352 384 0
SYMBOL voltage 256 384 R180
WINDOW 0 24 96 Left 2
WINDOW 3 24 16 Left 2
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName V1
SYMATTR Value 12
SYMBOL voltage -352 256 R0
WINDOW 3 24 44 Left 2
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName V2
SYMATTR Value SINE(0 1 1k)
SYMBOL voltage 256 -16 R180
WINDOW 0 24 96 Left 2
WINDOW 3 24 16 Left 2
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName V3
SYMATTR Value 12
SYMBOL Opamps\\LT1001 256 64 R0
SYMATTR InstName U1
SYMBOL res -128 96 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName R1
SYMATTR Value 1k
SYMBOL res 544 16 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName Rf
SYMATTR Value 10k
TEXT -56 384 Left 2 !.tran 20ms
"""


UNKNOWN_SYMBOL_ASC = """Version 4
SHEET 1 880 680
WIRE -96 16 -32 16
WIRE 32 16 96 16
FLAG -96 16 IN
FLAG 96 16 OUT
SYMBOL Exotic\\Foo 0 0 R0
SYMATTR InstName U1
TEXT 0 128 Left 2 !.op
"""


MISQUALIFIED_KNOWN_SYMBOL_ASC = """Version 4
SHEET 1 880 680
SYMBOL Exotic\\res 0 0 R0
SYMATTR InstName R1
SYMATTR Value 1k
TEXT 0 128 Left 2 !.op
"""


MOS_DIFFERENTIAL_ASC = """Version 4
SHEET 1 880 680
WIRE 0 0 64 0
WIRE 128 0 192 0
WIRE 0 64 64 64
WIRE 128 64 192 64
FLAG 0 0 ND
FLAG 64 0 NG
FLAG 192 0 NS
FLAG 0 64 ND2
FLAG 64 64 NG2
FLAG 192 64 NS2
SYMBOL nmos 96 0 R0
SYMATTR InstName M1
SYMATTR Value 2N7002
SYMBOL nmos 96 64 R0
SYMATTR InstName M2
SYMATTR Value 2N7002
TEXT 0 144 Left 2 !.model 2N7002 VDMOS(Vto=2 Kp=1)
TEXT 0 160 Left 2 !.tran 20m
"""


def _write_asc_file(tmp_path: Path, file_name: str, content: str) -> Path:
    path = tmp_path / file_name
    path.write_text(content, encoding="utf-8")
    return path


def test_transcriber_rejects_incompatible_ltspice_opamp_instead_of_substituting_a_fake(tmp_path: Path):
    asc_path = _write_asc_file(tmp_path, "amplifier.asc", AMPLIFIER_ASC)
    transcriber = LtspiceAscToCirTranscriber()

    with pytest.raises(ValueError, match="LT1001"):
        transcriber.transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))


def test_transcriber_rejects_unknown_symbol_instead_of_guessing_nearby_wire_pins(tmp_path: Path):
    asc_path = _write_asc_file(tmp_path, "unknown.asc", UNKNOWN_SYMBOL_ASC)
    transcriber = LtspiceAscToCirTranscriber()

    with pytest.raises(ValueError, match=r"\.asy"):
        transcriber.transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))


def test_transcriber_does_not_fall_back_from_wrong_symbol_path_to_known_basename(tmp_path: Path):
    asc_path = _write_asc_file(tmp_path, "misqualified.asc", MISQUALIFIED_KNOWN_SYMBOL_ASC)

    with pytest.raises(ValueError, match=r"\.asy"):
        LtspiceAscToCirTranscriber().transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))


def test_transcriber_preserves_ngspice_native_three_terminal_vdmos_form(tmp_path: Path):
    asc_path = _write_asc_file(tmp_path, "mos_diff.asc", MOS_DIFFERENTIAL_ASC)
    transcriber = LtspiceAscToCirTranscriber()

    result = transcriber.transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))

    mos_lines = [line for line in result.netlist_text.splitlines() if line.startswith(("M1 ", "M2 "))]
    assert len(mos_lines) == 2
    for line in mos_lines:
        pieces = line.split()
        assert len(pieces) == 5
        assert pieces[4] == "2N7002"
    assert not any("body=source" in warning for warning in result.warnings)
    assert ".tran 20u 20m" in result.netlist_text
    assert result.degraded is False
    assert result.validation_errors == ()


def test_transcriber_rejects_catalog_name_without_explicit_model_definition(
    tmp_path: Path,
) -> None:
    asc_path = _write_asc_file(
        tmp_path,
        "undeclared_model.asc",
        MOS_DIFFERENTIAL_ASC.replace(
            "TEXT 0 144 Left 2 !.model 2N7002 VDMOS(Vto=2 Kp=1)\n",
            "",
        ),
    )

    with pytest.raises(ValueError, match="2N7002"):
        LtspiceAscToCirTranscriber().transcribe_file(
            str(asc_path),
            output_dir=str(tmp_path / "cir"),
        )


def test_transcriber_ties_body_to_source_only_for_three_pin_standard_mos(tmp_path: Path):
    asc_path = _write_asc_file(
        tmp_path,
        "standard_mos.asc",
        MOS_DIFFERENTIAL_ASC.replace("2N7002", "TEST_NMOS").replace(
            ".model TEST_NMOS VDMOS(Vto=2 Kp=1)",
            ".model TEST_NMOS NMOS(Vto=2 Kp=1)",
        ),
    )

    result = LtspiceAscToCirTranscriber().transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))

    for line in [line for line in result.netlist_text.splitlines() if line.startswith(("M1 ", "M2 "))]:
        pieces = line.split()
        assert len(pieces) == 6
        assert pieces[4] == pieces[3]
        assert pieces[5] == "TEST_NMOS"
    assert any("body=source" in warning for warning in result.warnings)


def test_transcriber_preserves_ngspice_param_expression_analysis(tmp_path: Path) -> None:
    asc_path = _write_asc_file(
        tmp_path,
        "param_tran.asc",
        MOS_DIFFERENTIAL_ASC.replace(
            "TEXT 0 160 Left 2 !.tran 20m",
            "TEXT 0 152 Left 2 !.param tend=1u\nTEXT 0 160 Left 2 !.tran 10n {tend}",
        ),
    )

    result = LtspiceAscToCirTranscriber().transcribe_file(
        str(asc_path),
        output_dir=str(tmp_path / "cir"),
    )

    assert ".param tend=1u" in result.netlist_text
    assert ".tran 10n {tend}" in result.netlist_text


def test_transcriber_preserves_embedded_subcircuit_directive_order(tmp_path: Path):
    asc_path = _write_asc_file(
        tmp_path,
        "inline_subckt.asc",
        """Version 4
SHEET 1 880 680
TEXT 0 0 Left 2 !.subckt AUX a b
TEXT 0 16 Left 2 !Rinside a b 1k
TEXT 0 32 Left 2 !.ends AUX
TEXT 0 48 Left 2 !X1 in out AUX
TEXT 0 64 Left 2 !.op
""",
    )

    result = LtspiceAscToCirTranscriber().transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))

    lines = result.netlist_text.splitlines()
    assert lines.index(".subckt AUX a b") < lines.index("Rinside a b 1k") < lines.index(".ends AUX")
    assert result.validation_errors == ()
