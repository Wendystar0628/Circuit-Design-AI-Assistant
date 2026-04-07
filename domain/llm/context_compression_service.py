from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, Optional

from domain.llm.context_compressor import ContextCompressor
from domain.llm.message_helpers import messages_to_dicts
from domain.llm.working_context_builder import (
    WORKING_CONTEXT_COMPRESSED_COUNT_KEY,
    WORKING_CONTEXT_KEEP_RECENT_KEY,
    WORKING_CONTEXT_SUMMARY_KEY,
    build_working_context_state,
)
from infrastructure.config.settings import (
    COMPRESS_AUTO_THRESHOLD,
    COMPRESS_FALLBACK_NEW_CONVERSATION,
    DEFAULT_KEEP_RECENT_MESSAGES,
)


class _CompressionLLMAdapter:
    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        response = await asyncio.to_thread(
            self._client.chat,
            messages=[{"role": "user", "content": prompt}],
            model=self._model,
            streaming=False,
            tools=None,
            thinking=False,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return {
            "content": getattr(response, "content", "") or "",
            "usage": getattr(response, "usage", None) or {},
        }


class ContextCompressionService:
    def __init__(self):
        self._logger = None
        self._context_manager = None
        self._session_state_manager = None
        self._config_manager = None
        self._event_bus = None
        self._compressor = ContextCompressor()
        self._lock = asyncio.Lock()

    @property
    def logger(self):
        if self._logger is None:
            try:
                from infrastructure.utils.logger import get_logger
                self._logger = get_logger("context_compression_service")
            except Exception:
                self._logger = logging.getLogger(__name__)
        return self._logger

    @property
    def context_manager(self):
        if self._context_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONTEXT_MANAGER
                self._context_manager = ServiceLocator.get_optional(SVC_CONTEXT_MANAGER)
            except Exception:
                pass
        return self._context_manager

    @property
    def session_state_manager(self):
        if self._session_state_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_SESSION_STATE_MANAGER
                self._session_state_manager = ServiceLocator.get_optional(SVC_SESSION_STATE_MANAGER)
            except Exception:
                pass
        return self._session_state_manager

    @property
    def config_manager(self):
        if self._config_manager is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_CONFIG_MANAGER
                self._config_manager = ServiceLocator.get_optional(SVC_CONFIG_MANAGER)
            except Exception:
                pass
        return self._config_manager

    @property
    def event_bus(self):
        if self._event_bus is None:
            try:
                from shared.service_locator import ServiceLocator
                from shared.service_names import SVC_EVENT_BUS
                self._event_bus = ServiceLocator.get_optional(SVC_EVENT_BUS)
            except Exception:
                pass
        return self._event_bus

    @property
    def llm_client(self):
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_CLIENT
            return ServiceLocator.get_optional(SVC_LLM_CLIENT)
        except Exception:
            return None

    @property
    def llm_runtime_config_manager(self):
        try:
            from shared.service_locator import ServiceLocator
            from shared.service_names import SVC_LLM_RUNTIME_CONFIG_MANAGER
            return ServiceLocator.get_optional(SVC_LLM_RUNTIME_CONFIG_MANAGER)
        except Exception:
            return None

    def _resolve_model(self) -> Dict[str, str]:
        provider = "zhipu"
        model = "glm-5"
        if self.llm_runtime_config_manager:
            try:
                active_config = self.llm_runtime_config_manager.resolve_active_config()
                provider = active_config.provider or provider
                model = active_config.model or model
            except Exception:
                pass
        return {
            "provider": provider,
            "model": model,
            "model_id": f"{provider}:{model}",
        }

    def _get_current_state(self) -> Dict[str, Any]:
        if self.context_manager is None:
            return {}
        try:
            return self.context_manager.get_current_state() or {}
        except Exception:
            return {}

    def _build_state_signature(self, state: Dict[str, Any]) -> str:
        payload = {
            "messages": messages_to_dicts(state.get("messages", [])),
            WORKING_CONTEXT_SUMMARY_KEY: state.get(WORKING_CONTEXT_SUMMARY_KEY, ""),
            WORKING_CONTEXT_COMPRESSED_COUNT_KEY: state.get(WORKING_CONTEXT_COMPRESSED_COUNT_KEY, 0),
            WORKING_CONTEXT_KEEP_RECENT_KEY: state.get(WORKING_CONTEXT_KEEP_RECENT_KEY, 0),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _build_budget_snapshot(
        self,
        state: Dict[str, Any],
        model: str,
        provider: str,
    ) -> Dict[str, Any]:
        usage = self.context_manager.calculate_usage(state, model) if self.context_manager else {}
        input_limit = max(0, usage.get("context_limit", 0) - usage.get("output_reserve", 0))
        return {
            "provider": provider,
            "model": model,
            "model_id": f"{provider}:{model}",
            "history_message_count": usage.get("history_message_count", len(state.get("messages", []))),
            "working_message_count": usage.get("working_message_count", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "message_tokens": usage.get("message_tokens", 0),
            "summary_tokens": usage.get("summary_tokens", 0),
            "context_limit": usage.get("context_limit", 0),
            "output_reserve": usage.get("output_reserve", 0),
            "input_limit": input_limit,
            "available": usage.get("available", 0),
            "usage_ratio": usage.get("usage_ratio", 0.0),
        }

    def _publish_result(self, payload: Dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        try:
            from shared.event_types import EVENT_CONTEXT_COMPRESS_COMPLETE
            self.event_bus.publish(
                EVENT_CONTEXT_COMPRESS_COMPLETE,
                payload,
                source="context_compression_service",
            )
        except Exception as exc:
            self.logger.warning(f"Failed to publish compression result: {exc}")

    def create_preview(
        self,
        keep_recent: Optional[int] = None,
        reason: str = "manual",
    ) -> Dict[str, Any]:
        state = self._get_current_state()
        model_info = self._resolve_model()
        keep_recent = keep_recent or DEFAULT_KEEP_RECENT_MESSAGES
        budget = self._build_budget_snapshot(state, model_info["model"], model_info["provider"])
        preview = self._compressor.generate_compress_preview(
            state,
            keep_recent=keep_recent,
            model=model_info["model"],
        )
        preview_state = build_working_context_state(
            state,
            summary=preview.summary_preview,
            compressed_count=preview.compressed_message_count,
            keep_recent=keep_recent,
        )
        after_budget = self._build_budget_snapshot(preview_state, model_info["model"], model_info["provider"])
        categories = self.context_manager.classify_messages(state) if self.context_manager else {}
        return {
            "status": "ready",
            "reason": reason,
            "keep_recent": keep_recent,
            "budget": budget,
            "summary_preview": preview.summary_preview,
            "estimated": {
                "summarized_count": len(preview.messages_to_summarize),
                "direct_count": len(preview.direct_messages_after_compress),
                "saved_tokens": preview.estimated_tokens_saved,
                "summary_tokens": after_budget.get("summary_tokens", 0),
                "after_tokens": after_budget.get("total_tokens", 0),
                "after_ratio": after_budget.get("usage_ratio", 0.0),
            },
            "classification": {
                "high": len(categories.get("high", [])),
                "medium": len(categories.get("medium", [])),
                "low": len(categories.get("low", [])),
            },
        }

    async def apply_manual_compression(
        self,
        keep_recent: Optional[int] = None,
        source: str = "context_compress_dialog",
    ) -> Dict[str, Any]:
        return await self._run_compression(
            keep_recent=keep_recent,
            mode="manual",
            trigger_reason="manual",
            source=source,
            force=True,
        )

    async def maybe_auto_compress(
        self,
        source: str = "llm_turn_complete",
    ) -> Optional[Dict[str, Any]]:
        state = self._get_current_state()
        model_info = self._resolve_model()
        budget = self._build_budget_snapshot(state, model_info["model"], model_info["provider"])
        if budget["usage_ratio"] < COMPRESS_AUTO_THRESHOLD:
            return None
        return await self._run_compression(
            keep_recent=DEFAULT_KEEP_RECENT_MESSAGES,
            mode="auto",
            trigger_reason="usage_threshold",
            source=source,
            force=False,
        )

    def schedule_auto_compress(self, source: str = "llm_turn_complete") -> None:
        try:
            asyncio.create_task(self.maybe_auto_compress(source=source))
        except Exception as exc:
            self.logger.warning(f"Failed to schedule auto compression: {exc}")

    async def _run_compression(
        self,
        keep_recent: Optional[int],
        mode: str,
        trigger_reason: str,
        source: str,
        force: bool,
    ) -> Dict[str, Any]:
        if self.context_manager is None:
            result = {
                "status": "failed",
                "mode": mode,
                "trigger_reason": trigger_reason,
                "source": source,
                "error": "ContextManager unavailable",
            }
            self._publish_result(result)
            return result
        if self.llm_client is None:
            result = {
                "status": "failed",
                "mode": mode,
                "trigger_reason": trigger_reason,
                "source": source,
                "error": "LLM client unavailable",
            }
            self._publish_result(result)
            return result
        keep_recent = keep_recent or DEFAULT_KEEP_RECENT_MESSAGES
        async with self._lock:
            state = self._get_current_state()
            state_signature = self._build_state_signature(state)
            model_info = self._resolve_model()
            before = self._build_budget_snapshot(state, model_info["model"], model_info["provider"])
            if not force and before["usage_ratio"] < COMPRESS_AUTO_THRESHOLD:
                return {
                    "status": "skipped",
                    "mode": mode,
                    "trigger_reason": trigger_reason,
                    "source": source,
                }
            adapter = _CompressionLLMAdapter(self.llm_client, model_info["model"])
            engine_result = await self._compressor.compress(
                state,
                adapter,
                keep_recent=keep_recent,
                context_limit=before["input_limit"],
                model=model_info["model"],
            )
            current_state = self._get_current_state()
            if self._build_state_signature(current_state) != state_signature:
                result = {
                    "status": "skipped",
                    "mode": mode,
                    "trigger_reason": trigger_reason,
                    "source": source,
                    "keep_recent": keep_recent,
                    "error": "Conversation changed during compression",
                }
                if mode == "manual":
                    self._publish_result(result)
                return result
            new_state = engine_result.get("state", state)
            status = engine_result.get("status", "failed")
            after = self._build_budget_snapshot(new_state, model_info["model"], model_info["provider"])
            payload = {
                "status": status,
                "mode": mode,
                "trigger_reason": trigger_reason,
                "source": source,
                "keep_recent": keep_recent,
                "before_tokens": before["total_tokens"],
                "after_tokens": after["total_tokens"],
                "before_ratio": before["usage_ratio"],
                "after_ratio": after["usage_ratio"],
                "saved_tokens": max(0, before["total_tokens"] - after["total_tokens"]),
                "before_history_message_count": before["history_message_count"],
                "after_history_message_count": after["history_message_count"],
                "before_working_message_count": before["working_message_count"],
                "after_working_message_count": after["working_message_count"],
                "summary_tokens": after["summary_tokens"],
                "model": model_info["model"],
                "provider": model_info["provider"],
                "model_id": model_info["model_id"],
            }
            if status in {"completed", "suggest_new_conversation"}:
                self.context_manager.sync_state(new_state)
                if self.session_state_manager:
                    try:
                        self.session_state_manager.mark_dirty()
                        self.session_state_manager.save_current_session()
                    except Exception as exc:
                        self.logger.warning(f"Failed to persist compressed session: {exc}")
                if status == "completed" and COMPRESS_FALLBACK_NEW_CONVERSATION and after["usage_ratio"] >= COMPRESS_AUTO_THRESHOLD:
                    status = "suggest_new_conversation"
                    payload["status"] = status
            elif status == "failed":
                payload["error"] = engine_result.get("error", "Compression failed")
            elif status == "skipped":
                payload["error"] = engine_result.get("error", "No compressible history")
            self._publish_result(payload)
            return payload
