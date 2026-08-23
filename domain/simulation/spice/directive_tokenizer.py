"""Pure structural tokenization for SPICE dot directives."""

from __future__ import annotations

from typing import Tuple


def tokenize_spice_directive(directive: str) -> Tuple[str, ...]:
    """Split one logical directive without evaluating SPICE expressions.

    Whitespace separates tokens only outside braces, parentheses, and quoted
    strings.  Top-level inline comments are discarded.  Malformed structural
    boundaries return an empty tuple so callers fail closed instead of using a
    misleading partial token sequence.
    """

    text = str(directive or "").strip()
    if not text:
        return ()

    tokens: list[str] = []
    current: list[str] = []
    brace_depth = 0
    paren_depth = 0
    quote = ""
    escaped = False
    index = 0

    while index < len(text):
        character = text[index]
        if quote:
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue

        if character in {"'", '"'}:
            quote = character
            current.append(character)
            index += 1
            continue
        if character == "{":
            brace_depth += 1
            current.append(character)
            index += 1
            continue
        if character == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return ()
            current.append(character)
            index += 1
            continue
        if character == "(":
            paren_depth += 1
            current.append(character)
            index += 1
            continue
        if character == ")":
            paren_depth -= 1
            if paren_depth < 0:
                return ()
            current.append(character)
            index += 1
            continue

        at_top_level = brace_depth == 0 and paren_depth == 0
        if at_top_level and (
            character in {";", "$"}
            or (character == "/" and text[index : index + 2] == "//")
        ):
            break
        if at_top_level and character.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            index += 1
            continue

        current.append(character)
        index += 1

    if quote or brace_depth != 0 or paren_depth != 0:
        return ()
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


def is_spice_end_directive(directive: str) -> bool:
    """Return whether one logical line is exactly ``.end`` plus comments."""

    tokens = tokenize_spice_directive(directive)
    return len(tokens) == 1 and tokens[0].casefold() == ".end"


__all__ = ["is_spice_end_directive", "tokenize_spice_directive"]
