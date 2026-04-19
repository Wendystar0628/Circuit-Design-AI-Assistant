"""DisplayMetric — the authoritative presentation-layer metric row.

Lives in the domain layer so headless pipelines (artifact persistence,
agent tools) can build metric rows without importing UI code. The UI
view-model re-exports this dataclass unchanged.

Each row is a fully-formatted value string, not raw numbers, so the
same objects flow into the frontend table, the conversation attachment
panel, and the ``metrics.csv`` / ``metrics.json`` artifacts. Any
additional derivations (scoring, diff against goals) must stay off
this type — keep it as a thin display record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DisplayMetric:
    """UI-friendly representation of a ``.MEASURE`` result.

    Fields are intentionally narrowed to the columns genuinely consumed
    by downstream (frontend table, JSON export, agent attachment).
    """

    name: str
    """Metric identifier (name from the ``.MEASURE`` statement)."""

    display_name: str
    """Localised display name."""

    value: str
    """Formatted numeric string (e.g. ``"20.5 dB"``)."""

    unit: str
    """Unit symbol (``dB`` / ``Hz`` / ``V`` / ...)."""

    raw_value: Optional[float] = None
    """Raw numeric value for downstream arithmetic."""

    target: str = ""
    """User-authored target text (e.g. ``"\u2265 20 dB"``). Empty means unset."""


__all__ = ["DisplayMetric"]
