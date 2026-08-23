"""DisplayMetric — the shared formatted metric row.

The UI, root-backed agent reader and manual exporter build this type without
depending on presentation widgets.

Each row is a fully-formatted value string, not raw numbers, so the
same objects can flow into the frontend table, temporary conversation
attachments and user-requested exports. Keep scoring and target evaluation off
this thin display record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DisplayMetric:
    """UI-friendly representation of a ``.MEASURE`` result.

    Fields match the frontend, agent readout and manual export columns.
    """

    name: str
    """Metric identifier (name from the ``.MEASURE`` statement)."""

    display_name: str
    """Localised display name."""

    value: str
    """Formatted numeric string, or empty when ``status`` is not ``OK``."""

    unit: str
    """Unit symbol (``dB`` / ``Hz`` / ``V`` / ...)."""

    status: str
    """Authoritative measurement outcome (``OK`` / ``FAILED`` / ``PARSE_ERROR``)."""

    error_message: str
    """ngspice or parser failure reason. Empty only for a successful row."""

    raw_value: Optional[float] = None
    """Raw numeric value for downstream arithmetic."""

    target: str = ""
    """User-authored target text (e.g. ``"\u2265 20 dB"``). Empty means unset."""


__all__ = ["DisplayMetric"]
