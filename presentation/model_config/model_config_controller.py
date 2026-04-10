from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import httpx
from PyQt6.QtCore import QTimer

from infrastructure.config.settings import (
    CONFIG_EMBEDDING_BASE_URL,
    CONFIG_EMBEDDING_BATCH_SIZE,
    CONFIG_EMBEDDING_MODEL,
    CONFIG_EMBEDDING_PROVIDER,
    CONFIG_EMBEDDING_TIMEOUT,
    CREDENTIAL_TYPE_EMBEDDING,
    DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_TIMEOUT,
    DEFAULT_THINKING_TIMEOUT,
    DEFAULT_TIMEOUT,
)
from infrastructure.llm_adapters.client_factory import LLMClientFactory
from presentation.model_config.model_config_state_serializer import ModelConfigStateSerializer
from shared.embedding_model_registry import EmbeddingModelRegistry
from shared.event_types import EVENT_LANGUAGE_CHANGED, EVENT_LLM_CONFIG_CHANGED
from shared.model_registry import ModelRegistry


@dataclass
class ModelConfigDraft:
    active_tab: str = "chat"
    chat_provider: str = ""
    chat_model: str = ""
    chat_api_key: str = ""
    chat_base_url: str = ""
    chat_timeout: int = DEFAULT_TIMEOUT
    chat_streaming: bool = True
    chat_enable_thinking: bool = False
    chat_thinking_timeout: int = DEFAULT_THINKING_TIMEOUT
    chat_validation_status: str = "not_verified"
    chat_validation_message: str = ""
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_timeout: int = DEFAULT_EMBEDDING_TIMEOUT
    embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    embedding_validation_status: str = "not_verified"
    embedding_validation_message: str = ""


class ModelConfigController:
    def __init__(
        self,
        *,
        config_manager: Any,
        llm_runtime_config_manager: Any,
        credential_manager: Any,
        event_bus: Any,
        i18n_manager: Any,
        logger: Any,
        on_state_changed: Callable[[Dict[str, Any]], None],
        on_close_requested: Callable[[], None],
        on_confirm_requested: Callable[..., None],
        on_notice_requested: Callable[..., None],
    ):
        self.config_manager = config_manager
        self.llm_runtime_config_manager = llm_runtime_config_manager
        self.credential_manager = credential_manager
        self.event_bus = event_bus
        self.i18n_manager = i18n_manager
        self.logger = logger
        self.on_state_changed = on_state_changed
        self.on_close_requested = on_close_requested
        self.on_confirm_requested = on_confirm_requested
        self.on_notice_requested = on_notice_requested
        self._draft = ModelConfigDraft()
        self._language_subscribed = False
        self._serializer = ModelConfigStateSerializer(self._get_text)

    def activate(self) -> None:
        ModelRegistry.initialize()
        EmbeddingModelRegistry.initialize()
        if self.event_bus and not self._language_subscribed:
            self.event_bus.subscribe(EVENT_LANGUAGE_CHANGED, self._handle_language_changed)
            self._language_subscribed = True
        self.load_state()

    def deactivate(self) -> None:
        if self.event_bus and self._language_subscribed:
            self.event_bus.unsubscribe(EVENT_LANGUAGE_CHANGED, self._handle_language_changed)
            self._language_subscribed = False

    def cleanup(self) -> None:
        self.deactivate()

    def _handle_language_changed(self, _event_data: Dict[str, Any]) -> None:
        self.emit_state()

    def _get_text(self, key: str, default: str) -> str:
        if not self.i18n_manager:
            return default
        try:
            return self.i18n_manager.get_text(key, default)
        except Exception:
            return default

    def _list_chat_providers(self) -> List[Any]:
        try:
            ModelRegistry.initialize()
            providers = ModelRegistry.list_implemented_providers()
            return sorted(providers, key=lambda item: item.display_name.lower())
        except Exception as exc:
            if self.logger:
                self.logger.error(f"加载聊天模型厂商失败: {exc}")
            return []

    def _list_embedding_providers(self) -> List[Any]:
        try:
            EmbeddingModelRegistry.initialize()
            providers = EmbeddingModelRegistry.list_implemented_providers()
            return sorted(providers, key=lambda item: item.display_name.lower())
        except Exception as exc:
            if self.logger:
                self.logger.error(f"加载嵌入模型厂商失败: {exc}")
            return []

    def _get_chat_provider(self, provider_id: str) -> Any:
        if not provider_id:
            return None
        try:
            ModelRegistry.initialize()
            return ModelRegistry.get_provider(provider_id)
        except Exception as exc:
            if self.logger:
                self.logger.error(f"读取聊天模型厂商失败: {exc}")
            return None

    def _get_embedding_provider(self, provider_id: str) -> Any:
        if not provider_id:
            return None
        try:
            EmbeddingModelRegistry.initialize()
            return EmbeddingModelRegistry.get_provider(provider_id)
        except Exception as exc:
            if self.logger:
                self.logger.error(f"读取嵌入模型厂商失败: {exc}")
            return None

    def _get_chat_model_names(self, provider_id: str) -> List[str]:
        if not provider_id:
            return []
        try:
            ModelRegistry.initialize()
            return ModelRegistry.list_model_names(provider_id)
        except Exception as exc:
            if self.logger:
                self.logger.error(f"加载聊天模型列表失败: {exc}")
            return []

    def _get_embedding_model_names(self, provider_id: str) -> List[str]:
        if not provider_id:
            return []
        try:
            EmbeddingModelRegistry.initialize()
            return EmbeddingModelRegistry.list_model_names(provider_id)
        except Exception as exc:
            if self.logger:
                self.logger.error(f"加载嵌入模型列表失败: {exc}")
            return []

    def _provider_supports_thinking(self, provider_id: str, model_name: str) -> bool:
        if not provider_id or not model_name:
            return False
        try:
            ModelRegistry.initialize()
            model = ModelRegistry.get_model(f"{provider_id}:{model_name}")
            return bool(model.supports_thinking) if model else False
        except Exception as exc:
            if self.logger:
                self.logger.error(f"读取模型能力失败: {exc}")
            return False

    def _get_chat_default_model(self, provider_id: str) -> str:
        provider = self._get_chat_provider(provider_id)
        if provider and provider.default_model:
            return provider.default_model
        model_names = self._get_chat_model_names(provider_id)
        return model_names[0] if model_names else ""

    def _get_embedding_default_model(self, provider_id: str) -> str:
        provider = self._get_embedding_provider(provider_id)
        if provider and provider.default_model:
            return provider.default_model
        model_names = self._get_embedding_model_names(provider_id)
        return model_names[0] if model_names else ""

    def _chat_provider_requires_api_key(self) -> bool:
        provider = self._get_chat_provider(self._draft.chat_provider)
        if provider is None:
            return True
        return bool(getattr(provider, "requires_api_key", True))

    def _embedding_provider_requires_api_key(self) -> bool:
        provider = self._get_embedding_provider(self._draft.embedding_provider)
        if provider is None:
            return False
        return bool(getattr(provider, "requires_api_key", False))

    def _load_chat_verification_timestamp(self, provider_id: str) -> str:
        if not self.config_manager or not provider_id:
            return ""
        return self.config_manager.get(f"llm_verified_at_{provider_id}", "")

    def _save_chat_verification_timestamp(self, provider_id: str) -> None:
        if self.config_manager and provider_id:
            self.config_manager.set(
                f"llm_verified_at_{provider_id}",
                datetime.now().isoformat(),
            )

    def _load_embedding_verification_timestamp(self, provider_id: str) -> str:
        if not self.config_manager or not provider_id:
            return ""
        return self.config_manager.get(f"embedding_verified_at_{provider_id}", "")

    def _save_embedding_verification_timestamp(self, provider_id: str) -> None:
        if self.config_manager and provider_id:
            self.config_manager.set(
                f"embedding_verified_at_{provider_id}",
                datetime.now().isoformat(),
            )

    def _refresh_chat_validation_status(self) -> None:
        provider_id = self._draft.chat_provider
        if not provider_id or not self._chat_provider_requires_api_key():
            self._draft.chat_validation_status = "not_verified"
            self._draft.chat_validation_message = ""
            return
        verified_at = self._load_chat_verification_timestamp(provider_id)
        if not verified_at:
            self._draft.chat_validation_status = "not_verified"
            self._draft.chat_validation_message = ""
            return
        current_api_key = self._draft.chat_api_key.strip()
        saved_api_key = ""
        if self.credential_manager and provider_id:
            saved_api_key = self.credential_manager.get_llm_api_key(provider_id).strip()
        if current_api_key and current_api_key == saved_api_key:
            self._draft.chat_validation_status = "verified"
            self._draft.chat_validation_message = ""
        else:
            self._draft.chat_validation_status = "not_verified"
            self._draft.chat_validation_message = ""

    def _refresh_embedding_validation_status(self) -> None:
        provider_id = self._draft.embedding_provider
        if not provider_id or not self._embedding_provider_requires_api_key():
            self._draft.embedding_validation_status = "not_verified"
            self._draft.embedding_validation_message = ""
            return
        verified_at = self._load_embedding_verification_timestamp(provider_id)
        if not verified_at:
            self._draft.embedding_validation_status = "not_verified"
            self._draft.embedding_validation_message = ""
            return
        current_api_key = self._draft.embedding_api_key.strip()
        saved_api_key = ""
        if self.credential_manager and provider_id:
            saved_api_key = self.credential_manager.get_embedding_api_key(provider_id).strip()
        if current_api_key and current_api_key == saved_api_key:
            self._draft.embedding_validation_status = "verified"
            self._draft.embedding_validation_message = ""
        else:
            self._draft.embedding_validation_status = "not_verified"
            self._draft.embedding_validation_message = ""

    def load_state(self) -> None:
        self._draft = ModelConfigDraft(active_tab=self._draft.active_tab or "chat")
        chat_providers = self._list_chat_providers()
        embedding_providers = self._list_embedding_providers()

        if self.llm_runtime_config_manager:
            active_config = self.llm_runtime_config_manager.resolve_active_config()
            self._draft.chat_provider = active_config.provider or ""
            self._draft.chat_model = active_config.model or ""
            self._draft.chat_api_key = active_config.api_key or ""
            self._draft.chat_base_url = active_config.base_url or ""
            self._draft.chat_timeout = int(active_config.timeout or DEFAULT_TIMEOUT)
            self._draft.chat_streaming = bool(active_config.streaming)
            self._draft.chat_enable_thinking = bool(active_config.enable_thinking)
            self._draft.chat_thinking_timeout = int(
                active_config.thinking_timeout or DEFAULT_THINKING_TIMEOUT
            )

        if not self._draft.chat_provider and chat_providers:
            self._draft.chat_provider = chat_providers[0].id
        self._sync_chat_provider_state(preserve_selected_model=True)

        if self.config_manager:
            self._draft.embedding_provider = self.config_manager.get(CONFIG_EMBEDDING_PROVIDER, "") or ""
            self._draft.embedding_model = self.config_manager.get(CONFIG_EMBEDDING_MODEL, "") or ""
            self._draft.embedding_base_url = self.config_manager.get(CONFIG_EMBEDDING_BASE_URL, "") or ""
            self._draft.embedding_timeout = int(
                self.config_manager.get(CONFIG_EMBEDDING_TIMEOUT, DEFAULT_EMBEDDING_TIMEOUT)
            )
            self._draft.embedding_batch_size = int(
                self.config_manager.get(CONFIG_EMBEDDING_BATCH_SIZE, DEFAULT_EMBEDDING_BATCH_SIZE)
            )

        if not self._draft.embedding_provider and embedding_providers:
            self._draft.embedding_provider = embedding_providers[0].id
        self._sync_embedding_provider_state(preserve_selected_model=True)
        self.emit_state()

    def _sync_chat_provider_state(self, preserve_selected_model: bool) -> None:
        provider_id = self._draft.chat_provider
        provider = self._get_chat_provider(provider_id)
        model_names = self._get_chat_model_names(provider_id)
        current_model = self._draft.chat_model if preserve_selected_model else ""
        if current_model not in model_names:
            current_model = self._get_chat_default_model(provider_id)
        self._draft.chat_model = current_model
        if provider:
            default_base_url = provider.base_url or ""
            if not self._draft.chat_base_url.strip() or not preserve_selected_model:
                self._draft.chat_base_url = default_base_url
            if self.credential_manager and self._chat_provider_requires_api_key():
                self._draft.chat_api_key = self.credential_manager.get_llm_api_key(provider_id)
        supports_thinking = self._provider_supports_thinking(provider_id, self._draft.chat_model)
        if not supports_thinking:
            self._draft.chat_enable_thinking = False
        self._refresh_chat_validation_status()

    def _sync_embedding_provider_state(self, preserve_selected_model: bool) -> None:
        provider_id = self._draft.embedding_provider
        provider = self._get_embedding_provider(provider_id)
        model_names = self._get_embedding_model_names(provider_id)
        current_model = self._draft.embedding_model if preserve_selected_model else ""
        if current_model not in model_names:
            current_model = self._get_embedding_default_model(provider_id)
        self._draft.embedding_model = current_model
        if provider:
            default_base_url = provider.base_url or ""
            if not self._draft.embedding_base_url.strip() or not preserve_selected_model:
                self._draft.embedding_base_url = default_base_url
            if self.credential_manager and self._embedding_provider_requires_api_key():
                self._draft.embedding_api_key = self.credential_manager.get_embedding_api_key(provider_id)
        self._refresh_embedding_validation_status()

    def update_draft(self, section: str, field: str, value: Any) -> None:
        normalized_section = str(section or "").strip().lower()
        normalized_field = str(field or "").strip()
        if not normalized_section or not normalized_field:
            return

        prefix = "chat_" if normalized_section == "chat" else "embedding_"
        attr_name = f"{prefix}{self._camel_to_snake(normalized_field)}"
        if not hasattr(self._draft, attr_name):
            return

        typed_value = value
        current_value = getattr(self._draft, attr_name)
        if isinstance(current_value, bool):
            typed_value = bool(value)
        elif isinstance(current_value, int):
            try:
                typed_value = int(value)
            except Exception:
                typed_value = current_value
        elif value is None:
            typed_value = ""
        else:
            typed_value = str(value)

        setattr(self._draft, attr_name, typed_value)

        if normalized_section == "chat":
            if normalized_field == "provider":
                self._draft.chat_base_url = ""
                self._draft.chat_model = ""
                self._sync_chat_provider_state(preserve_selected_model=False)
            elif normalized_field == "model":
                if not self._provider_supports_thinking(self._draft.chat_provider, self._draft.chat_model):
                    self._draft.chat_enable_thinking = False
            elif normalized_field == "apiKey":
                self._refresh_chat_validation_status()
        elif normalized_section == "embedding":
            if normalized_field == "provider":
                self._draft.embedding_base_url = ""
                self._draft.embedding_model = ""
                self._sync_embedding_provider_state(preserve_selected_model=False)
            elif normalized_field == "apiKey":
                self._refresh_embedding_validation_status()

        self.emit_state()

    def select_tab(self, tab_id: str) -> None:
        self._draft.active_tab = "embedding" if tab_id == "embedding" else "chat"
        self.emit_state()

    def request_test_connection(self) -> None:
        if self._draft.active_tab == "embedding":
            self._request_embedding_connection_test()
            return
        self._request_chat_connection_test()

    def _request_chat_connection_test(self) -> None:
        api_key = self._draft.chat_api_key.strip()
        if self._chat_provider_requires_api_key() and not api_key:
            self._show_notice(
                self._get_text(
                    "dialog.model_config.error.no_api_key",
                    "Please enter an API Key first.",
                ),
                title=self._get_text("dialog.warning", "Warning"),
                tone="error",
            )
            return

        self._draft.chat_validation_status = "testing"
        self._draft.chat_validation_message = ""
        self.emit_state()
        QTimer.singleShot(100, self._perform_chat_connection_test)

    def _request_embedding_connection_test(self) -> None:
        if self._embedding_provider_requires_api_key() and not self._draft.embedding_api_key.strip():
            self._show_notice(
                self._get_text(
                    "dialog.model_config.error.no_embedding_api_key",
                    "Please enter an embedding API Key first.",
                ),
                title=self._get_text("dialog.warning", "Warning"),
                tone="error",
            )
            return

        self._draft.embedding_validation_status = "testing"
        self._draft.embedding_validation_message = ""
        self.emit_state()
        QTimer.singleShot(100, self._perform_embedding_connection_test)

    def _perform_chat_connection_test(self) -> None:
        api_key = self._draft.chat_api_key.strip()
        provider_id = self._draft.chat_provider
        if (self._chat_provider_requires_api_key() and not api_key) or not provider_id:
            self._refresh_chat_validation_status()
            self.emit_state()
            return

        try:
            client = LLMClientFactory.create_client(
                provider_id=provider_id,
                api_key=api_key,
                base_url=self._draft.chat_base_url.strip() or None,
                model=self._draft.chat_model.strip() or None,
                timeout=self._draft.chat_timeout,
            )
            response = client.chat(
                messages=[{"role": "user", "content": "Hi"}],
                streaming=False,
                thinking=False,
            )
            success = bool(response.content or response.tool_calls is not None)
            if success:
                self._draft.chat_validation_status = "verified"
                self._draft.chat_validation_message = ""
                self._save_chat_verification_timestamp(provider_id)
            else:
                self._draft.chat_validation_status = "failed"
                self._draft.chat_validation_message = ""
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Chat connection test failed: {exc}")
            self._draft.chat_validation_status = "failed"
            self._draft.chat_validation_message = str(exc)
        self.emit_state()

    def _perform_embedding_connection_test(self) -> None:
        provider_id = self._draft.embedding_provider.strip()
        if not provider_id:
            self._refresh_embedding_validation_status()
            self.emit_state()
            return

        try:
            if provider_id != "zhipu":
                raise RuntimeError(
                    self._get_text(
                        "dialog.model_config.error.embedding_test_not_supported",
                        "Embedding connection testing is not implemented for this provider yet.",
                    )
                )
            headers = {}
            api_key = self._draft.embedding_api_key.strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = httpx.post(
                self._draft.embedding_base_url.strip() or None,
                headers=headers,
                json={
                    "input": ["ping"],
                    "model": self._draft.embedding_model.strip() or None,
                },
                timeout=max(1, int(self._draft.embedding_timeout or DEFAULT_EMBEDDING_TIMEOUT)),
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            first_item = items[0] if items else None
            embedding = first_item.get("embedding") if isinstance(first_item, dict) else None
            if not isinstance(embedding, list) or not embedding:
                raise RuntimeError(
                    self._get_text(
                        "dialog.model_config.error.invalid_embedding_response",
                        "Embedding API returned an invalid response.",
                    )
                )
            self._draft.embedding_validation_status = "verified"
            self._draft.embedding_validation_message = ""
            self._save_embedding_verification_timestamp(provider_id)
        except Exception as exc:
            if self.logger:
                self.logger.error(f"Embedding connection test failed: {exc}")
            self._draft.embedding_validation_status = "failed"
            self._draft.embedding_validation_message = str(exc)
        self.emit_state()

    def request_save(self) -> None:
        validation_error = self._validate()
        if validation_error:
            self._show_notice(
                validation_error,
                title=self._get_text("dialog.warning", "Warning"),
                tone="error",
            )
            return
        confirmation_message = self._build_unverified_save_confirmation_message()
        if confirmation_message:
            self._show_confirm(
                kind="model_config_save_without_verify",
                title=self._get_text("dialog.confirm", "Confirm"),
                message=confirmation_message,
                confirm_label=self._get_text("btn.save", "Save"),
                cancel_label=self._get_text("btn.cancel", "Cancel"),
            )
            return
        self._commit_save()

    def confirm_save_without_verify(self) -> None:
        self._commit_save()

    def _build_unverified_save_confirmation_message(self) -> str:
        unverified_targets: List[str] = []
        if self._chat_provider_requires_api_key() and self._draft.chat_validation_status != "verified":
            unverified_targets.append("chat")
        if self._embedding_provider_requires_api_key() and self._draft.embedding_validation_status != "verified":
            unverified_targets.append("embedding")
        if not unverified_targets:
            return ""
        if len(unverified_targets) > 1:
            return self._get_text(
                "dialog.model_config.save_multiple_without_verify",
                "One or more API keys have not been verified. Save anyway?",
            )
        if unverified_targets[0] == "embedding":
            return self._get_text(
                "dialog.model_config.save_embedding_without_verify",
                "Embedding API Key has not been verified. Save anyway?",
            )
        return self._get_text(
            "dialog.model_config.save_without_verify",
            "API Key has not been verified. Save anyway?",
        )

    def _validate(self) -> Optional[str]:
        if not self._draft.chat_provider:
            return self._get_text(
                "dialog.model_config.error.no_provider",
                "Please select a chat provider.",
            )
        if not self._draft.chat_model:
            return self._get_text(
                "dialog.model_config.error.no_model",
                "Please select a model.",
            )
        if self._chat_provider_requires_api_key() and not self._draft.chat_api_key.strip():
            return self._get_text(
                "dialog.model_config.error.no_api_key",
                "Please enter an API Key first.",
            )
        if not self._draft.embedding_provider:
            return self._get_text(
                "dialog.model_config.error.no_embedding_provider",
                "Please select an embedding provider.",
            )
        if not self._draft.embedding_model:
            return self._get_text(
                "dialog.model_config.error.no_embedding_model",
                "Please select an embedding model.",
            )
        if self._embedding_provider_requires_api_key() and not self._draft.embedding_api_key.strip():
            return self._get_text(
                "dialog.model_config.error.no_embedding_api_key",
                "Please enter an embedding API Key first.",
            )
        return None

    def _commit_save(self) -> None:
        if not self.llm_runtime_config_manager or not self.config_manager:
            self._show_notice(
                self._get_text(
                    "dialog.model_config.error.missing_services",
                    "Model configuration services are unavailable.",
                ),
                title=self._get_text("dialog.error", "Error"),
                tone="error",
            )
            return

        validation_error = self._validate()
        if validation_error:
            self._show_notice(
                validation_error,
                title=self._get_text("dialog.warning", "Warning"),
                tone="error",
            )
            return

        previous_active_config = self.llm_runtime_config_manager.resolve_active_config()
        previous_model_id = previous_active_config.model_id

        try:
            self.llm_runtime_config_manager.save_active_chat_config(
                provider_id=self._draft.chat_provider,
                model_name=self._draft.chat_model,
                base_url=self._draft.chat_base_url.strip(),
                timeout=self._draft.chat_timeout,
                streaming=self._draft.chat_streaming,
                enable_thinking=self._draft.chat_enable_thinking,
                thinking_timeout=self._draft.chat_thinking_timeout,
                api_key=self._draft.chat_api_key.strip(),
            )
            self.config_manager.set(CONFIG_EMBEDDING_PROVIDER, self._draft.embedding_provider)
            self.config_manager.set(CONFIG_EMBEDDING_MODEL, self._draft.embedding_model)
            self.config_manager.set(CONFIG_EMBEDDING_BASE_URL, self._draft.embedding_base_url.strip())
            self.config_manager.set(CONFIG_EMBEDDING_TIMEOUT, self._draft.embedding_timeout)
            self.config_manager.set(CONFIG_EMBEDDING_BATCH_SIZE, self._draft.embedding_batch_size)
            embedding_api_key = self._draft.embedding_api_key.strip()
            if self.credential_manager and embedding_api_key:
                self.credential_manager.set_embedding_api_key(
                    self._draft.embedding_provider,
                    embedding_api_key,
                )
            elif self.credential_manager:
                self.credential_manager.delete_credential(
                    CREDENTIAL_TYPE_EMBEDDING,
                    self._draft.embedding_provider,
                )
            if self.event_bus:
                self.event_bus.publish(
                    EVENT_LLM_CONFIG_CHANGED,
                    data={
                        "old_model_id": previous_model_id,
                    },
                    source="model_config_surface",
                )
            if callable(self.on_close_requested):
                self.on_close_requested()
        except Exception as exc:
            if self.logger:
                self.logger.error(f"保存模型配置失败: {exc}")
            self._show_notice(
                str(exc),
                title=self._get_text("dialog.error", "Error"),
                tone="error",
            )
            self.emit_state()

    def _show_confirm(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        confirm_label: str,
        cancel_label: str,
        tone: str = "normal",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if callable(self.on_confirm_requested):
            self.on_confirm_requested(
                kind=kind,
                title=title,
                message=message,
                confirm_label=confirm_label,
                cancel_label=cancel_label,
                tone=tone,
                payload=payload,
            )

    def _show_notice(self, message: str, *, title: str = "", tone: str = "info") -> None:
        if callable(self.on_notice_requested):
            self.on_notice_requested(message, title=title, tone=tone)

    def emit_state(self) -> None:
        if callable(self.on_state_changed):
            self.on_state_changed(self.serialize_state())

    def serialize_state(self) -> Dict[str, Any]:
        chat_providers = self._list_chat_providers()
        embedding_providers = self._list_embedding_providers()
        chat_models = self._get_chat_model_names(self._draft.chat_provider)
        embedding_models = self._get_embedding_model_names(self._draft.embedding_provider)
        chat_provider = self._get_chat_provider(self._draft.chat_provider)
        embedding_provider = self._get_embedding_provider(self._draft.embedding_provider)
        supports_thinking = self._provider_supports_thinking(
            self._draft.chat_provider,
            self._draft.chat_model,
        )
        status_state, status_text = self._get_active_status()
        return self._serializer.serialize(
            draft=self._draft,
            chat_providers=chat_providers,
            embedding_providers=embedding_providers,
            chat_models=chat_models,
            embedding_models=embedding_models,
            chat_provider=chat_provider,
            embedding_provider=embedding_provider,
            supports_thinking=supports_thinking,
            status_state=status_state,
            status_text=status_text,
        )

    def _get_active_status(self) -> tuple[str, str]:
        if self._draft.active_tab == "embedding":
            return self._format_status(
                self._draft.embedding_validation_status,
                self._draft.embedding_validation_message,
            )
        return self._format_status(
            self._draft.chat_validation_status,
            self._draft.chat_validation_message,
        )

    def _format_status(self, status: str, message: str) -> tuple[str, str]:
        normalized_status = status if status in {"testing", "verified", "failed"} else "not_verified"
        if normalized_status == "testing":
            return normalized_status, self._get_text(
                "dialog.model_config.status.testing",
                "Testing...",
            )
        if normalized_status == "verified":
            return normalized_status, self._get_text(
                "dialog.model_config.status.verified",
                "Connection successful",
            )
        if normalized_status == "failed":
            error_text = self._get_text(
                "dialog.model_config.status.failed",
                "Connection failed",
            )
            if message:
                error_text = f"{error_text}: {message}"
            return normalized_status, error_text
        return "not_verified", self._get_text(
            "dialog.model_config.status.not_verified",
            "Not verified",
        )

    @staticmethod
    def _camel_to_snake(value: str) -> str:
        characters: List[str] = []
        for index, char in enumerate(value):
            if char.isupper() and index > 0:
                characters.append("_")
            characters.append(char.lower())
        return "".join(characters)


__all__ = [
    "ModelConfigController",
    "ModelConfigDraft",
]
