"""Authoritative payload accessor for the three simulation lifecycle events.

``EventBus.publish`` wraps every payload in a generic envelope shaped
like ``{"type": ..., "data": ..., "timestamp": ..., "source": ...}``.
For simulation lifecycle events we additionally contract that the
inner ``data`` dict **must** carry every identity field listed in
``SIM_PAYLOAD_FIELDS``. A missing field is a producer bug (the
``SimulationJobManager`` is the single publisher), not a subscriber
concern.

The purpose of this module is to prevent every subscriber from
reinventing envelope-unwrapping and missing-field handling. Every
simulation subscriber's handler must call
:func:`extract_sim_payload` **on its first line** — that is also the
compliance check the Step-5 rollout grep asserts against.

Design notes
------------

- This helper **raises** on missing fields rather than returning a
  sentinel or silently filling defaults. Handlers are free to catch
  :class:`MissingSimPayloadFieldError` and convert it into whatever
  telemetry they need, but they are not allowed to run their legacy
  "no result_path? scan the filesystem for the latest bundle"
  fallback — that path was deleted in Step 5.
- The required-field set is deliberately conservative: only the
  identity fields plus the one or two payload-specific fields that
  downstream routing actually depends on. Adding rarely-used fields
  to the required set would just push producers into defensive
  padding and dilute the contract; if a subscriber wants a field
  that isn't required, it may still read ``payload.get(...)``
  optimistically.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from shared.event_types import (
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)


# ---------------------------------------------------------------------------
# Contract table
# ---------------------------------------------------------------------------


# Identity fields common to all three simulation lifecycle events. The
# split between "common" and "per-event" exists only for readability —
# the effective required set per event is the union of both tuples.
_COMMON_IDENTITY_FIELDS: Tuple[str, ...] = (
    "job_id",
    "origin",
    "circuit_file",
    "project_root",
)


SIM_PAYLOAD_FIELDS: Dict[str, Tuple[str, ...]] = {
    EVENT_SIM_STARTED: _COMMON_IDENTITY_FIELDS + (
        "analysis_type",
    ),
    EVENT_SIM_COMPLETE: _COMMON_IDENTITY_FIELDS + (
        "result_path",
        "success",
        "duration_seconds",
    ),
    EVENT_SIM_ERROR: _COMMON_IDENTITY_FIELDS + (
        "error_message",
        "result_path",
        "cancelled",
        "duration_seconds",
    ),
}


SIM_LIFECYCLE_EVENT_TYPES: Tuple[str, ...] = tuple(SIM_PAYLOAD_FIELDS.keys())


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MissingSimPayloadFieldError(ValueError):
    """Raised when a simulation lifecycle event is missing required fields.

    This is always a *producer* bug — the job manager either forgot
    to fill a field, or something downstream mutated the payload
    before it reached subscribers. Treat it as loud and fatal rather
    than papering over it with defaults.
    """

    def __init__(self, event_type: str, missing: Tuple[str, ...], payload: Any):
        self.event_type = event_type
        self.missing = missing
        self.payload = payload
        super().__init__(
            f"Simulation event {event_type!r} payload is missing required "
            f"fields {list(missing)}. Payload was: {payload!r}"
        )


class InvalidSimEventEnvelopeError(ValueError):
    """Raised when the EventBus envelope itself is not shaped correctly.

    Separate from :class:`MissingSimPayloadFieldError` because the
    cause is different: somebody published with ``data=None`` or
    with a non-dict, which means the producer didn't follow the
    EventBus payload convention at all.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_sim_payload(
    event_type: str,
    event_data: Any,
) -> Mapping[str, Any]:
    """Unwrap the EventBus envelope and validate required identity fields.

    Parameters
    ----------
    event_type:
        One of :data:`EVENT_SIM_STARTED` / :data:`EVENT_SIM_COMPLETE`
        / :data:`EVENT_SIM_ERROR`. Passing any other event type is a
        programming error and raises ``KeyError`` — this helper is
        deliberately scoped to the three simulation lifecycle events,
        not a generic unwrapper.
    event_data:
        The object the EventBus handed to the handler. Should be
        the full envelope dict (with a ``"data"`` key) published by
        ``EventBus.publish``.

    Returns
    -------
    Mapping[str, Any]
        The inner ``data`` payload, guaranteed to contain every field
        listed in ``SIM_PAYLOAD_FIELDS[event_type]``.

    Raises
    ------
    KeyError
        If ``event_type`` is not one of the three simulation lifecycle
        events covered by this contract.
    InvalidSimEventEnvelopeError
        If ``event_data`` is not a mapping, or its ``data`` entry is
        not a mapping — i.e. the envelope shape is wrong.
    MissingSimPayloadFieldError
        If the payload is missing any required field.
    """
    required = SIM_PAYLOAD_FIELDS[event_type]

    if not isinstance(event_data, Mapping):
        raise InvalidSimEventEnvelopeError(
            f"Simulation event {event_type!r} handler received a "
            f"non-mapping envelope of type {type(event_data).__name__}: "
            f"{event_data!r}"
        )

    payload = event_data.get("data")
    if not isinstance(payload, Mapping):
        raise InvalidSimEventEnvelopeError(
            f"Simulation event {event_type!r} envelope carries a "
            f"non-mapping 'data' entry of type {type(payload).__name__}: "
            f"{event_data!r}"
        )

    missing = tuple(field for field in required if field not in payload)
    if missing:
        raise MissingSimPayloadFieldError(event_type, missing, payload)

    return payload


__all__ = [
    "SIM_LIFECYCLE_EVENT_TYPES",
    "SIM_PAYLOAD_FIELDS",
    "MissingSimPayloadFieldError",
    "InvalidSimEventEnvelopeError",
    "extract_sim_payload",
]
