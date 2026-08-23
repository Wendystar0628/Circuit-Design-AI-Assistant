import pytest

from domain.simulation.spice.directive_tokenizer import (
    is_spice_end_directive,
    tokenize_spice_directive,
)


def test_end_directive_accepts_only_inline_comments() -> None:
    assert is_spice_end_directive(".end") is True
    assert is_spice_end_directive("  .END ; complete") is True
    assert is_spice_end_directive(".end $ complete") is True
    assert is_spice_end_directive(".end // complete") is True
    assert is_spice_end_directive(".end unexpected") is False


def test_braced_expressions_with_spaces_remain_single_tokens():
    assert tokenize_spice_directive(
        ".dc V1 {vmin - 1} {vmax / 2} {step size}"
    ) == (
        ".dc",
        "V1",
        "{vmin - 1}",
        "{vmax / 2}",
        "{step size}",
    )


def test_quotes_parentheses_and_top_level_comments_have_structural_boundaries():
    assert tokenize_spice_directive(
        ".measure tran product FIND par('v(in) * v(out)') ; ignored"
    ) == (
        ".measure",
        "tran",
        "product",
        "FIND",
        "par('v(in) * v(out)')",
    )
    assert tokenize_spice_directive(
        '.include "models/my library.lib" // ignored'
    ) == (".include", '"models/my library.lib"')


def test_comment_markers_inside_expressions_and_quotes_are_preserved():
    assert tokenize_spice_directive(
        ".param expression={left // right} label='cost $ value'"
    ) == (
        ".param",
        "expression={left // right}",
        "label='cost $ value'",
    )


@pytest.mark.parametrize(
    "directive",
    [
        ".dc V1 {start stop step",
        ".dc V1 start} stop step",
        ".measure tran x FIND par(v(out)",
        ".include \"unterminated.lib",
    ],
)
def test_unbalanced_structure_fails_closed(directive: str):
    assert tokenize_spice_directive(directive) == ()
