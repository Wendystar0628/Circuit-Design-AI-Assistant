from pathlib import Path

from application.session_state import SessionState
from application.session_state_projector import SessionStateProjector
from shared.event_types import (
    EVENT_RAG_INDEX_COMPLETE,
    EVENT_RAG_INDEX_PROGRESS,
    EVENT_RAG_INDEX_STARTED,
)


class _EventBus:
    def __init__(self) -> None:
        self.handlers = {}

    def subscribe(self, event_type, handler) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type, handler) -> bool:
        handlers = self.handlers.get(event_type, [])
        try:
            handlers.remove(handler)
            return True
        except ValueError:
            return False

    def publish(self, event_type, payload) -> None:
        envelope = {"type": event_type, "data": payload, "source": "test"}
        for handler in list(self.handlers.get(event_type, [])):
            handler(envelope)


def test_projector_keeps_only_project_and_rag_read_model(tmp_path: Path):
    state = SessionState()
    bus = _EventBus()
    projector = SessionStateProjector(state, bus)

    projector.update_project_state(str(tmp_path))
    assert state.get_all() == {
        "project_root": str(tmp_path),
        "rag_indexing": False,
        "rag_index_status": {},
    }

    assert projector.subscribe_rag_events()
    bus.publish(
        EVENT_RAG_INDEX_STARTED,
        {
            "project_root": str(tmp_path),
            "total_files": 4,
            "track_id": "idx-1",
        },
    )
    assert state.rag_indexing is True
    assert state.rag_index_status == {
        "status": "indexing",
        "total_files": 4,
        "processed": 0,
        "track_id": "idx-1",
    }

    bus.publish(
        EVENT_RAG_INDEX_COMPLETE,
        {
            "project_root": str(tmp_path),
            "total_indexed": 4,
            "failed": 0,
            "duration_s": 0.5,
        },
    )
    assert state.rag_indexing is False
    assert state.rag_index_status["status"] == "complete"

    projector.clear_project_state()
    assert state.get_all() == {
        "project_root": None,
        "rag_indexing": False,
        "rag_index_status": {},
    }


def test_projector_rejects_late_other_project_event_and_unsubscribes(
    tmp_path: Path,
):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    state = SessionState()
    bus = _EventBus()
    projector = SessionStateProjector(state, bus)
    projector.update_project_state(str(root_b))
    assert projector.subscribe_rag_events()

    bus.publish(
        EVENT_RAG_INDEX_PROGRESS,
        {
            "project_root": str(root_a),
            "processed": 9,
            "total": 10,
        },
    )
    assert state.rag_index_status == {}

    projector.shutdown()
    assert all(not handlers for handlers in bus.handlers.values())

    bus.publish(
        EVENT_RAG_INDEX_STARTED,
        {"project_root": str(root_b), "total_files": 1},
    )
    assert state.rag_indexing is False
