"""Compile experiment controls into a derived immutable source graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from domain.simulation.measure.measure_authority import parse_measure_statement
from domain.simulation.models.experiment import ExperimentSpec, validate_solver_options
from domain.simulation.spice.directive_tokenizer import tokenize_spice_directive, is_spice_end_directive
from domain.simulation.spice.source_closure import (
    SpiceSourceClosureGraph, SpiceSourceView, build_spice_source_closure,
)


@dataclass(frozen=True)
class _Card:
    key: str
    source_id: str
    is_main: bool
    line_numbers: tuple[int, ...]
    statement: str
    command: str


def _cards(views: Sequence[SpiceSourceView]) -> Iterable[_Card]:
    """Yield complete top-level logical cards from active library views only."""
    seen: set[tuple[str, int]] = set()
    for view in views:
        depth = 0
        index = 0
        while index < len(view.lines):
            line = view.lines[index]
            index += 1
            if view.is_main_deck and line.line_number == 1:
                continue
            statement = line.text.strip()
            numbers = [line.line_number]
            while index < len(view.lines) and view.lines[index].text.lstrip().startswith("+"):
                statement += " " + view.lines[index].text.lstrip()[1:].strip()
                numbers.append(view.lines[index].line_number)
                index += 1
            tokens = tokenize_spice_directive(statement)
            command = tokens[0].casefold() if tokens else ""
            if command == ".subckt":
                depth += 1
            elif command == ".ends":
                depth = max(0, depth - 1)
            elif command == ".end":
                break
            elif depth == 0 and (view.key, line.line_number) not in seen:
                seen.add((view.key, line.line_number))
                yield _Card(view.key, view.source_id, view.is_main_deck, tuple(numbers), statement, command)


def _assignments(statement: str) -> dict[str, str]:
    # Tokenizer keeps quoted/braced expressions together, including spaces.
    normalized = re.sub(r"\s*=\s*", "=", statement)
    tokens = tokenize_spice_directive(normalized)
    if len(tokens) < 2:
        raise ValueError(f"Expected name=value assignments: {statement}")
    values: dict[str, str] = {}
    for token in tokens[1:]:
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.+)", token)
        if match is None:
            raise ValueError(f"Expected name=value assignment, got {token!r}")
        name, value = match.groups()
        key = name.casefold()
        if key in values:
            raise ValueError(f"Duplicate assignment: {name}")
        values[key] = value
    return values


def source_solver_options(views: Sequence[SpiceSourceView]) -> dict[str, str]:
    options: dict[str, str] = {}
    for card in _cards(views):
        if card.command not in {".option", ".options"}:
            continue
        try:
            assignments = _assignments(card.statement)
            for key, value in assignments.items():
                if key in options and options[key].casefold() != value.casefold():
                    raise ValueError(f"Conflicting source solver option: {key}")
                options[key] = value
        except ValueError as exc:
            raise ValueError(f"{card.source_id}:{card.line_numbers[0]}: {exc}") from exc
    return validate_solver_options(options)


def compile_experiment_graph(
    graph: SpiceSourceClosureGraph, experiment: ExperimentSpec,
) -> tuple[SpiceSourceClosureGraph, str, list[dict]]:
    """Select analysis, replace main .param values and record filtered measures.

    With an explicit analysis, AC/DC/TRAN measures of other analysis types are
    omitted, including continuation lines. Malformed/unknown measures remain
    errors. Source files and the supplied graph are never mutated.
    """
    analyses = graph.main_analysis_commands
    explicit = bool(experiment.analysis_command)
    if explicit:
        analysis_command = experiment.analysis_command
    elif len(analyses) == 1:
        analysis_command = analyses[0].statement
    else:
        raise ValueError(
            "未指定 experiment.analysis_command 时，主网表必须且只能包含一张顶层 "
            f".ac、.dc、.tran、.noise 或 .op 分析卡；当前检测到 {len(analyses)} 张"
        )
    analysis = tokenize_spice_directive(analysis_command)[0].casefold()[1:]
    cards = tuple(_cards(graph.active_views))
    replacements: dict[tuple[str, int], str] = {}
    omitted: list[dict] = []
    found_parameters: dict[str, list[_Card]] = {}

    def replace(card: _Card, statement: str) -> None:
        replacements[(card.key, card.line_numbers[0])] = statement
        for number in card.line_numbers[1:]:
            replacements[(card.key, number)] = "* experiment: continuation replaced"

    for card in cards:
        if explicit and card.is_main and card.command in {".ac", ".dc", ".tran", ".noise", ".op"}:
            replace(card, "* experiment: analysis selected below")
        if explicit and card.command in {".measure", ".meas"}:
            parsed = parse_measure_statement(card.statement)
            if parsed and parsed.analysis_type in {"ac", "dc", "tran"} and parsed.analysis_type != analysis:
                replace(card, "* experiment: measurement belongs to another analysis")
                omitted.append({"source_id": card.source_id, "line_number": card.line_numbers[0],
                                "statement": card.statement, "reason": f"analysis {parsed.analysis_type} does not match {analysis}"})
        if experiment.temperature is not None and card.command == ".temp":
            replace(card, "* experiment: temperature selected below")
        if experiment.parameters and card.command == ".param":
            assignments = _assignments(card.statement)
            for name in experiment.parameters.keys() & assignments.keys():
                found_parameters.setdefault(name, []).append(card)
            overridden = {name: experiment.parameters.get(name, value) for name, value in assignments.items()}
            if card.is_main and overridden != assignments:
                replace(card, ".param " + " ".join(f"{name}={value}" for name, value in overridden.items()))

    for name in experiment.parameters:
        matches = found_parameters.get(name, [])
        if len(matches) != 1 or not matches[0].is_main:
            raise ValueError(
                f"Parameter {name!r} must have exactly one existing top-level .param declaration in the main deck; "
                "unknown, dependency-only, duplicate, and subcircuit-local parameters cannot be overridden"
            )

    # Validate all source controls, even when an experiment replaces a value:
    # an unknown option must never silently disappear.
    try:
        source_options = source_solver_options(graph.active_views)
    except ValueError as exc:
        raise ValueError(f".option/.options 无效: {exc}") from exc
    effective_options = validate_solver_options({**source_options, **experiment.solver_options})
    if experiment.solver_options:
        for card in cards:
            if card.command in {".option", ".options"}:
                replace(card, "* experiment: solver controls consolidated below")

    additions = []
    if explicit:
        additions.append(analysis_command)
    if experiment.temperature is not None:
        additions.append(f".temp {experiment.temperature:.17g}")
    if experiment.solver_options:
        additions.append(".options " + " ".join(f"{key}={value}" for key, value in effective_options.items()))
    if not replacements and not additions:
        return graph, analysis_command, omitted

    raw_by_key = {}
    for blob in graph.blobs:
        if not any(key == blob.key for key, _line in replacements) and (
            blob.key != graph.main_key or not additions
        ):
            raw_by_key[blob.key] = blob.raw_bytes
            continue
        lines = blob.source_text.splitlines()
        rewritten = []
        inserted = False
        for number, line in enumerate(lines, start=1):
            if blob.key == graph.main_key and number != 1 and not inserted and is_spice_end_directive(line):
                rewritten.extend(additions)
                inserted = True
            rewritten.append(replacements.get((blob.key, number), line))
        if blob.key == graph.main_key and additions and not inserted:
            # Leave missing .end a clear syntax failure; never repair the source implicitly.
            raise ValueError("网表缺少必需的 .end 结束指令")
        text = "\n".join(rewritten)
        if blob.source_text.endswith(("\n", "\r")):
            text += "\n"
        raw_by_key[blob.key] = text.encode("utf-8")
    references = {(reference.parent_key, reference.raw_path): reference.target_key for reference in graph.references}
    ids = {blob.key: blob.source_id for blob in graph.blobs}
    effective = build_spice_source_closure(
        graph.main_key, load_bytes=lambda key: raw_by_key[key],
        resolve_reference=lambda parent, path: references[(parent, path)],
        identify_source=lambda _parent, _parent_id, target, _path: ids[target],
    )
    return effective, analysis_command, omitted


__all__ = ["compile_experiment_graph", "source_solver_options"]
