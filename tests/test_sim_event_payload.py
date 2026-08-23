from __future__ import annotations

from collections.abc import Mapping

import pytest

from shared.event_types import EVENT_SIM_COMPLETE, EVENT_SIM_ERROR, EVENT_SIM_STARTED
from shared.event_bus import EventBus
from shared.sim_event_payload import (
    InvalidSimEventEnvelopeError,
    InvalidSimPayloadError,
    MissingSimPayloadFieldError,
    SIM_LIFECYCLE_EVENT_TYPES,
    SIM_PAYLOAD_FIELDS,
    extract_sim_payload,
    validate_sim_payload,
)


def _identity(tmp_path):
    return {
        "job_id": "job_0123456789abcdef",
        "origin": "ui_editor",
        "circuit_file": str(tmp_path / "amp.cir"),
        "project_root": str(tmp_path),
        "session_id": "session-1",
    }


def _payload(tmp_path, event_type):
    identity = _identity(tmp_path)
    result_path = "simulation_results/amp/run/result.json"
    export_root = str(tmp_path / "simulation_results" / "amp" / "run")
    if event_type == EVENT_SIM_STARTED:
        return identity
    if event_type == EVENT_SIM_COMPLETE:
        return {
            **identity,
            "result_path": result_path,
            "export_root": export_root,
            "duration_seconds": 0.25,
        }
    return {
        **identity,
        "error_message": "ngspice failed",
        "result_path": result_path,
        "export_root": export_root,
        "cancelled": False,
        "duration_seconds": 0.25,
    }


def _envelope(event_type, payload):
    return {"type": event_type, "data": payload, "timestamp": 0.0, "source": "test"}


def test_contract_has_only_the_three_real_lifecycle_events():
    assert SIM_LIFECYCLE_EVENT_TYPES == (
        EVENT_SIM_STARTED,
        EVENT_SIM_COMPLETE,
        EVENT_SIM_ERROR,
    )
    assert set(SIM_PAYLOAD_FIELDS) == set(SIM_LIFECYCLE_EVENT_TYPES)


@pytest.mark.parametrize("event_type", SIM_LIFECYCLE_EVENT_TYPES)
def test_extract_validates_and_returns_isolated_read_only_payload(tmp_path, event_type):
    source = _payload(tmp_path, event_type)
    extracted = extract_sim_payload(event_type, _envelope(event_type, source))
    assert isinstance(extracted, Mapping)
    assert extracted == source
    assert extracted is not source
    with pytest.raises(TypeError):
        extracted["job_id"] = "corrupt"  # type: ignore[index]

def test_event_bus_isolates_simulation_payload_between_subscribers(tmp_path):
    bus = EventBus()
    observed = []

    def corrupt_first(envelope):
        envelope["data"]["session_id"] = "corrupt"

    def observe_second(envelope):
        observed.append(envelope["data"]["session_id"])

    bus.subscribe(EVENT_SIM_STARTED, corrupt_first)
    bus.subscribe(EVENT_SIM_STARTED, observe_second)
    bus.publish(
        EVENT_SIM_STARTED,
        _payload(tmp_path, EVENT_SIM_STARTED),
        source="test",
    )

    assert observed == ["session-1"]


@pytest.mark.parametrize("retired_field", ["analysis_type", "config"])
def test_started_rejects_retired_analysis_config_fields(tmp_path, retired_field):
    payload = _payload(tmp_path, EVENT_SIM_STARTED)
    payload[retired_field] = "tran" if retired_field == "analysis_type" else {}

    with pytest.raises(InvalidSimPayloadError, match="unexpected"):
        validate_sim_payload(EVENT_SIM_STARTED, payload)


def test_missing_and_extra_fields_are_rejected(tmp_path):
    missing = _payload(tmp_path, EVENT_SIM_COMPLETE)
    missing.pop("export_root")
    with pytest.raises(MissingSimPayloadFieldError) as info:
        validate_sim_payload(EVENT_SIM_COMPLETE, missing)
    assert info.value.missing == ("export_root",)

    extra = _payload(tmp_path, EVENT_SIM_COMPLETE)
    extra["success"] = True
    with pytest.raises(InvalidSimPayloadError, match="unexpected"):
        validate_sim_payload(EVENT_SIM_COMPLETE, extra)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_id", ""),
        ("job_id", "random"),
        ("origin", "legacy"),
        ("circuit_file", "relative.cir"),
        ("project_root", "relative/project"),
        ("session_id", None),
    ],
)
def test_identity_fields_require_canonical_types_and_values(tmp_path, field, value):
    payload = _payload(tmp_path, EVENT_SIM_STARTED)
    payload[field] = value
    with pytest.raises(InvalidSimPayloadError):
        validate_sim_payload(EVENT_SIM_STARTED, payload)


def test_circuit_identity_must_belong_to_event_project(tmp_path):
    payload = _payload(tmp_path, EVENT_SIM_STARTED)
    payload["circuit_file"] = str(tmp_path.parent / "other" / "amp.cir")
    with pytest.raises(InvalidSimPayloadError, match="inside project_root"):
        validate_sim_payload(EVENT_SIM_STARTED, payload)


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan"), "1"])
def test_duration_must_be_finite_nonnegative_number(tmp_path, value):
    payload = _payload(tmp_path, EVENT_SIM_COMPLETE)
    payload["duration_seconds"] = value
    with pytest.raises(InvalidSimPayloadError, match="duration_seconds"):
        validate_sim_payload(EVENT_SIM_COMPLETE, payload)


def test_complete_requires_matching_canonical_bundle_paths(tmp_path):
    payload = _payload(tmp_path, EVENT_SIM_COMPLETE)
    payload["result_path"] = "../outside/result.json"
    with pytest.raises(InvalidSimPayloadError, match="result_path"):
        validate_sim_payload(EVENT_SIM_COMPLETE, payload)

    for invalid in (
        "simulation_results/amp/result.json",
        "simulation_results/bad:bundle/run/result.json",
        "simulation_results/amp/.__bundle_tmp__/result.json",
    ):
        payload = _payload(tmp_path, EVENT_SIM_COMPLETE)
        payload["result_path"] = invalid
        with pytest.raises(InvalidSimPayloadError, match="result_path"):
            validate_sim_payload(EVENT_SIM_COMPLETE, payload)

    payload = _payload(tmp_path, EVENT_SIM_COMPLETE)
    payload["export_root"] = str(tmp_path / "wrong")
    with pytest.raises(InvalidSimPayloadError, match="export_root"):
        validate_sim_payload(EVENT_SIM_COMPLETE, payload)

    payload = _payload(tmp_path, EVENT_SIM_COMPLETE)
    payload["result_path"] = payload["export_root"] = ""
    with pytest.raises(InvalidSimPayloadError, match="require a bundle"):
        validate_sim_payload(EVENT_SIM_COMPLETE, payload)


def test_error_allows_no_bundle_only_when_both_paths_are_empty(tmp_path):
    payload = _payload(tmp_path, EVENT_SIM_ERROR)
    payload["result_path"] = payload["export_root"] = ""
    assert validate_sim_payload(EVENT_SIM_ERROR, payload)

    payload["export_root"] = str(tmp_path / "somewhere")
    with pytest.raises(InvalidSimPayloadError, match="both"):
        validate_sim_payload(EVENT_SIM_ERROR, payload)


def test_error_requires_nonempty_message_and_real_bool(tmp_path):
    payload = _payload(tmp_path, EVENT_SIM_ERROR)
    payload["error_message"] = ""
    with pytest.raises(InvalidSimPayloadError, match="error_message"):
        validate_sim_payload(EVENT_SIM_ERROR, payload)
    payload = _payload(tmp_path, EVENT_SIM_ERROR)
    payload["cancelled"] = 0
    with pytest.raises(InvalidSimPayloadError, match="cancelled"):
        validate_sim_payload(EVENT_SIM_ERROR, payload)


def test_envelope_must_match_handler_event_type(tmp_path):
    payload = _payload(tmp_path, EVENT_SIM_STARTED)
    with pytest.raises(InvalidSimEventEnvelopeError, match="does not match"):
        extract_sim_payload(
            EVENT_SIM_STARTED,
            _envelope(EVENT_SIM_COMPLETE, payload),
        )
    with pytest.raises(InvalidSimEventEnvelopeError):
        extract_sim_payload(EVENT_SIM_STARTED, {"type": EVENT_SIM_STARTED})
    with pytest.raises(InvalidSimEventEnvelopeError):
        extract_sim_payload(EVENT_SIM_STARTED, "bad")


def test_unknown_event_type_is_a_programming_error(tmp_path):
    with pytest.raises(KeyError):
        extract_sim_payload("sim_paused", _envelope("sim_paused", {}))
