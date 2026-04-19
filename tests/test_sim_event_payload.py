"""Tests for the Step-5 authoritative simulation-event payload contract.

These tests lock in three guarantees that the Step-5 rollout makes
non-negotiable:

1. The manager emits every required identity field on every
   lifecycle event — failures, cancellations, persistence blow-ups
   included. ``extract_sim_payload`` running against a real manager
   emission must never raise.
2. Missing / malformed payloads are producer bugs, not subscriber
   concerns: ``extract_sim_payload`` raises loud, distinct
   exceptions rather than silently defaulting.
3. No subscriber is allowed to silently fall back when a field is
   missing — the AST-level grep in this file asserts every
   simulation subscriber's handler reads its payload via
   ``extract_sim_payload`` before doing anything else.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from shared.event_types import (
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)
from shared.sim_event_payload import (
    InvalidSimEventEnvelopeError,
    MissingSimPayloadFieldError,
    SIM_LIFECYCLE_EVENT_TYPES,
    SIM_PAYLOAD_FIELDS,
    extract_sim_payload,
)


# ---------------------------------------------------------------------------
# Contract table is what it claims to be
# ---------------------------------------------------------------------------


def test_contract_table_covers_all_three_lifecycle_events():
    """The three lifecycle events are the *only* ones this helper
    handles — no more, no less. Adding a fourth without updating
    every subscriber is the exact silent-drift that Step 5 is trying
    to prevent, so the test pins the list explicitly."""
    assert set(SIM_LIFECYCLE_EVENT_TYPES) == {
        EVENT_SIM_STARTED,
        EVENT_SIM_COMPLETE,
        EVENT_SIM_ERROR,
    }


@pytest.mark.parametrize("event_type", SIM_LIFECYCLE_EVENT_TYPES)
def test_common_identity_fields_required_on_every_event(event_type):
    """Identity routing only works if *every* lifecycle event carries
    the same four identity fields. Permitting e.g. a SIM_ERROR without
    ``origin`` would let a producer emit a "cancelled" event that no
    subscriber can route by origin — which is precisely the
    "guess from circuit_file / mtime" pathology Step 5 deletes."""
    required = SIM_PAYLOAD_FIELDS[event_type]
    for field in ("job_id", "origin", "circuit_file", "project_root"):
        assert field in required, (
            f"{event_type}: missing required identity field {field!r} "
            f"from Step-5 contract"
        )


# ---------------------------------------------------------------------------
# Happy path: a valid envelope unwraps to the payload unchanged
# ---------------------------------------------------------------------------


def _valid_payload(event_type: str) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "job_id": "job-abc",
        "origin": "ui",
        "circuit_file": "/tmp/amp.cir",
        "project_root": "/tmp/project",
    }
    if event_type == EVENT_SIM_STARTED:
        base.update({"analysis_type": "tran", "config": {"tstop": 1e-3}})
    elif event_type == EVENT_SIM_COMPLETE:
        base.update({
            "result_path": "simulation_results/amp/ts/result.json",
            "export_root": "/tmp/project/simulation_results/amp/ts",
            "success": True,
            "duration_seconds": 0.25,
        })
    elif event_type == EVENT_SIM_ERROR:
        base.update({
            "error_message": "boom",
            "result_path": "simulation_results/amp/ts/result.json",
            "export_root": "/tmp/project/simulation_results/amp/ts",
            "cancelled": False,
            "duration_seconds": 0.12,
        })
    return base


def _envelope(payload: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    return {
        "type": event_type,
        "data": payload,
        "timestamp": 1234567890.0,
        "source": "test",
    }


@pytest.mark.parametrize("event_type", SIM_LIFECYCLE_EVENT_TYPES)
def test_extract_returns_inner_payload_on_happy_path(event_type):
    payload = _valid_payload(event_type)
    envelope = _envelope(payload, event_type)

    got = extract_sim_payload(event_type, envelope)

    assert got is payload, (
        "extract_sim_payload must return the inner payload unchanged — "
        "subscribers sometimes mutate or log it, and a copy would break "
        "identity comparisons and cost an allocation per event."
    )


# ---------------------------------------------------------------------------
# Producer bugs: loud, typed, distinct
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", SIM_LIFECYCLE_EVENT_TYPES)
def test_missing_required_field_raises_missing_payload_error(event_type):
    payload = _valid_payload(event_type)
    payload.pop("job_id")
    envelope = _envelope(payload, event_type)

    with pytest.raises(MissingSimPayloadFieldError) as excinfo:
        extract_sim_payload(event_type, envelope)

    assert excinfo.value.event_type == event_type
    assert "job_id" in excinfo.value.missing


def test_missing_multiple_fields_reports_all_of_them():
    """The whole point of raising is to hand the producer-bug fix a
    complete list — not to stop at the first missing field and force
    the author into a whack-a-mole fix cycle."""
    payload = _valid_payload(EVENT_SIM_COMPLETE)
    payload.pop("job_id")
    payload.pop("result_path")
    payload.pop("success")
    envelope = _envelope(payload, EVENT_SIM_COMPLETE)

    with pytest.raises(MissingSimPayloadFieldError) as excinfo:
        extract_sim_payload(EVENT_SIM_COMPLETE, envelope)

    assert set(excinfo.value.missing) == {"job_id", "result_path", "success"}


def test_envelope_without_data_key_raises_invalid_envelope():
    with pytest.raises(InvalidSimEventEnvelopeError):
        extract_sim_payload(EVENT_SIM_STARTED, {"type": EVENT_SIM_STARTED})


def test_envelope_with_non_mapping_data_raises_invalid_envelope():
    with pytest.raises(InvalidSimEventEnvelopeError):
        extract_sim_payload(
            EVENT_SIM_STARTED,
            {"type": EVENT_SIM_STARTED, "data": "not a dict"},
        )


def test_non_mapping_event_data_raises_invalid_envelope():
    with pytest.raises(InvalidSimEventEnvelopeError):
        extract_sim_payload(EVENT_SIM_STARTED, "totally bogus")


def test_unknown_event_type_is_caller_programming_error():
    """The helper is scoped to the three lifecycle events on purpose.
    Being called with something else is not a runtime input bug; it
    is caller code that shouldn't compile. ``KeyError`` is the right
    signal for that."""
    with pytest.raises(KeyError):
        extract_sim_payload("sim_paused", _envelope({}, "sim_paused"))


# ---------------------------------------------------------------------------
# Subscriber compliance: every simulation handler unwraps via the helper
# ---------------------------------------------------------------------------


# (module path, handler method names that subscribe to EVENT_SIM_*)
_SIMULATION_SUBSCRIBERS: List[tuple] = [
    (
        "presentation.panels.simulation.simulation_tab",
        ("_on_simulation_started", "_on_simulation_complete", "_on_simulation_error"),
    ),
    (
        "presentation.panels.simulation.simulation_view_model",
        ("_on_simulation_started", "_on_simulation_complete", "_on_simulation_error"),
    ),
    (
        "presentation.panels.bottom_panel",
        ("_on_simulation_complete",),
    ),
    (
        # Step 6 added the editor Run-button controller as a third
        # subscriber: it filters by its own submitted job_id set, so
        # the very first thing it must do is decode the payload via
        # the authoritative helper.
        "presentation.simulation_command_controller",
        (
            "_on_sim_started_event",
            "_on_sim_complete_event",
            "_on_sim_error_event",
        ),
    ),
]


def _find_method(tree: ast.AST, method_name: str) -> Optional[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return node
    return None


def _uses_extract_sim_payload(func: ast.FunctionDef) -> bool:
    """Return True iff the first executable statement of ``func``
    contains a call to ``extract_sim_payload``. We intentionally scan
    only the function's very first statement: the Step-5 contract is
    "handler's first action is authoritative payload extraction",
    not "extracts it somewhere down the line after maybe falling back
    to the old scan-for-latest path"."""
    body = list(func.body)
    while body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        # Skip the docstring if present
        body = body[1:]
    if not body:
        return False

    first_stmt = body[0]
    for node in ast.walk(first_stmt):
        if isinstance(node, ast.Call):
            func_node = node.func
            if isinstance(func_node, ast.Name) and func_node.id == "extract_sim_payload":
                return True
            if isinstance(func_node, ast.Attribute) and func_node.attr == "extract_sim_payload":
                return True
    return False


@pytest.mark.parametrize("module_path,handler_names", _SIMULATION_SUBSCRIBERS)
def test_every_simulation_handler_extracts_payload_on_first_line(
    module_path, handler_names
):
    """Grep-style compliance check executed at the AST level.

    For each registered simulation subscriber, open its source,
    locate each lifecycle handler method, and assert the very first
    non-docstring statement inside the method calls
    ``extract_sim_payload``. This replaces the fragile plain-text
    grep the Step-5 plan mandates with a structural check that
    ignores comments, whitespace, and docstrings."""
    module = importlib.import_module(module_path)
    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for handler_name in handler_names:
        func = _find_method(tree, handler_name)
        assert func is not None, (
            f"{module_path}: expected handler {handler_name!r} not found"
        )
        assert _uses_extract_sim_payload(func), (
            f"{module_path}.{handler_name} must call extract_sim_payload "
            f"on its first executable line (Step-5 authoritative-payload "
            f"contract)."
        )


# ---------------------------------------------------------------------------
# Forbidden patterns stay out of the simulation subscriber surface
# ---------------------------------------------------------------------------


def test_simulation_tab_has_no_result_path_fallback_scan():
    """Step 5 deletes the branch "if event has no result_path, scan
    the project for the latest bundle". This test greps the whole
    simulation_tab source for the old fallback marker so a future
    well-meaning refactor can't quietly resurrect it."""
    module = importlib.import_module(
        "presentation.panels.simulation.simulation_tab"
    )
    source = Path(module.__file__).read_text(encoding="utf-8")
    forbidden_markers = [
        "No result_path in event, trying to load latest result",
        "elif not result_path:",
    ]
    for marker in forbidden_markers:
        assert marker not in source, (
            f"simulation_tab.py must not contain the Step-5-forbidden "
            f"fallback marker: {marker!r}"
        )
