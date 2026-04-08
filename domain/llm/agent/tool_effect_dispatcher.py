from typing import Any, Dict, List, Optional


class ToolEffectDispatcher:
    def __init__(self, event_bus=None):
        self._event_bus = event_bus

    def dispatch(self, tool_name: str, effects: Optional[List[Dict[str, Any]]]) -> None:
        return None
