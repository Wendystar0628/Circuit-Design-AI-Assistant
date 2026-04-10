from types import SimpleNamespace

from PyQt6.QtCore import QJsonValue

from presentation.model_config.model_config_controller import ModelConfigController, ModelConfigDraft
from presentation.model_config.model_config_state_serializer import ModelConfigStateSerializer
from presentation.panels.conversation.conversation_web_bridge import ConversationWebBridge


class _FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, handler):
        self.subscriptions.append((event_type, handler))

    def unsubscribe(self, event_type, handler):
        self.unsubscriptions.append((event_type, handler))
        return True


def test_conversation_web_bridge_normalizes_model_config_actions():
    bridge = ConversationWebBridge()
    ready_events = []
    draft_events = []
    tab_events = []
    test_events = []
    save_events = []
    close_events = []

    bridge.ready.connect(lambda: ready_events.append(True))
    bridge.model_config_draft_update_requested.connect(
        lambda section, field, value: draft_events.append((section, field, value))
    )
    bridge.model_config_tab_change_requested.connect(lambda tab_id: tab_events.append(tab_id))
    bridge.model_config_test_requested.connect(lambda: test_events.append(True))
    bridge.model_config_save_requested.connect(lambda: save_events.append(True))
    bridge.model_config_close_requested.connect(lambda: close_events.append(True))

    bridge.markReady()
    bridge.updateModelConfigDraft("chat", "timeout", QJsonValue.fromVariant(45))
    bridge.updateModelConfigDraft("embedding", "apiKey", {"masked": False})
    bridge.selectModelConfigTab("embedding")
    bridge.selectModelConfigTab("invalid")
    bridge.requestModelConfigTestConnection()
    bridge.requestModelConfigSave()
    bridge.closeModelConfig()

    assert ready_events == [True]
    assert draft_events == [
        ("chat", "timeout", 45),
        ("embedding", "apiKey", {"masked": False}),
    ]
    assert tab_events == ["embedding", "chat"]
    assert test_events == [True]
    assert save_events == [True]
    assert close_events == [True]


def test_model_config_state_serializer_builds_authoritative_payload():
    serializer = ModelConfigStateSerializer(lambda _key, default: default)
    draft = ModelConfigDraft(
        active_tab="embedding",
        chat_provider="zhipu",
        chat_model="glm-4.7",
        chat_api_key="sk-chat",
        chat_base_url="https://chat.example.com",
        chat_timeout=90,
        chat_streaming=False,
        chat_enable_thinking=True,
        chat_thinking_timeout=240,
        chat_validation_status="verified",
        embedding_provider="zhipu",
        embedding_model="embedding-3",
        embedding_api_key="sk-embedding",
        embedding_base_url="https://embedding.example.com",
        embedding_timeout=30,
        embedding_batch_size=16,
        embedding_validation_status="verified",
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
        status_state="verified",
        status_text="Connection successful",
    )

    assert payload["surface"]["activeTab"] == "embedding"
    assert payload["surface"]["tabs"][0]["id"] == "chat"
    assert payload["surface"]["tabs"][1]["id"] == "embedding"
    assert payload["surface"]["status"] == {
        "state": "verified",
        "text": "Connection successful",
    }
    assert payload["chat"]["providerOptions"] == [{"value": "zhipu", "label": "智谱 AI"}]
    assert payload["chat"]["labels"]["featuresTitle"] == "Provider Features"
    assert payload["chat"]["supportsThinking"] is True
    assert payload["embedding"]["modelOptions"][0]["value"] == "embedding-3"
    assert payload["embedding"]["labels"]["batchSize"] == "Batch Size"
    assert "confirmDialog" not in payload
    assert "noticeDialog" not in payload


def test_model_config_controller_requests_confirmation_for_unverified_save():
    confirm_requests = []
    controller = ModelConfigController(
        config_manager=None,
        llm_runtime_config_manager=None,
        credential_manager=None,
        event_bus=None,
        i18n_manager=None,
        logger=None,
        on_state_changed=lambda _state: None,
        on_close_requested=lambda: None,
        on_confirm_requested=lambda **payload: confirm_requests.append(payload),
        on_notice_requested=lambda *_args, **_kwargs: None,
    )

    controller._draft = ModelConfigDraft(
        chat_provider="zhipu",
        chat_model="glm-4.7",
        chat_api_key="sk-chat",
        embedding_provider="zhipu",
        embedding_model="embedding-3",
        embedding_api_key="sk-embedding",
    )

    controller.request_save()

    assert confirm_requests == [
        {
            "kind": "model_config_save_without_verify",
            "title": "Confirm",
            "message": "One or more API keys have not been verified. Save anyway?",
            "confirm_label": "Save",
            "cancel_label": "Cancel",
            "tone": "normal",
            "payload": None,
        }
    ]


def test_model_config_controller_unsubscribes_language_events_on_deactivate():
    event_bus = _FakeEventBus()
    emitted_states = []
    controller = ModelConfigController(
        config_manager=None,
        llm_runtime_config_manager=None,
        credential_manager=None,
        event_bus=event_bus,
        i18n_manager=None,
        logger=None,
        on_state_changed=lambda state: emitted_states.append(state),
        on_close_requested=lambda: None,
        on_confirm_requested=lambda **_payload: None,
        on_notice_requested=lambda *_args, **_kwargs: None,
    )

    controller.activate()
    controller.deactivate()

    assert len(event_bus.subscriptions) == 1
    assert len(event_bus.unsubscriptions) == 1
    assert event_bus.subscriptions[0][0] == event_bus.unsubscriptions[0][0]
