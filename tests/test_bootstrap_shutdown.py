"""Regression tests for the explicit application shutdown order."""

from __future__ import annotations

import asyncio

from application import bootstrap
from shared.service_locator import ServiceLocator
from shared.service_names import (
    SVC_FILE_WATCHER,
    SVC_LLM_CLIENT,
    SVC_LLM_EXECUTOR,
    SVC_PROJECT_SERVICE,
    SVC_RAG_MANAGER,
    SVC_SESSION_STATE_PROJECTOR,
    SVC_SIMULATION_JOB_MANAGER,
)


def test_shutdown_settles_runtime_owners_before_async_runtime(monkeypatch):
    events: list[str] = []

    class SyncService:
        def __init__(self, event: str, method_name: str):
            setattr(self, method_name, lambda: events.append(event))

    class SimulationService:
        @staticmethod
        def close(timeout: float = 0.0) -> bool:
            assert timeout == 2.0
            events.append("simulation")
            return True

    class AsyncService:
        def __init__(self, event: str, method_name: str):
            async def lifecycle():
                events.append(event)

            setattr(self, method_name, lifecycle)

    class ProjectService:
        @staticmethod
        def is_project_open() -> bool:
            return True

        @staticmethod
        def close_project():
            events.append("project")
            return True, ""

    ServiceLocator.clear()
    try:
        ServiceLocator.register(
            SVC_FILE_WATCHER, SyncService("file_watcher", "stop_watching")
        )
        ServiceLocator.register(
            SVC_LLM_EXECUTOR, AsyncService("llm_executor", "shutdown")
        )
        ServiceLocator.register(
            SVC_SIMULATION_JOB_MANAGER, SimulationService()
        )
        ServiceLocator.register(SVC_RAG_MANAGER, SyncService("rag", "stop"))
        ServiceLocator.register(
            SVC_SESSION_STATE_PROJECTOR,
            SyncService("projector", "shutdown"),
        )
        ServiceLocator.register(SVC_PROJECT_SERVICE, ProjectService())
        ServiceLocator.register(
            SVC_LLM_CLIENT, AsyncService("llm_client", "close")
        )
        async def shutdown_async() -> None:
            events.append("async_runtime")

        monkeypatch.setattr("shared.async_runtime.shutdown_async", shutdown_async)

        asyncio.run(bootstrap._shutdown_services_async())
    finally:
        ServiceLocator.clear()

    assert events == [
        "llm_executor",
        "simulation",
        "project",
        "file_watcher",
        "projector",
        "rag",
        "llm_client",
        "async_runtime",
    ]


def test_shutdown_reports_rejected_project_close_before_tearing_down_watcher(
    monkeypatch,
):
    events: list[str] = []

    class ProjectService:
        @staticmethod
        def is_project_open() -> bool:
            return True

        @staticmethod
        def close_project():
            events.append("project_rejected")
            return False, "session save failed"

    class Watcher:
        @staticmethod
        def stop_watching() -> None:
            events.append("file_watcher")

    class Logger:
        def __init__(self) -> None:
            self.errors = []

        def error(self, message, *args) -> None:
            self.errors.append(message % args if args else message)

        def info(self, *_args) -> None:
            pass

        def warning(self, *_args) -> None:
            pass

    logger = Logger()
    monkeypatch.setattr(bootstrap, "_logger", logger)

    ServiceLocator.clear()
    try:
        ServiceLocator.register(SVC_PROJECT_SERVICE, ProjectService())
        ServiceLocator.register(SVC_FILE_WATCHER, Watcher())

        async def shutdown_async() -> None:
            events.append("async_runtime")

        monkeypatch.setattr("shared.async_runtime.shutdown_async", shutdown_async)
        asyncio.run(bootstrap._shutdown_services_async())
    finally:
        ServiceLocator.clear()

    assert events == ["project_rejected", "file_watcher", "async_runtime"]
    assert logger.errors == [
        "ProjectService 拒绝关闭项目，未清空 dirty 会话状态: session save failed"
    ]


def test_shutdown_failure_does_not_skip_remaining_services(monkeypatch):
    events: list[str] = []

    class BrokenWatcher:
        @staticmethod
        def stop_watching() -> None:
            events.append("broken_watcher")
            raise RuntimeError("watcher failure")

    class RagManager:
        @staticmethod
        def stop() -> None:
            events.append("rag")

    ServiceLocator.clear()
    try:
        ServiceLocator.register(SVC_FILE_WATCHER, BrokenWatcher())
        ServiceLocator.register(SVC_RAG_MANAGER, RagManager())

        async def shutdown_async() -> None:
            events.append("async_runtime")

        monkeypatch.setattr("shared.async_runtime.shutdown_async", shutdown_async)

        asyncio.run(bootstrap._shutdown_services_async())
    finally:
        ServiceLocator.clear()

    assert events == ["broken_watcher", "rag", "async_runtime"]
