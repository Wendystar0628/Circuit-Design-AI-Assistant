import os
from typing import Iterable, Optional, Set

from shared.path_utils import normalize_absolute_path, normalize_identity_path


class WorkspaceExplorerStateStore:
    _CONFIG_KEY = "workspace_explorer_state"

    def __init__(self):
        self._config_manager = None

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

    def load_expanded_directories(self, project_root: Optional[str]) -> Set[str]:
        absolute_root = self._normalize_absolute_root(project_root)
        identity_root = self._normalize_identity_root(project_root)
        if absolute_root is None or identity_root is None or self.config_manager is None:
            return set()
        raw_state = self.config_manager.get(self._CONFIG_KEY, {})
        if not isinstance(raw_state, dict):
            return set()
        project_state = raw_state.get(identity_root, {})
        if not isinstance(project_state, dict):
            return set()
        raw_paths = project_state.get("expanded_directories", [])
        if not isinstance(raw_paths, list):
            return set()
        expanded: Set[str] = set()
        for raw_path in raw_paths:
            relative_path = self._normalize_relative_path(raw_path)
            if relative_path is None:
                continue
            expanded.add(normalize_identity_path(os.path.join(absolute_root, relative_path)))
        return expanded

    def save_expanded_directories(self, project_root: Optional[str], expanded_directory_paths: Iterable[str]) -> None:
        absolute_root = self._normalize_absolute_root(project_root)
        identity_root = self._normalize_identity_root(project_root)
        if absolute_root is None or identity_root is None or self.config_manager is None:
            return
        raw_state = self.config_manager.get(self._CONFIG_KEY, {})
        next_state = dict(raw_state) if isinstance(raw_state, dict) else {}
        next_state[identity_root] = {
            "expanded_directories": self._serialize_relative_paths(absolute_root, expanded_directory_paths),
        }
        self.config_manager.set(self._CONFIG_KEY, next_state)

    def _normalize_absolute_root(self, project_root: Optional[str]) -> Optional[str]:
        value = str(project_root or "").strip()
        if not value:
            return None
        return normalize_absolute_path(value)

    def _normalize_identity_root(self, project_root: Optional[str]) -> Optional[str]:
        value = str(project_root or "").strip()
        if not value:
            return None
        return normalize_identity_path(value)

    def _normalize_relative_path(self, value: object) -> Optional[str]:
        text = str(value or "").strip().replace("\\", "/")
        if not text or text in {".", "/"}:
            return None
        return text

    def _serialize_relative_paths(self, absolute_root: str, expanded_directory_paths: Iterable[str]) -> list[str]:
        identity_root = normalize_identity_path(absolute_root)
        relative_paths: set[str] = set()
        for raw_path in expanded_directory_paths:
            absolute_path = normalize_absolute_path(str(raw_path or ""))
            identity_path = normalize_identity_path(absolute_path)
            try:
                if os.path.commonpath([identity_root, identity_path]) != identity_root:
                    continue
            except ValueError:
                continue
            try:
                relative_path = os.path.relpath(absolute_path, absolute_root)
            except ValueError:
                continue
            normalized_relative_path = self._normalize_relative_path(relative_path)
            if normalized_relative_path is None:
                continue
            relative_paths.add(normalized_relative_path)
        return sorted(relative_paths)


__all__ = ["WorkspaceExplorerStateStore"]
