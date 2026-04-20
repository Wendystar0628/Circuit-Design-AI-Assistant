from domain.simulation.spice.analysis_directive_authority import (
    detect_last_analysis_type_from_text,
    extract_last_analysis_command,
    normalize_analysis_directive,
    replace_or_inject_analysis_command,
)


def test_normalize_transient_single_stop_token_to_explicit_step_and_stop() -> None:
    assert normalize_analysis_directive(".tran 20ms") == ".tran 20u 20ms"
    assert normalize_analysis_directive(".tran 20m") == ".tran 20u 20m"



def test_normalize_transient_single_stop_token_preserves_uic() -> None:
    assert normalize_analysis_directive(".tran 20ms uic") == ".tran 20u 20ms uic"



def test_extract_and_replace_canonicalize_legacy_transient_directive() -> None:
    netlist = ".title demo\nR1 out 0 1k\n.tran 20ms\n.end\n"

    assert detect_last_analysis_type_from_text(netlist) == "tran"
    assert extract_last_analysis_command(netlist, "tran") == ".tran 20u 20ms"

    rewritten = replace_or_inject_analysis_command(netlist, ".tran 20ms")
    assert ".tran 20u 20ms" in rewritten
    assert ".tran 20ms\n" not in rewritten
