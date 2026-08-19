import asyncio
from types import SimpleNamespace

from PyQt6.QtCore import QObject, pyqtSignal

from domain.llm.llm_executor import (
    ACTIVE_GENERATION_ERROR,
    LLMExecutor,
    OUTCOME_COMPLETED,
    OUTCOME_ERROR,
    OUTCOME_STOPPED,
)
from presentation.panels.conversation.conversation_history_controller import (
    ConversationHistoryController,
)
from presentation.panels.conversation.conversation_view_model import (
    AgentStep,
    ConversationViewModel,
)
from presentation.panels.conversation_panel import ConversationPanel
from shared.service_locator import ServiceLocator
from shared.service_names import SVC_CONTEXT_MANAGER


class _Registry:
    @staticmethod
    def get_names():
        return []


def _completed_result(content: str = "done"):
    return SimpleNamespace(
        is_error=False,
        error_message="",
        content=content,
        reasoning_content="",
        usage={},
        total_turns=1,
        tool_calls_count=0,
    )


def _prepare_executor(monkeypatch, loop_type):
    from domain.llm.agent import agent_loop, agent_prompt_builder, tool_factory

    monkeypatch.setattr(agent_loop, "AgentLoop", loop_type)
    monkeypatch.setattr(tool_factory, "create_default_tools", lambda: _Registry())
    monkeypatch.setattr(
        agent_prompt_builder,
        "build_agent_system_prompt",
        lambda **kwargs: "system",
    )

    executor = LLMExecutor()
    monkeypatch.setattr(executor, "_get_llm_client", lambda model: object())
    monkeypatch.setattr(executor, "_get_project_root", lambda: "E:/demo")
    monkeypatch.setattr(executor, "_get_active_circuit_file", lambda: None)
    monkeypatch.setattr(executor, "_get_rag_query_service", lambda: None)
    monkeypatch.setattr(executor, "_get_sim_job_manager", lambda: None)
    monkeypatch.setattr(executor, "_get_sim_result_repository", lambda: None)
    monkeypatch.setattr(
        executor,
        "_get_pending_workspace_edit_service",
        lambda: None,
    )
    return executor


def test_active_circuit_fallback_reads_current_conversation_state():
    context_manager = SimpleNamespace(
        get_current_state=lambda: {"circuit_file_path": "E:/demo/main.cir"}
    )
    ServiceLocator.clear()
    try:
        ServiceLocator.register(SVC_CONTEXT_MANAGER, context_manager)
        assert LLMExecutor()._get_active_circuit_file() == "E:/demo/main.cir"
    finally:
        ServiceLocator.clear()


def test_executor_rejects_second_live_task_without_replacing_owner(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    class _ControlledLoop:
        def __init__(self, **kwargs):
            del kwargs

        async def run(self, messages, on_event):
            del messages, on_event
            started.set()
            await release.wait()
            return _completed_result("first")

    async def scenario():
        executor = _prepare_executor(monkeypatch, _ControlledLoop)
        finished = []
        executor.generation_finished.connect(
            lambda task_id, result: finished.append((task_id, dict(result)))
        )

        first = executor.execute_agent("task-a", [], "model")
        await started.wait()
        assert executor.is_generating is True
        assert executor._active_task is first

        second = executor.execute_agent("task-b", [], "model")
        await second

        assert executor._active_task is first
        assert executor._active_task_id == "task-a"
        rejected = next(result for task_id, result in finished if task_id == "task-b")
        assert rejected["outcome"] == OUTCOME_ERROR
        assert rejected["rejected"] is True
        assert ACTIVE_GENERATION_ERROR in rejected["error_message"]

        release.set()
        await first
        assert executor.is_generating is False
        assert any(
            task_id == "task-a" and result["outcome"] == OUTCOME_COMPLETED
            for task_id, result in finished
        )

    asyncio.run(scenario())


def test_executor_stop_checks_task_identity_and_cancel_emits_stopped(monkeypatch):
    started = asyncio.Event()

    class _WaitingLoop:
        def __init__(self, **kwargs):
            del kwargs

        async def run(self, messages, on_event):
            del messages, on_event
            started.set()
            await asyncio.Event().wait()

    async def scenario():
        executor = _prepare_executor(monkeypatch, _WaitingLoop)
        finished = []
        executor.generation_finished.connect(
            lambda task_id, result: finished.append((task_id, dict(result)))
        )
        task = executor.execute_agent("task-a", [], "model")
        await started.wait()

        assert executor.request_stop("task-b") is False
        assert task.cancelled() is False
        assert executor.request_stop("task-a") is True
        await task

        assert executor.is_generating is False
        assert finished[-1] == ("task-a", {"outcome": OUTCOME_STOPPED})

    asyncio.run(scenario())


def test_executor_shutdown_cancels_and_awaits_active_task(monkeypatch):
    started = asyncio.Event()

    class _WaitingLoop:
        def __init__(self, **kwargs):
            del kwargs

        async def run(self, messages, on_event):
            del messages, on_event
            started.set()
            await asyncio.Event().wait()

    async def scenario():
        executor = _prepare_executor(monkeypatch, _WaitingLoop)
        task = executor.execute_agent("task-a", [], "model")
        await started.wait()

        await executor.shutdown()
        await executor.shutdown()

        assert task.done() is True
        assert executor.is_generating is False
        assert executor._active_task_id is None

    asyncio.run(scenario())


def test_start_agent_claims_task_before_first_event_loop_turn(monkeypatch):
    calls = {"loop_created": 0, "project_root": 0}

    class _MustNotStartLoop:
        def __init__(self, **kwargs):
            del kwargs
            calls["loop_created"] += 1

        async def run(self, messages, on_event):
            del messages, on_event
            raise AssertionError("cancelled scheduled task must never enter AgentLoop")

    async def scenario():
        executor = _prepare_executor(monkeypatch, _MustNotStartLoop)
        finished = []
        executor.generation_finished.connect(
            lambda task_id, result: finished.append((task_id, dict(result)))
        )

        def project_root():
            calls["project_root"] += 1
            return "E:/new-project"

        monkeypatch.setattr(executor, "_get_project_root", project_root)
        task = executor.start_agent("task-pending", [], "model")

        # No event-loop yield occurred between scheduling and these checks.
        assert task is executor._active_task
        assert executor._active_task_id == "task-pending"
        assert executor.request_stop("task-pending") is True
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)

        assert calls == {"loop_created": 0, "project_root": 0}
        assert executor.is_generating is False
        assert executor._active_task_id is None
        assert finished == [
            ("task-pending", {"outcome": OUTCOME_STOPPED})
        ]

    asyncio.run(scenario())


def test_stale_task_finally_does_not_clear_new_task_owner(monkeypatch):
    holder = {"executor": None, "replacement_task": None}

    class _OwnerSwapLoop:
        def __init__(self, **kwargs):
            del kwargs

        async def run(self, messages, on_event):
            del messages, on_event
            holder["executor"]._active_task = holder["replacement_task"]
            holder["executor"]._active_task_id = "task-b"
            return _completed_result("first")

    async def scenario():
        executor = _prepare_executor(monkeypatch, _OwnerSwapLoop)
        replacement_task = asyncio.create_task(asyncio.Event().wait())
        holder["executor"] = executor
        holder["replacement_task"] = replacement_task
        first = executor.execute_agent("task-a", [], "model")
        await first

        assert executor._active_task is replacement_task
        assert executor._active_task_id == "task-b"
        replacement_task.cancel()
        try:
            await replacement_task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


class _FakeExecutor(QObject):
    agent_turn_started = pyqtSignal(str, int)
    stream_chunk = pyqtSignal(str, int, str, dict)
    generation_finished = pyqtSignal(str, dict)
    tool_execution_started = pyqtSignal(str, int, str, str, dict)
    tool_execution_finished = pyqtSignal(str, int, str, str, str, bool, dict)

    def __init__(self):
        super().__init__()
        self.is_generating = True
        self.stop_requests = []

    def request_stop(self, expected_task_id=None):
        self.stop_requests.append(expected_task_id)
        return True


def test_session_change_cancels_and_invalidates_old_view_model_run():
    executor = _FakeExecutor()
    view_model = ConversationViewModel()
    view_model._is_loading = True
    view_model._current_task_id = "task-a"
    view_model._active_session_id = "session-a"
    view_model._active_agent_steps = [AgentStep(step_index=1, content="partial")]
    view_model._connect_llm_executor_signals(executor)

    view_model._on_session_changed(
        {
            "data": {
                "action": "switch",
                "session_id": "session-b",
                "previous_session_id": "session-a",
            }
        }
    )

    assert executor.stop_requests == ["task-a"]
    assert view_model.is_loading is False
    assert view_model._current_task_id is None
    assert view_model.active_agent_steps == []
    assert view_model._connected_llm_executor is None

    # A late signal from the cancelled task is disconnected/invalidated and
    # therefore cannot append into the newly selected conversation.
    executor.stream_chunk.emit("task-a", 1, "content", {"text": "late"})
    assert view_model.active_agent_steps == []


def test_deleting_non_current_session_does_not_cancel_active_run():
    executor = _FakeExecutor()
    view_model = ConversationViewModel()
    view_model._is_loading = True
    view_model._current_task_id = "task-a"
    view_model._active_session_id = "session-a"
    view_model._connect_llm_executor_signals(executor)

    view_model._on_session_changed(
        {
            "data": {
                "action": "delete",
                "session_id": "session-a",
                "previous_session_id": "session-old",
            }
        }
    )

    assert executor.stop_requests == []
    assert view_model.is_loading is True
    assert view_model._current_task_id == "task-a"


def test_session_change_cancels_message_submission_before_llm_start(monkeypatch):
    checkpoint_started = asyncio.Event()
    release_checkpoint = asyncio.Event()

    class _RollbackService:
        async def capture_user_turn_checkpoint(self, **kwargs):
            del kwargs
            checkpoint_started.set()
            await release_checkpoint.wait()

    class _ContextManager:
        def __init__(self):
            self.added = []

        def add_user_message(self, *args, **kwargs):
            self.added.append((args, kwargs))

    async def scenario():
        context_manager = _ContextManager()
        view_model = ConversationViewModel()
        view_model._context_manager = context_manager
        view_model._conversation_rollback_service = _RollbackService()
        monkeypatch.setattr(view_model, "load_messages", lambda *args, **kwargs: None)
        monkeypatch.setattr(view_model, "_update_usage_ratio", lambda: None)

        submission = asyncio.create_task(view_model.send_message("hello"))
        await checkpoint_started.wait()
        assert view_model.can_change_session()[0] is False

        view_model._on_session_changed(
            {
                "data": {
                    "action": "switch",
                    "session_id": "session-b",
                    "previous_session_id": "session-a",
                }
            }
        )

        try:
            await submission
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("message submission should be cancelled")

        assert context_manager.added == []
        assert view_model._message_submission_task is None
        assert view_model._message_submission_in_progress is False

    asyncio.run(scenario())


class _HistorySupport:
    def __init__(self):
        self.session_state_manager = object()
        self.project_root = "E:/demo"
        self.opened = []
        self.deleted = []

    def get_project_root(self):
        return self.project_root

    @staticmethod
    def normalize_export_format(export_format):
        return str(export_format or "")

    @staticmethod
    def build_default_export_path(session_id, export_format):
        return f"{session_id}.{export_format}"

    @staticmethod
    def normalize_export_file_path(file_path, export_format):
        del export_format
        return str(file_path or "")

    def open_session(self, session_id):
        self.opened.append(session_id)
        return True

    def delete_session(self, session_id, *, project_root=None):
        del project_root
        self.deleted.append(session_id)
        return True


def test_history_mutations_are_rejected_while_generation_is_active():
    support = _HistorySupport()
    notices = []
    confirms = []
    controller = ConversationHistoryController(
        session_support=support,
        get_text=lambda key, default: default,
        on_state_changed=lambda: None,
        on_notice_requested=lambda message, **kwargs: notices.append(message),
        on_confirm_requested=lambda **kwargs: confirms.append(kwargs),
        logger_getter=lambda: None,
        can_mutate_session=lambda: (False, "generation-active"),
    )

    assert controller.open_session("session-b") is False
    controller.request_delete_session("session-b")
    assert controller.handle_confirm_acceptance(
        "history_delete", {"session_id": "session-b"}
    ) is True

    assert support.opened == []
    assert support.deleted == []
    assert confirms == []
    assert notices == ["generation-active", "generation-active"]


def test_panel_claims_send_before_scheduled_coroutine_gets_first_turn():
    release = asyncio.Event()

    class _PanelHarness:
        _on_send_requested = ConversationPanel._on_send_requested

        def __init__(self):
            self._send_in_progress = False
            self._rollback_in_progress = False
            self.sync_states = []
            self.started = asyncio.Event()

        def _sync_input_action_state(self):
            self.sync_states.append(self._send_in_progress)

        async def _send_message(self, text, composer_state, *, send_claimed=False):
            del text, composer_state
            assert send_claimed is True
            self.started.set()
            await release.wait()
            self._send_in_progress = False

    async def scenario():
        panel = _PanelHarness()
        panel._on_send_requested("hello", {})

        # This assertion runs before the scheduled _send_message coroutine.
        assert panel._send_in_progress is True
        assert panel.sync_states == [True]
        await panel.started.wait()
        release.set()
        await asyncio.sleep(0)

    asyncio.run(scenario())
