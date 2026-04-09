import mimetypes
from pathlib import Path, PurePosixPath
from typing import Optional

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QUrl

try:
    from PyQt6.QtWebEngineCore import (
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestJob,
        QWebEngineUrlScheme,
        QWebEngineUrlSchemeHandler,
    )
    WEB_RESOURCE_HOST_AVAILABLE = True
except ImportError:
    QWebEngineProfile = None
    QWebEngineSettings = None
    QWebEngineUrlRequestJob = None
    QWebEngineUrlScheme = None
    QWebEngineUrlSchemeHandler = None
    WEB_RESOURCE_HOST_AVAILABLE = False

_AppWebResourceHandlerBase = QWebEngineUrlSchemeHandler if QWebEngineUrlSchemeHandler is not None else object

from resources.resource_loader import get_resources_dir

APP_WEB_SCHEME = "cai"
APP_WEB_SCHEME_BYTES = APP_WEB_SCHEME.encode("ascii")
APP_WEB_HOST = "app"

_registered = False
_installed_profile = None
_installed_handler = None


def register_app_web_scheme() -> bool:
    global _registered
    if _registered or not WEB_RESOURCE_HOST_AVAILABLE:
        return _registered
    scheme = QWebEngineUrlScheme(APP_WEB_SCHEME_BYTES)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.FetchApiAllowed
        | QWebEngineUrlScheme.Flag.ServiceWorkersAllowed
        | QWebEngineUrlScheme.Flag.ViewSourceAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _registered = True
    return True


class _AppWebResourceHandler(_AppWebResourceHandlerBase):
    def requestStarted(self, job) -> None:
        resource_path = _resolve_resource_path(job.requestUrl())
        if resource_path is None or not resource_path.is_file():
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        try:
            content = resource_path.read_bytes()
        except Exception:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return
        buffer = QBuffer(job)
        buffer.setData(QByteArray(content))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(_content_type_for_path(resource_path).encode("utf-8"), buffer)


def install_app_web_resource_handler(profile=None) -> bool:
    global _installed_profile, _installed_handler
    if not register_app_web_scheme() or QWebEngineProfile is None:
        return False
    target_profile = profile or QWebEngineProfile.defaultProfile()
    if target_profile is None:
        return False
    if _installed_profile is target_profile and _installed_handler is not None:
        return True
    handler = _AppWebResourceHandler(target_profile)
    target_profile.installUrlSchemeHandler(APP_WEB_SCHEME_BYTES, handler)
    _installed_profile = target_profile
    _installed_handler = handler
    return True


def app_resource_url(relative_path: str) -> QUrl:
    normalized_path = _normalize_relative_resource_path(relative_path)
    return QUrl(f"{APP_WEB_SCHEME}://{APP_WEB_HOST}/{normalized_path}")


def configure_app_web_view(web_view) -> None:
    if web_view is None or QWebEngineSettings is None:
        return
    settings = web_view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    scroll_animator_attr = getattr(QWebEngineSettings.WebAttribute, "ScrollAnimatorEnabled", None)
    if scroll_animator_attr is not None:
        settings.setAttribute(scroll_animator_attr, True)


def _normalize_relative_resource_path(relative_path: str) -> str:
    path = PurePosixPath(str(relative_path or "").replace("\\", "/"))
    parts = [part for part in path.parts if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Invalid resource path: {relative_path}")
    return "/".join(parts)


def _resolve_resource_path(url: QUrl) -> Optional[Path]:
    if url.scheme() != APP_WEB_SCHEME or url.host() != APP_WEB_HOST:
        return None
    try:
        relative_path = _normalize_relative_resource_path(url.path().lstrip("/"))
    except ValueError:
        return None
    resources_dir = get_resources_dir().resolve()
    resolved_path = (resources_dir / relative_path).resolve()
    try:
        if resolved_path.is_relative_to(resources_dir):
            return resolved_path
    except AttributeError:
        if str(resolved_path).startswith(str(resources_dir)):
            return resolved_path
    return None


def _content_type_for_path(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type:
        return mime_type
    suffix = path.suffix.lower()
    if suffix == ".js":
        return "application/javascript"
    if suffix == ".mjs":
        return "application/javascript"
    if suffix == ".html":
        return "text/html"
    if suffix == ".css":
        return "text/css"
    if suffix == ".json":
        return "application/json"
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".woff2":
        return "font/woff2"
    return "application/octet-stream"


__all__ = [
    "APP_WEB_HOST",
    "APP_WEB_SCHEME",
    "WEB_RESOURCE_HOST_AVAILABLE",
    "app_resource_url",
    "configure_app_web_view",
    "install_app_web_resource_handler",
    "register_app_web_scheme",
]
