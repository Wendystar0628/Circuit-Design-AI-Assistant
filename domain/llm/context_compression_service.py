from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
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
        # ContextCompressor exposes these tuning hints for generic summarizers,
        # but BaseLLMClient intentionally accepts only its explicit portable
        # chat contract.  Do not leak unsupported wire options into providers.
        del max_tokens, temperature
        response = await asyncio.to_thread(
            self._client.chat,
            messages=[{"role": "user", "content": prompt}],
            model=self._model,
            streaming=False,
            tools=None,
            thinking=False,
        )
        finish_reason = getattr(response, "finish_reason", None)
        raw_finish_reason = "" if finish_reason is None else str(finish_reason).strip()
        normalized_reason = (
            raw_finish_reason.casefold().replace("-", "_")
        )
        if normalized_reason not in {"", "stop", "end_turn"}:
            raise ValueError(
                "Compression summary response ended with an unusable "
                f"finish_reason={finish_reason!r}"
            )
        return {
            "content": getattr(response, "content", "") or "",
            "usage": getattr(response, "usage", None) or {},
            "finish_reason": finish_reason,
        }


@dataclass(frozen=True)
class _CompressionOperationIdentity:
    """Immutable owner identity captured before an asynchronous compression."""

    project_root: str
    session_id: str
    state_signature: str
    generation: int


class ContextCompressionService:
    def __init__(self):
        self._logger = None
        self._context_manager = None
        self._session_state_manager = None
        self._config_manager = None
        self._event_bus = None
        self._compressor = ContextCompressor()
        self._lock = asyncio.Lock()
        self._operation_generation = 0
        self._compression_tasks: set[asyncio.Task] = set()
        self._events_subscribed = False

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
        provider = ""
        model = ""
        if self.llm_runtime_config_manager:
            try:
                active_config = self.llm_runtime_config_manager.resolve_active_config()
                provider = active_config.provider or provider
                model = active_config.model or model
            except Exception:
                pass

        if not provider or not model:
            try:
                from shared.model_registry import ModelRegistry

                default_provider = ModelRegistry.get_default_provider()
                if default_provider and not provider:
                    provider = default_provider.id

                if provider and not model:
                    default_model = ModelRegistry.get_default_model(provider)
                    if default_model:
                        model = default_model.name
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

    def _capture_operation_identity(
        self,
        state: Dict[str, Any],
    ) -> _CompressionOperationIdentity:
        """Capture authoritative session/project identity plus state revision."""

        manager = self.session_state_manager
        project_root = ""
        session_id = ""
        if manager is not None:
            try:
                project_root = manager.get_project_root() or ""
                session_id = manager.get_current_session_id() or ""
            except Exception:
                pass
        project_root = project_root or str(state.get("project_root", "") or "")
        session_id = session_id or str(state.get("session_id", "") or "")
        return _CompressionOperationIdentity(
            project_root=self._normalize_project_root(project_root),
            session_id=session_id,
            state_signature=self._build_state_signature(state),
            generation=self._operation_generation,
        )

    def _is_operation_current(
        self,
        identity: _CompressionOperationIdentity,
        current_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if identity.generation != self._operation_generation:
            return False
        current_state = current_state if current_state is not None else self._get_current_state()
        current = self._capture_operation_identity(current_state)
        return (
            current.project_root == identity.project_root
            and current.session_id == identity.session_id
            and current.state_signature == identity.state_signature
        )

    @staticmethod
    def _normalize_project_root(project_root: str) -> str:
        if not project_root:
            return ""
        return os.path.normcase(os.path.normpath(os.path.abspath(project_root)))

    @property
    def is_compressing(self) -> bool:
        """Whether any manual/automatic compression task is still live."""

        return self._lock.locked() or any(
            not task.done() for task in tuple(self._compression_tasks)
        )

    def _track_task(self, task: Optional[asyncio.Task]) -> None:
        if task is None or task in self._compression_tasks:
            return
        self._compression_tasks.add(task)
        task.add_done_callback(self._on_compression_task_done)

    def _on_compression_task_done(self, task: asyncio.Task) -> None:
        self._compression_tasks.discard(task)
        # Scheduled auto-compression has no direct awaiter.  Retrieve its
        # terminal exception to avoid "Task exception was never retrieved".
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass

    def invalidate_for_context_change(self, reason: str = "context_changed") -> int:
        """Invalidate and cancel compression work owned by the old context."""

        self._operation_generation += 1
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None

        cancelled = 0
        for task in tuple(self._compression_tasks):
            if task is current_task or task.done():
                continue
            task.cancel()
            cancelled += 1
        if cancelled and self.logger:
            self.logger.info(
                "Invalidated %s compression task(s): %s",
                cancelled,
                reason,
            )
        return cancelled

    def _ensure_lifecycle_subscription(self) -> None:
        if self._events_subscribed or self.event_bus is None:
            return
        try:
            from shared.event_types import (
                EVENT_SESSION_CHANGED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_STATE_PROJECT_OPENED,
            )

            for event_type in (
                EVENT_SESSION_CHANGED,
                EVENT_STATE_PROJECT_CLOSED,
                EVENT_STATE_PROJECT_OPENED,
            ):
                self.event_bus.subscribe(event_type, self._on_context_changed)
            self._events_subscribed = True
        except Exception as exc:
            self.logger.warning(f"Failed to subscribe compression lifecycle: {exc}")

    def _on_context_changed(self, event_data: Dict[str, Any]) -> None:
        event_type = str(event_data.get("type", "") or "")
        data = event_data.get("data", event_data)
        action = str(data.get("action", "") or "") if isinstance(data, dict) else ""
        self.invalidate_for_context_change(action or event_type or "context_changed")

    def _build_budget_snapshot(
        self,
        state: Dict[str, Any],
        model: str,
        provider: str,
    ) -> Dict[str, Any]:
        usage = self.context_manager.calculate_usage(state, model, provider=provider) if self.context_manager else {}
        input_limit = usage.get("input_limit", 0)
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

    def schedule_auto_compress(
        self,
        source: str = "llm_turn_complete",
    ) -> Optional[asyncio.Task]:
        self._ensure_lifecycle_subscription()
        if self.is_compressing:
            return None
        try:
            task = asyncio.create_task(self.maybe_auto_compress(source=source))
            self._track_task(task)
            return task
        except Exception as exc:
            self.logger.warning(f"Failed to schedule auto compression: {exc}")
            return None

    async def _run_compression(
        self,
        keep_recent: Optional[int],
        mode: str,
        trigger_reason: str,
        source: str,
        force: bool,
    ) -> Dict[str, Any]:
        self._ensure_lifecycle_subscription()
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        self._track_task(current_task)
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
            operation_identity = self._capture_operation_identity(state)
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
            try:
                engine_result = await self._compressor.compress(
                    state,
                    adapter,
                    keep_recent=keep_recent,
                    context_limit=before["input_limit"],
                    model=model_info["model"],
                )
            except asyncio.CancelledError:
                # A session/project transition uses cancellation as a prompt
                # stop request.  Return a normal invalidated outcome to manual
                # UI callers; unrelated shutdown/task cancellation still
                # propagates through the regular asyncio contract.
                if operation_identity.generation != self._operation_generation:
                    return {
                        "status": "invalidated",
                        "mode": mode,
                        "trigger_reason": trigger_reason,
                        "source": source,
                        "keep_recent": keep_recent,
                        "error": "Compression context changed",
                    }
                raise
            current_state = self._get_current_state()
            if not self._is_operation_current(operation_identity, current_state):
                # A stale result must be completely silent: publishing even a
                # skipped/completed event after the UI has switched context can
                # cause the new conversation to reload or show old feedback.
                return {
                    "status": "invalidated",
                    "mode": mode,
                    "trigger_reason": trigger_reason,
                    "source": source,
                    "keep_recent": keep_recent,
                    "error": "Compression context changed",
                }
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
                "project_root": operation_identity.project_root,
                "session_id": operation_identity.session_id,
            }
            if status in {"completed", "suggest_new_conversation"}:
                # Recheck immediately at the commit boundary.  There is no
                # await between this check, sync_state and persistence.
                if not self._is_operation_current(operation_identity):
                    return {
                        "status": "invalidated",
                        "mode": mode,
                        "trigger_reason": trigger_reason,
                        "source": source,
                        "keep_recent": keep_recent,
                        "error": "Compression context changed before commit",
                    }
                manager = self.session_state_manager
                if manager is None:
                    payload["status"] = "failed"
                    payload["error"] = "SessionStateManager unavailable"
                    self._publish_result(payload)
                    return payload

                try:
                    # Persist the candidate state before installing it into the
                    # live ContextManager.  Persistence is part of the commit,
                    # not a best-effort side effect of a completed operation.
                    persisted = manager.save_current_session(
                        state=new_state,
                        project_root=operation_identity.project_root,
                        expected_session_id=operation_identity.session_id,
                    )
                except Exception as exc:
                    persisted = False
                    self.logger.warning(f"Failed to persist compressed session: {exc}")

                if not persisted:
                    # A persistence rejection can mean another thread changed
                    # the owning session/project after the last identity
                    # check.  The stale operation must stay silent and must not
                    # dirty the newly active conversation.
                    if not self._is_operation_current(operation_identity):
                        return {
                            "status": "invalidated",
                            "mode": mode,
                            "trigger_reason": trigger_reason,
                            "source": source,
                            "keep_recent": keep_recent,
                            "error": "Compression context changed during persistence",
                        }
                    try:
                        # SessionStateManager already retains dirty on a failed
                        # durable commit.  Keep this defensive call for custom
                        # managers/failure injectors that only report False.
                        manager.mark_dirty()
                    except Exception:
                        pass
                    payload["status"] = "failed"
                    payload["error"] = "Failed to persist compressed session"
                    self._publish_result(payload)
                    return payload

                # A synchronous persistence call may still race with a project
                # transition on another thread.  Its disk write belongs to the
                # captured session, but it must never install into a new live
                # session.
                if not self._is_operation_current(operation_identity):
                    return {
                        "status": "invalidated",
                        "mode": mode,
                        "trigger_reason": trigger_reason,
                        "source": source,
                        "keep_recent": keep_recent,
                        "error": "Compression context changed after persistence",
                    }

                try:
                    self.context_manager.sync_state(new_state)
                except Exception as exc:
                    try:
                        manager.mark_dirty()
                    except Exception:
                        pass
                    payload["status"] = "failed"
                    payload["error"] = f"Failed to install compressed state: {exc}"
                    self._publish_result(payload)
                    return payload
                if status == "completed" and COMPRESS_FALLBACK_NEW_CONVERSATION and after["usage_ratio"] >= COMPRESS_AUTO_THRESHOLD:
                    status = "suggest_new_conversation"
                    payload["status"] = status
            elif status == "failed":
                payload["error"] = engine_result.get("error", "Compression failed")
            elif status == "skipped":
                payload["error"] = engine_result.get("error", "No compressible history")
            self._publish_result(payload)
            return payload
