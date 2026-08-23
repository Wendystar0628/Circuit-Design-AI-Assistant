"""Validation for provider API base URLs."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit


_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_base_url(value: str) -> str:
    """Return a trimmed absolute HTTP(S) base URL or raise ``ValueError``."""

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Base URL is required")
    if "\\" in normalized or any(character.isspace() for character in normalized):
        raise ValueError("Base URL must be an absolute HTTP(S) URL with a valid host")

    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "Base URL must be an absolute HTTP(S) URL with a valid host"
        ) from exc

    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise ValueError("Base URL must be an absolute HTTP(S) URL with a valid host")

    hostname = parsed.hostname.rstrip(".")
    if not hostname:
        raise ValueError("Base URL must be an absolute HTTP(S) URL with a valid host")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(
                "Base URL must be an absolute HTTP(S) URL with a valid host"
            ) from exc
        if len(ascii_hostname) > 253 or any(
            not _HOST_LABEL.fullmatch(label)
            for label in ascii_hostname.split(".")
        ):
            raise ValueError("Base URL must be an absolute HTTP(S) URL with a valid host")

    return normalized


__all__ = ["validate_base_url"]
