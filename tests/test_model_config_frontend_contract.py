from types import SimpleNamespace

from PyQt6.QtCore import QJsonValue

from presentation.dialogs.model_config_bridge import ModelConfigWebBridge
from presentation.dialogs.model_config_state import (
    ModelConfigDialogController,
    ModelConfigDialogDraft,
)
from presentation.dialogs.model_config_state_serializer import ModelConfigStateSerializer


class _FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, handler):
        self.subscriptions.append((event_type, handler))

    def unsubscribe(self, event_type, handler):
        self.unsubscriptions.append((event_type, handler))
        return True


def test_model_config_web_bridge_normalizes_draft_and_tab_actions():
    bridge = ModelConfigWebBridge()
    ready_events = []
    draft_events = []
    tab_events = []
    confirm_events = []
    notice_close_events = []

    bridge.ready.connect(lambda: ready_events.append(True))
    bridge.draft_update_requested.connect(
        lambda section, field, value: draft_events.append((section, field, value))
    )
    bridge.tab_change_requested.connect(lambda tab_id: tab_events.append(tab_id))
    bridge.confirm_dialog_resolved.connect(lambda accepted: confirm_events.append(accepted))
    bridge.notice_dialog_close_requested.connect(lambda: notice_close_events.append(True))

    bridge.markReady()
    bridge.updateDraft("chat", "timeout", QJsonValue.fromVariant(45))
    bridge.updateDraft("embedding", "apiKey", {"masked": False})
    bridge.selectTab("embedding")
    bridge.selectTab("invalid")
    bridge.resolveConfirmDialog(True)
    bridge.closeNoticeDialog()

    assert ready_events == [True]
    assert draft_events == [
        ("chat", "timeout", 45),
        ("embedding", "apiKey", {"masked": False}),
    ]
    assert tab_events == ["embedding", "chat"]
    assert confirm_events == [True]
    assert notice_close_events == [True]


def test_model_config_state_serializer_builds_authoritative_payload():
    serializer = ModelConfigStateSerializer(lambda _key, default: default)
    draft = ModelConfigDialogDraft(
        active_tab="embedding",
        chat_provider="zhipu",
        chat_model="glm-4.7",
        chat_api_key="sk-chat",
        chat_base_url="https://chat.example.com",
        chat_timeout=90,
        chat_streaming=False,
        chat_enable_thinking=True,
        chat_thinking_timeout=240,
        embedding_provider="zhipu",
        embedding_model="embedding-3",
        embedding_api_key="sk-embedding",
        embedding_base_url="https://embedding.example.com",
        embedding_timeout=30,
        embedding_batch_size=16,
        validation_status="verified",
    )

    payload = serializer.serialize(
        draft=draft,
        chat_providers=[SimpleNamespace(id="zhipu", display_name="智谱 AI")],
        embedding_providers=[
            SimpleNamespace(id="zhipu", display_name="智谱 AI", requires_api_key=True)
        ],
        chat_models=["glm-4.7", "glm-4.6"],
        embedding_models=["embedding-3", "embedding-2"],
        chat_provider=SimpleNamespace(base_url="https://chat.example.com"),
        embedding_provider=SimpleNamespace(
            base_url="https://embedding.example.com",
            requires_api_key=True,
        ),
        supports_thinking=True,
        validation_status_text="Connection successful",
    )

    assert payload["dialog"]["activeTab"] == "embedding"
    assert payload["dialog"]["tabs"][0]["id"] == "chat"
    assert payload["dialog"]["tabs"][1]["id"] == "embedding"
    assert payload["dialog"]["status"] == {
        "state": "verified",
        "text": "Connection successful",
    }
    assert payload["chat"]["providerOptions"] == [{"value": "zhipu", "label": "智谱 AI"}]
    assert payload["chat"]["labels"]["featuresTitle"] == "Provider Features"
    assert payload["chat"]["supportsThinking"] is True
    assert payload["embedding"]["modelOptions"][0]["value"] == "embedding-3"
    assert payload["embedding"]["labels"]["batchSize"] == "Batch Size"
    assert payload["confirmDialog"]["open"] is False
    assert payload["noticeDialog"]["closeText"] == "OK"


def test_model_config_controller_unsubscribes_language_events_on_cleanup():
    event_bus = _FakeEventBus()
    emitted_states = []
    controller = ModelConfigDialogController(
        parent=None,
        config_manager=None,
        llm_runtime_config_manager=None,
        credential_manager=None,
        event_bus=event_bus,
        i18n_manager=None,
        logger=None,
        on_state_changed=lambda state: emitted_states.append(state),
        on_accept_requested=lambda: None,
        on_reject_requested=lambda: None,
    )

    controller.initialize()
    controller.cleanup()

    assert len(event_bus.subscriptions) == 1
    assert len(event_bus.unsubscriptions) == 1
    assert event_bus.subscriptions[0][0] == event_bus.unsubscriptions[0][0]
