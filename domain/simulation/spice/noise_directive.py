"""Strict structural parser for the native ngspice ``.noise`` directive."""

from __future__ import annotations

from dataclasses import dataclass

from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive


@dataclass(frozen=True)
class NoiseDirective:
    """The seven structural operands of one validated ``.noise`` card."""

    output_nodes: tuple[str, ...]
    input_source: str
    sweep_mode: str
    points: str
    start_frequency: str
    stop_frequency: str

    @property
    def output_expression(self) -> str:
        return f"V({','.join(self.output_nodes)})"

    @property
    def input_signal_type(self) -> str:
        return "voltage" if self.input_source[0].casefold() == "v" else "current"


def parse_noise_directive(directive: str) -> NoiseDirective:
    """Parse the exact ngspice ``.noise V(node[,ref]) SRC ...`` grammar.

    This parser is deliberately structural: numeric SPICE expressions remain
    the caller's responsibility.  It rejects current-output expressions,
    malformed differential-voltage operands, and non-independent input-source
    forms before native execution or persisted-result acceptance.
    """

    if not isinstance(directive, str) or any(
        character in directive for character in ("\x00", "\r", "\n")
    ):
        raise ValueError("NOISE directive must be one text line")
    tokens = tokenize_spice_directive(directive)
    if len(tokens) != 7 or tokens[0].casefold() != ".noise":
        raise ValueError(
            "NOISE directive must include output, input, sweep, points, start, and stop"
        )

    output_operand = tokens[1].strip()
    if not (
        len(output_operand) > 3
        and output_operand[0].casefold() == "v"
        and output_operand[1] == "("
        and output_operand.endswith(")")
    ):
        raise ValueError(
            "NOISE output operand must be V(node) or V(node,reference)"
        )
    output_nodes = tuple(
        node.strip() for node in output_operand[2:-1].split(",")
    )
    invalid_node_characters = set("(){}=;")
    if len(output_nodes) not in {1, 2} or any(
        not node
        or any(character.isspace() for character in node)
        or any(character in invalid_node_characters for character in node)
        for node in output_nodes
    ):
        raise ValueError(
            "NOISE output operand must contain one or two canonical node names"
        )

    input_source = tokens[2].strip()
    if not (
        len(input_source) > 1
        and input_source[0].casefold() in {"v", "i"}
        and not any(character.isspace() for character in input_source)
        and not any(character in input_source for character in "(){}=;,")
    ):
        raise ValueError(
            "NOISE input source must be an independent voltage or current source"
        )

    sweep_mode = tokens[3].casefold()
    if sweep_mode not in {"lin", "dec", "oct"}:
        raise ValueError("NOISE sweep mode must be LIN, DEC, or OCT")

    return NoiseDirective(
        output_nodes=output_nodes,
        input_source=input_source,
        sweep_mode=sweep_mode,
        points=tokens[4],
        start_frequency=tokens[5],
        stop_frequency=tokens[6],
    )


__all__ = ["NoiseDirective", "parse_noise_directive"]
