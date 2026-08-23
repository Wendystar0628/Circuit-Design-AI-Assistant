"""Thread-safe in-process publish/subscribe event bus.

The event bus is application infrastructure, not a UI primitive. Publishers
may run on API, simulation, RAG, or file-worker threads, so handlers must be
small and thread-safe. UI and WebSocket adapters move work onto their own event
loop when required.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from shared.event_types import (
    CRITICAL_EVENTS,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
    EVENT_SIM_STARTED,
)


EventHandler = Callable[[Dict[str, Any]], None]
DEFAULT_THROTTLE_MS = 50
_ISOLATED_EVENT_TYPES = frozenset(
    {EVENT_SIM_STARTED, EVENT_SIM_COMPLETE, EVENT_SIM_ERROR}
)


class EventBus:
    """Synchronous event delivery with thread-safe latest-only throttling."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._lock = threading.RLock()
        self._logger = None
        self._debug = False
        self._throttle_buffer: Dict[str, Dict[str, Any]] = {}
        self._throttle_lock = threading.RLock()
        self._throttle_timer: Optional[threading.Timer] = None
        self._default_throttle_ms = DEFAULT_THROTTLE_MS
        self._stats = {
            "total_published": 0,
            "total_throttled": 0,
            "throttle_merged": 0,
        }

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger

                self._logger = get_logger("event_bus")
            except Exception:
                pass
        return self._logger

    def set_debug(self, enabled: bool) -> None:
        self._debug = bool(enabled)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if not event_type:
            raise ValueError("event_type is required")
        if not callable(handler):
            raise ValueError(f"Handler must be callable: {handler}")
        with self._lock:
            handlers = self._subscribers.setdefault(event_type, [])
            if handler not in handlers:
                handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        with self._lock:
            handlers = self._subscribers.get(event_type)
            if not handlers:
                return False
            try:
                handlers.remove(handler)
            except ValueError:
                return False
            if not handlers:
                self._subscribers.pop(event_type, None)
            return True

    def publish(
        self,
        event_type: str,
        data: Any = None,
        source: Optional[str] = None,
    ) -> None:
        event_data = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "source": source,
        }
        with self._lock:
            handlers = tuple(self._subscribers.get(event_type, ()))
            if handlers:
                self._stats["total_published"] += 1

        for handler in handlers:
            delivered = (
                copy.deepcopy(event_data)
                if event_type in _ISOLATED_EVENT_TYPES
                else event_data
            )
            self._execute_handler(handler, delivered, event_type)

    def publish_critical(
        self,
        event_type: str,
        data: Any = None,
        source: Optional[str] = None,
    ) -> bool:
        try:
            self.publish(event_type, data, source)
            return True
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    "Critical event '%s' publish failed, retrying: %s",
                    event_type,
                    exc,
                )
            try:
                self.publish(event_type, data, source)
                return True
            except Exception as retry_error:
                if self.logger:
                    self.logger.critical(
                        "Critical event '%s' failed after retry: %s",
                        event_type,
                        retry_error,
                    )
                return False

    def publish_throttled(
        self,
        event_type: str,
        data: Any = None,
        throttle_ms: Optional[int] = None,
        source: Optional[str] = None,
    ) -> None:
        interval_ms = self._default_throttle_ms if throttle_ms is None else throttle_ms
        if (
            isinstance(interval_ms, bool)
            or not isinstance(interval_ms, int)
            or interval_ms < 0
        ):
            raise ValueError("throttle_ms must be a non-negative integer")

        with self._throttle_lock:
            if event_type in self._throttle_buffer:
                buffered = self._throttle_buffer[event_type]
                buffered["data"] = data
                buffered["source"] = source
                self._stats["throttle_merged"] += 1
            else:
                self._throttle_buffer[event_type] = {
                    "data": data,
                    "source": source,
                }
                self._stats["total_throttled"] += 1

            timer = self._throttle_timer
            if timer is None or not timer.is_alive():
                timer = threading.Timer(
                    interval_ms / 1000.0,
                    self._flush_throttle_buffer,
                )
                timer.daemon = True
                self._throttle_timer = timer
                timer.start()

    def _flush_throttle_buffer(self) -> None:
        with self._throttle_lock:
            events = self._throttle_buffer
            self._throttle_buffer = {}
            self._throttle_timer = None
        for event_type, event_info in events.items():
            self.publish(
                event_type,
                event_info.get("data"),
                event_info.get("source"),
            )

    def stop_throttle_timer(self) -> None:
        with self._throttle_lock:
            timer = self._throttle_timer
            self._throttle_timer = None
            events = self._throttle_buffer
            self._throttle_buffer = {}
            if timer is not None:
                timer.cancel()
        for event_type, event_info in events.items():
            self.publish(
                event_type,
                event_info.get("data"),
                event_info.get("source"),
            )

    def clear_all(self) -> None:
        with self._throttle_lock:
            timer = self._throttle_timer
            self._throttle_timer = None
            self._throttle_buffer.clear()
            if timer is not None:
                timer.cancel()
        with self._lock:
            self._subscribers.clear()

    def get_subscriber_count(self, event_type: str) -> int:
        with self._lock:
            return len(self._subscribers.get(event_type, ()))

    def get_all_event_types(self) -> List[str]:
        with self._lock:
            return list(self._subscribers)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock, self._throttle_lock:
            return {
                "subscribers": {
                    event_type: len(handlers)
                    for event_type, handlers in self._subscribers.items()
                },
                **self._stats,
                "throttle_buffer_size": len(self._throttle_buffer),
            }

    def _execute_handler(
        self,
        handler: EventHandler,
        event_data: Dict[str, Any],
        event_type: str,
    ) -> None:
        started = time.monotonic()
        try:
            handler(event_data)
        except Exception as exc:
            handler_name = getattr(handler, "__name__", str(handler))
            if self.logger:
                self.logger.error(
                    "Handler '%s' failed for event '%s': %s",
                    handler_name,
                    event_type,
                    exc,
                )
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            if event_type in CRITICAL_EVENTS and duration_ms > 500 and self.logger:
                self.logger.warning(
                    "Handler '%s' for critical event '%s' took %.0fms",
                    getattr(handler, "__name__", str(handler)),
                    event_type,
                    duration_ms,
                )


__all__ = ["EventBus", "EventHandler"]
