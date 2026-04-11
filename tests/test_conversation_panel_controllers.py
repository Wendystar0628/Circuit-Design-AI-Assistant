import asyncio
from types import SimpleNamespace

from presentation.panels.conversation.conversation_history_controller import (
    ConversationHistoryController,
)
from presentation.panels.conversation.conversation_rag_controller import (
    ConversationRagController,
)


class _FakeSessionSupport:
    def __init__(self):
        self.opened_session_id = ""
        self.deleted_session_ids = []
        self.current_session_id = "session-1"
        self.sessions = [
            SimpleNamespace(session_id="session-1", name="Session 1"),
            SimpleNamespace(session_id="session-2", name="Session 2"),
        ]

    def ensure_current_session_persisted(self):
        return None

    def list_sessions(self):
        return list(self.sessions)

    def get_current_session_id(self):
        return self.current_session_id

    def get_session_messages(self, session_id: str):
        return [{"type": "user", "content": f"preview:{session_id}"}]

    def open_session(self, session_id: str) -> bool:
        self.opened_session_id = session_id
        return True

    def delete_session(self, session_id: str) -> bool:
        self.deleted_session_ids.append(session_id)
        self.sessions = [session for session in self.sessions if session.session_id != session_id]
        return True

    @staticmethod
    def normalize_export_format(export_format: str) -> str:
        normalized = str(export_format or "").strip().lower()
        return normalized if normalized in {"json", "txt", "md"} else ""

    @staticmethod
    def build_default_export_path(session_id: str, export_format: str) -> str:
        return f"E:/demo/{session_id}.{export_format}"

    @staticmethod
    def normalize_export_file_path(file_path: str, export_format: str) -> str:
        normalized_path = str(file_path or "").strip()
        if not normalized_path:
            return ""
        suffix = f".{export_format}"
        return normalized_path if normalized_path.endswith(suffix) else f"{normalized_path}{suffix}"

    def choose_export_file_path(self, *args, **kwargs):
        del args, kwargs
        return "E:/demo/export.md"

    def export_session_to_path(self, session_id: str, export_format: str, file_path: str):
        return True, self.normalize_export_file_path(file_path, export_format)


class _FakeQueryResult:
    is_empty = False
    chunks_count = 1

    @staticmethod
    def format_as_context(max_tokens: int = 3000) -> str:
        del max_tokens
        return "chunk result"


class _FakeRagManager:
    def __init__(self):
        self.project_root = "E:/demo"
        self.is_available = True
        self.is_indexing = False
        self.init_error = None
        self.cleared = False
        self.queries = []

    def get_index_status(self):
        stats = SimpleNamespace(
            total_files=2,
            processed=2,
            failed=0,
            excluded=0,
            total_chunks=4,
            total_entities=1,
            total_relations=0,
            storage_size_mb=1.5,
        )
        files = [
            SimpleNamespace(
                relative_path="src/app.py",
                status="processed",
                chunks_count=4,
                indexed_at="2026-04-11T10:00:00",
                exclude_reason="",
                error="",
            )
        ]
        return SimpleNamespace(stats=stats, files=files)

    def trigger_index(self):
        self.is_indexing = True

    async def clear_index_async(self):
        await asyncio.sleep(0)
        self.cleared = True

    async def query_async(self, query: str):
        self.queries.append(query)
        await asyncio.sleep(0)
        return _FakeQueryResult()


def _get_text(key: str, default: str = "") -> str:
    del key
    return default


def test_history_controller_handles_refresh_open_and_delete_flow():
    state_changes = []
    notices = []
    confirms = []
    support = _FakeSessionSupport()
    controller = ConversationHistoryController(
        session_support=support,
        get_text=_get_text,
        on_state_changed=lambda: state_changes.append(True),
        on_notice_requested=lambda message, **kwargs: notices.append((message, kwargs)),
        on_confirm_requested=lambda **kwargs: confirms.append(kwargs),
        logger_getter=lambda: None,
    )

    controller.refresh()
    assert controller.state["is_open"] is True
    assert controller.state["selected_session_id"] == "session-1"
    assert controller.state["preview_messages"][0]["content"] == "preview:session-1"

    assert controller.open_session("session-2") is True
    assert support.opened_session_id == "session-2"
    assert controller.state["is_open"] is False

    controller.refresh()
    controller.request_delete_session("session-2")
    assert confirms[-1]["kind"] == "history_delete"

    assert controller.handle_confirm_acceptance("history_delete", {"session_id": "session-2"}) is True
    assert support.deleted_session_ids == ["session-2"]
    assert controller.state["is_open"] is True
    assert notices == []
    assert state_changes


def test_rag_controller_builds_state_and_runs_search_and_clear_actions():
    state_changes = []
    confirms = []
    manager = _FakeRagManager()
    controller = ConversationRagController(
        rag_manager_getter=lambda: manager,
        get_text=_get_text,
        on_state_changed=lambda: state_changes.append(True),
        on_confirm_requested=lambda **kwargs: confirms.append(kwargs),
        logger_getter=lambda: None,
    )

    controller.handle_index_started({"data": {"total_files": 3}})
    frontend_state = controller.build_frontend_state()
    assert frontend_state["status"]["phase"] == "indexing"
    assert frontend_state["progress"]["total"] == 3
    assert frontend_state["files"][0]["relative_path"] == "src/app.py"

    controller.request_clear_index()
    assert confirms[-1]["kind"] == "rag_clear"

    async def run_async_flow():
        controller.request_search("voltage")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        search_state = controller.build_frontend_state()
        assert search_state["search"]["result_text"].startswith("片段: 1")
        await controller.clear_index()

    asyncio.run(run_async_flow())

    frontend_state = controller.build_frontend_state()
    assert manager.queries == ["voltage"]
    assert manager.cleared is True
    assert frontend_state["search"]["result_text"] == ""
    assert frontend_state["info"]["message"] == "索引库已清空"
    assert state_changes
