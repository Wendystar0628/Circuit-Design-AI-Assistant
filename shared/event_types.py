"""Canonical internal events for the headless application runtime.

Events coordinate long-lived domain services inside the Python sidecar. The
FastAPI adapter projects the subset needed by Electron onto the authenticated
WebSocket contract; renderer-specific actions are ordinary REST requests.
"""

# Project and configuration lifecycle.
EVENT_STATE_PROJECT_OPENED = "state_project_opened"
EVENT_STATE_PROJECT_CLOSED = "state_project_closed"
EVENT_STATE_CONFIG_CHANGED = "state_config_changed"
EVENT_PENDING_WORKSPACE_EDIT_STATE_CHANGED = "pending_workspace_edit_state_changed"
EVENT_METRIC_TARGET_STATE_CHANGED = "metric_target_state_changed"
EVENT_LLM_CONFIG_CHANGED = "llm_config_changed"

# Simulation lifecycle. SimulationJobManager is the sole publisher. Every
# payload carries job_id, origin, circuit_file, project_root, and session_id.
# Completion additionally carries result_path, export_root, and duration.
# Failure additionally carries error_message, cancelled, and duration.
EVENT_SIM_STARTED = "sim_started"
EVENT_SIM_COMPLETE = "sim_complete"
EVENT_SIM_ERROR = "sim_error"

# RAG lifecycle.
EVENT_RAG_INIT_COMPLETE = "rag.init_complete"
EVENT_RAG_INDEX_STARTED = "rag.index_started"
EVENT_RAG_INDEX_PROGRESS = "rag.index_progress"
EVENT_RAG_INDEX_COMPLETE = "rag.index_complete"
EVENT_RAG_INDEX_ERROR = "rag.index_error"
EVENT_RAG_QUERY_COMPLETE = "rag.query_complete"

# Conversation and workspace lifecycle.
EVENT_CONTEXT_COMPRESS_COMPLETE = "context_compress_complete"
EVENT_SESSION_CHANGED = "session_changed"
EVENT_WORKSPACE_SYNC_REQUIRED = "workspace_sync_required"

# Canonical disk-change event; payloads use shared.file_change.FileChange.
EVENT_FILE_CHANGED = "file_changed"

# Slow handlers for these identity-bearing lifecycle events are operationally
# significant and should be logged by EventBus.
CRITICAL_EVENTS = (
    EVENT_SIM_STARTED,
    EVENT_SIM_COMPLETE,
    EVENT_SIM_ERROR,
)

__all__ = [
    "EVENT_STATE_PROJECT_OPENED",
    "EVENT_STATE_PROJECT_CLOSED",
    "EVENT_STATE_CONFIG_CHANGED",
    "EVENT_PENDING_WORKSPACE_EDIT_STATE_CHANGED",
    "EVENT_METRIC_TARGET_STATE_CHANGED",
    "EVENT_LLM_CONFIG_CHANGED",
    "EVENT_SIM_STARTED",
    "EVENT_SIM_COMPLETE",
    "EVENT_SIM_ERROR",
    "EVENT_RAG_INIT_COMPLETE",
    "EVENT_RAG_INDEX_STARTED",
    "EVENT_RAG_INDEX_PROGRESS",
    "EVENT_RAG_INDEX_COMPLETE",
    "EVENT_RAG_INDEX_ERROR",
    "EVENT_RAG_QUERY_COMPLETE",
    "EVENT_CONTEXT_COMPRESS_COMPLETE",
    "EVENT_SESSION_CHANGED",
    "EVENT_WORKSPACE_SYNC_REQUIRED",
    "EVENT_FILE_CHANGED",
    "CRITICAL_EVENTS",
]
