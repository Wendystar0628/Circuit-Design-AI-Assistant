import math

from domain.simulation.spice.numeric import format_spice_number, is_spice_number, parse_spice_number


def test_ngspice_suffixes_distinguish_milli_from_mega() -> None:
    assert parse_spice_number("1M") == 1e-3
    assert parse_spice_number("1m") == 1e-3
    assert parse_spice_number("1Meg") == 1e6
    assert parse_spice_number("1MegHz") == 1e6
    assert parse_spice_number("10ms") == 10e-3


def test_ngspice_suffixes_cover_mil_atto_and_ignored_units() -> None:
    assert math.isclose(parse_spice_number("2mil"), 50.8e-6)
    assert math.isclose(parse_spice_number("3a"), 3e-18)
    assert parse_spice_number("12Volts") == 12.0
    assert is_spice_number("1e-3A") is True
    assert is_spice_number("{resistance}") is False


def test_formatter_emits_round_trip_safe_ngspice_numbers() -> None:
    for value in (0.0, -2.5e-3, 20e-6, 1e6, 4.7e-18, 3.2e12):
        rendered = format_spice_number(value)
        parsed = parse_spice_number(rendered)
        assert parsed is not None
        assert math.isclose(parsed, value, rel_tol=1e-11, abs_tol=1e-30)
