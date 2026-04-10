from domain.llm.context_manager import ContextManager
from domain.llm.conversation_rollback_service import (
    ConversationRollbackPreview,
    RollbackMessageSummary,
)
from domain.llm.message_helpers import get_reasoning_content
from domain.llm.message_types import Attachment
from domain.llm.session_state_manager import SessionInfo
from domain.services.snapshot_service import SnapshotFileChange
from presentation.panels.conversation.conversation_session_support import (
    ConversationSessionSupport,
)
from presentation.panels.conversation.conversation_state_serializer import (
    ConversationStateSerializer,
)
from presentation.panels.conversation.conversation_view_model import (
    AgentStep,
    AgentStepToolCall,
    ConversationViewModel,
    DisplayMessage,
    SuggestionItem,
)
from presentation.panels.conversation.conversation_web_bridge import (
    ConversationWebBridge,
)


def test_conversation_state_serializer_builds_authoritative_main_payload():
    serializer = ConversationStateSerializer()
    tool_call = AgentStepToolCall(
        tool_call_id="tool-1",
        tool_name="read_file",
        arguments={"path": "notes.txt"},
        result_content="done",
        is_error=False,
        details={"duration_ms": 12},
    )
    message_step = AgentStep(
        step_index=1,
        step_id="step-1",
        content="Inspecting workspace",
        reasoning_content="Need to inspect before editing",
        tool_calls=[tool_call],
        web_search_query="",
        web_search_results=[],
        web_search_message="",
        web_search_state="idle",
        is_complete=True,
    )
    runtime_step = AgentStep(
        step_index=2,
        step_id="step-2",
        content="Applying patch",
        reasoning_content="State contract is stable",
        tool_calls=[],
        web_search_query="",
        web_search_results=[],
        web_search_message="",
        web_search_state="idle",
        is_complete=False,
    )
    message = DisplayMessage(
        id="assistant-1",
        role="assistant",
        content="已完成状态序列化。",
        attachments=[
            Attachment(
                type="file",
                path="E:/demo/spec.md",
                name="spec.md",
                mime_type="text/markdown",
                size=123,
            )
        ],
        agent_steps=[message_step],
        suggestions=[
            SuggestionItem(
                id="suggestion-1",
                label="继续",
                value="continue",
                description="继续执行下一步",
                is_recommended=True,
            )
        ],
        status_summary="awaiting",
        suggestion_state="active",
        selected_suggestion_id="",
        can_rollback=True,
    )

    payload = serializer.serialize_main_state(
        session_id="session-1",
        session_name="Chat 2026-04-10 12:00",
        messages=[message],
        runtime_steps=[runtime_step],
        usage_info={
            "ratio": 0.42,
            "current_tokens": 420,
            "max_tokens": 1000,
            "input_limit": 800,
            "output_reserve": 200,
            "state": "warning",
            "message_count": 1,
        },
        pending_workspace_edit_summary={
            "file_count": 1,
            "added_lines": 5,
            "deleted_lines": 2,
            "files": [
                {
                    "path": "E:/demo/file.py",
                    "relative_path": "file.py",
                    "added_lines": 5,
                    "deleted_lines": 2,
                }
            ],
        },
        model_display_name="gpt-4.1",
        action_mode="stop",
        action_status="正在生成…",
        history_overlay={
            "is_open": True,
            "current_session_id": "session-1",
            "selected_session_id": "session-1",
            "sessions": [],
            "preview_messages": [],
        },
        rollback_overlay={
            "is_open": False,
            "target_message_id": "",
            "preview": None,
        },
        confirm_dialog={
            "is_open": True,
            "kind": "clear_display",
            "title": "确认",
            "message": "确认清空显示？",
            "confirm_label": "确认",
            "cancel_label": "取消",
            "tone": "normal",
            "payload": {},
        },
        notice_dialog={
            "is_open": True,
            "title": "提示",
            "message": "状态已同步",
            "tone": "success",
        },
        is_loading=True,
        can_send=False,
        send_in_progress=False,
        rollback_in_progress=False,
    )

    assert payload["session"] == {
        "id": "session-1",
        "name": "Chat 2026-04-10 12:00",
    }
    assert payload["conversation"]["message_count"] == 1
    assert payload["conversation"]["is_loading"] is True
    assert payload["conversation"]["can_send"] is False
    assert payload["conversation"]["messages"][0]["agent_steps"][0]["tool_calls"][0]["tool_name"] == "read_file"
    assert payload["conversation"]["runtime_steps"][0]["step_id"] == "step-2"
    assert payload["composer"]["usage"]["state"] == "warning"
    assert payload["composer"]["model_display_name"] == "gpt-4.1"
    assert payload["composer"]["action_mode"] == "stop"
    assert payload["composer"]["pending_workspace_edit_summary"]["files"][0]["relative_path"] == "file.py"
    assert payload["view_flags"]["has_messages"] is True
    assert payload["view_flags"]["has_runtime_steps"] is True
    assert payload["view_flags"]["has_pending_workspace_edits"] is True
    assert payload["view_flags"]["is_busy"] is True
    assert payload["overlays"]["history"]["is_open"] is True
    assert payload["overlays"]["confirm"]["kind"] == "clear_display"
    assert payload["overlays"]["notice"]["tone"] == "success"


def test_conversation_state_serializer_serializes_history_and_rollback_payloads():
    serializer = ConversationStateSerializer()
    file_change = SnapshotFileChange(
        relative_path="src/app.py",
        change_type="modified",
        summary="updated app flow",
        added_lines=7,
        deleted_lines=3,
        diff_preview="@@ -1,3 +1,7 @@",
        is_text=True,
    )
    preview = ConversationRollbackPreview(
        session_id="session-rollback",
        snapshot_id="snapshot-1",
        anchor_message_id="user-2",
        anchor_timestamp="2026-04-10T12:00:00",
        anchor_label="继续优化对话面板",
        current_message_count=8,
        target_message_count=4,
        removed_message_count=4,
        removed_messages=[
            RollbackMessageSummary(
                message_id="user-2",
                role="user",
                timestamp="2026-04-10T12:00:00",
                content_preview="继续优化对话面板",
            )
        ],
        changed_files=[file_change],
        changed_file_count=1,
        total_added_lines=7,
        total_deleted_lines=3,
        workspace_changed_files=[file_change],
        workspace_changed_file_count=1,
        workspace_total_added_lines=7,
        workspace_total_deleted_lines=3,
    )
    history_state = serializer.serialize_history_state(
        sessions=[
            SessionInfo(
                session_id="session-rollback",
                name="Chat",
                created_at="2026-04-10T11:00:00",
                updated_at="2026-04-10T12:00:00",
                message_count=8,
                preview="继续优化对话面板",
                has_partial_response=False,
            )
        ],
        current_session_id="session-rollback",
        selected_session_id="session-rollback",
        preview_messages=[
            {
                "type": "user",
                "content": "继续优化对话面板",
                "additional_kwargs": {
                    "metadata": {
                        "timestamp": "2026-04-10T12:00:00",
                        "id": "user-2",
                    }
                },
            }
        ],
    )
    rollback_state = serializer.serialize_rollback_preview(preview)
    history_overlay = serializer.serialize_history_overlay_state(
        {
            "is_open": True,
            "is_loading": False,
            "error_message": "",
            "current_session_id": "session-rollback",
            "selected_session_id": "session-rollback",
            "sessions": [
                SessionInfo(
                    session_id="session-rollback",
                    name="Chat",
                    created_at="2026-04-10T11:00:00",
                    updated_at="2026-04-10T12:00:00",
                    message_count=8,
                    preview="继续优化对话面板",
                    has_partial_response=False,
                )
            ],
            "preview_messages": [
                {
                    "type": "user",
                    "content": "继续优化对话面板",
                    "additional_kwargs": {
                        "metadata": {
                            "timestamp": "2026-04-10T12:00:00",
                            "id": "user-2",
                        }
                    },
                }
            ],
        }
    )
    rollback_overlay = serializer.serialize_rollback_overlay_state(
        {
            "is_open": True,
            "is_loading": False,
            "error_message": "",
            "target_message_id": "user-2",
            "preview": preview,
        }
    )
    confirm_state = serializer.serialize_confirm_dialog_state(
        {
            "is_open": True,
            "kind": "history_delete",
            "title": "警告",
            "message": "确认删除？",
            "confirm_label": "删除",
            "cancel_label": "取消",
            "tone": "danger",
            "payload": {"session_id": "session-rollback"},
        }
    )
    notice_state = serializer.serialize_notice_dialog_state(
        {
            "is_open": True,
            "title": "提示",
            "message": "导出成功",
            "tone": "success",
        }
    )

    assert history_state["sessions"][0]["session_id"] == "session-rollback"
    assert history_state["preview_messages"][0]["message_id"] == "user-2"
    assert rollback_state["anchor_message_id"] == "user-2"
    assert rollback_state["workspace_changed_files"][0]["relative_path"] == "src/app.py"
    assert rollback_state["workspace_total_added_lines"] == 7
    assert history_overlay["is_open"] is True
    assert rollback_overlay["target_message_id"] == "user-2"
    assert confirm_state["payload"]["session_id"] == "session-rollback"
    assert notice_state["tone"] == "success"


def test_conversation_session_support_formats_exports():
    messages = [
        {
            "type": "assistant",
            "content": "已完成迁移。",
            "additional_kwargs": {
                "metadata": {
                    "timestamp": "2026-04-10T12:00:00",
                }
            },
        }
    ]

    json_content = ConversationSessionSupport.format_export_content(messages, "json")
    txt_content = ConversationSessionSupport.format_export_content(messages, "txt")
    md_content = ConversationSessionSupport.format_export_content(messages, "md")

    assert '"type": "assistant"' in json_content
    assert "[ASSISTANT] 2026-04-10T12:00:00" in txt_content
    assert "## 🤖 Assistant (2026-04-10T12:00:00)" in md_content


def test_conversation_web_bridge_emits_structured_user_intent_actions():
    bridge = ConversationWebBridge()
    ready_events = []
    send_events = []
    rollback_events = []
    attachment_events = []
    history_select_events = []
    history_open_events = []
    history_export_events = []
    history_delete_events = []
    confirm_events = []
    notice_close_events = []
    rollback_close_events = []
    rollback_confirm_events = []

    bridge.ready.connect(lambda: ready_events.append(True))
    bridge.send_requested.connect(
        lambda text, payload: send_events.append((text, payload))
    )
    bridge.rollback_requested.connect(lambda message_id: rollback_events.append(message_id))
    bridge.attachments_selected.connect(lambda paths: attachment_events.append(paths))
    bridge.history_session_selected.connect(lambda session_id: history_select_events.append(session_id))
    bridge.history_session_open_requested.connect(lambda session_id: history_open_events.append(session_id))
    bridge.history_session_export_requested.connect(
        lambda session_id, export_format: history_export_events.append((session_id, export_format))
    )
    bridge.history_session_delete_requested.connect(lambda session_id: history_delete_events.append(session_id))
    bridge.confirm_dialog_resolved.connect(lambda accepted: confirm_events.append(accepted))
    bridge.notice_dialog_close_requested.connect(lambda: notice_close_events.append(True))
    bridge.rollback_preview_close_requested.connect(lambda: rollback_close_events.append(True))
    bridge.rollback_confirm_requested.connect(lambda: rollback_confirm_events.append(True))

    bridge.markReady()
    bridge.sendMessage("请继续", {"draftAttachments": ["a.png"]})
    bridge.requestRollback("message-3")
    bridge.selectHistorySession("session-1")
    bridge.openHistorySession("session-2")
    bridge.requestExportHistorySession("session-3", "md")
    bridge.requestDeleteHistorySession("session-4")
    bridge.resolveConfirmDialog(True)
    bridge.closeNoticeDialog()
    bridge.closeRollbackPreview()
    bridge.confirmRollback()
    bridge.attachFiles(["E:/demo/a.png", "", None, "E:/demo/b.txt"])

    assert ready_events == [True]
    assert send_events == [("请继续", {"draftAttachments": ["a.png"]})]
    assert rollback_events == ["message-3"]
    assert attachment_events == [["E:/demo/a.png", "E:/demo/b.txt"]]
    assert history_select_events == ["session-1"]
    assert history_open_events == ["session-2"]
    assert history_export_events == [("session-3", "md")]
    assert history_delete_events == ["session-4"]
    assert confirm_events == [True]
    assert notice_close_events == [True]
    assert rollback_close_events == [True]
    assert rollback_confirm_events == [True]


def test_partial_response_persists_latest_reasoning_content():
    context_manager = ContextManager()
    view_model = ConversationViewModel()
    view_model._context_manager = context_manager
    view_model._active_agent_steps = [
        AgentStep(
            step_index=1,
            step_id="step-1",
            content="partial answer",
            reasoning_content="latest reasoning",
            tool_calls=[],
            web_search_query="",
            web_search_results=[],
            web_search_message="",
            web_search_state="idle",
            is_complete=False,
        )
    ]

    view_model._save_partial_response("partial answer", "user_requested")

    messages = context_manager.get_display_messages()
    assert len(messages) == 1
    assert get_reasoning_content(messages[-1]) == "latest reasoning"
