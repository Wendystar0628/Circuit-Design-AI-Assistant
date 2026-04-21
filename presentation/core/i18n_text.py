from typing import Optional


def get_i18n_text(key: str, default: Optional[str] = None) -> str:
    try:
        from shared.service_locator import ServiceLocator
        from shared.service_names import SVC_I18N_MANAGER

        manager = ServiceLocator.get_optional(SVC_I18N_MANAGER)
        if manager is not None:
            return manager.get_text(key, default)
    except Exception:
        pass
    return default if default is not None else key


__all__ = ["get_i18n_text"]
