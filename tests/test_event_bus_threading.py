from __future__ import annotations

import threading

from shared.event_bus import EventBus


def test_worker_publish_is_synchronous_and_isolates_handler_failures() -> None:
    event_bus = EventBus()
    delivered = []
    worker_identity = []

    def failing_handler(_event) -> None:
        raise RuntimeError("expected handler failure")

    def recording_handler(event) -> None:
        delivered.append(event)
        worker_identity.append(threading.get_ident())

    event_bus.subscribe("worker.event", failing_handler)
    event_bus.subscribe("worker.event", recording_handler)

    publisher_identity = []

    def publish() -> None:
        publisher_identity.append(threading.get_ident())
        event_bus.publish("worker.event", {"value": 1}, source="worker")

    worker = threading.Thread(target=publish)
    worker.start()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert delivered[0]["data"] == {"value": 1}
    assert worker_identity == publisher_identity


def test_throttle_uses_latest_payload_and_threading_timer() -> None:
    event_bus = EventBus()
    delivered = []
    delivery_complete = threading.Event()

    def record(event) -> None:
        delivered.append(event)
        delivery_complete.set()

    event_bus.subscribe("throttled.event", record)
    event_bus.publish_throttled("throttled.event", 1, throttle_ms=10)
    event_bus.publish_throttled("throttled.event", 2, throttle_ms=10)

    assert delivery_complete.wait(timeout=1.0)
    assert [event["data"] for event in delivered] == [2]
