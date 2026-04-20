from pathlib import Path

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


def _write_asc_file(tmp_path: Path, file_name: str, content: str) -> Path:
    path = tmp_path / file_name
    path.write_text(content, encoding="utf-8")
    return path


def test_transcriber_generates_runnable_netlist_for_common_opamp_sample(tmp_path: Path):
    asc_path = _write_asc_file(tmp_path, "amplifier.asc", AMPLIFIER_ASC)
    transcriber = LtspiceAscToCirTranscriber()

    result = transcriber.transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))

    assert ".title amplifier" in result.netlist_text.lower()
    assert "XU1" in result.netlist_text
    assert "CAI_COMPAT_OPAMP_5" in result.netlist_text
    assert " LT1001" not in result.netlist_text
    assert "R1 " in result.netlist_text
    assert ".tran 20ms" in result.netlist_text
    assert result.degraded is True
    assert result.validation_errors == ()


def test_transcriber_falls_back_to_generated_subckt_for_unknown_symbol(tmp_path: Path):
    asc_path = _write_asc_file(tmp_path, "unknown.asc", UNKNOWN_SYMBOL_ASC)
    transcriber = LtspiceAscToCirTranscriber()

    result = transcriber.transcribe_file(str(asc_path), output_dir=str(tmp_path / "cir"))

    assert "XU1" in result.netlist_text
    assert ".subckt" in result.netlist_text.lower()
    assert result.degraded is True
    assert result.validation_errors == ()
