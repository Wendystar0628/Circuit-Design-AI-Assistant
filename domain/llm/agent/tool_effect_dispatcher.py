import logging
from typing import Any, Dict, List, Optional

from shared.event_types import EVENT_AGENT_FILE_MODIFIED


class ToolEffectDispatcher:
    def __init__(self, event_bus=None):
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def dispatch(self, tool_name: str, effects: Optional[List[Dict[str, Any]]]) -> None:
        if self._event_bus is None or not effects:
            return

        for effect in effects:
            effect_type = effect.get("type", "")
            if effect_type == "file_modified":
                self._dispatch_file_modified(tool_name, effect)

    def _dispatch_file_modified(self, tool_name: str, effect: Dict[str, Any]) -> None:
        path = effect.get("path", "")
        if not path:
            return

        try:
            self._event_bus.publish(
                EVENT_AGENT_FILE_MODIFIED,
                {
                    "path": path,
                    "tool_name": tool_name,
                },
            )
        except Exception as e:
            self._logger.warning(f"Failed to dispatch file modification effect: {e}")
