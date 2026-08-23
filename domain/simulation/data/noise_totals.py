"""Read-only display/export projection for integrated ngspice noise totals."""

from __future__ import annotations

from typing import Any, Dict, Optional

from domain.simulation.models.simulation_result import SimulationResult


def build_noise_totals_payload(
    result: Optional[SimulationResult],
) -> Dict[str, Any]:
    """Project authoritative scalar totals without treating them as signals.

    The values are read exclusively from ``SimulationData.noise_totals``.
    They are never inferred by integrating spectral-density vectors and are
    never inserted into the equal-length waveform/raw-data columns.
    """

    applicable = bool(
        isinstance(result, SimulationResult)
        and str(result.analysis_type or "").strip().casefold() == "noise"
    )
    base: Dict[str, Any] = {
        "applicable": applicable,
        "available": False,
        "source": "ngspice_noise_totals" if applicable else "",
        "items": [],
    }
    if not applicable or result is None or result.data is None:
        return base

    totals = result.data.noise_totals
    if totals is None:
        return base

    signals = result.data.signals
    signal_types = result.data.signal_types
    for signal_name in ("onoise_spectrum", "inoise_spectrum"):
        if signal_name not in signals or signal_name not in signal_types:
            raise ValueError(
                f"Integrated noise totals require canonical {signal_name!r} metadata"
            )

    output_type = signal_types["onoise_spectrum"]
    input_type = signal_types["inoise_spectrum"]
    if output_type != "voltage":
        raise ValueError("Integrated output noise must use canonical voltage units")
    unit_by_input_type = {"voltage": "V", "current": "A"}
    if input_type not in unit_by_input_type:
        raise ValueError(
            "Input-referred noise must use canonical voltage or current units"
        )

    output_unit = "V"
    input_unit = unit_by_input_type[input_type]
    base["available"] = True
    base["items"] = [
        {
            "key": "output_rms",
            "value": float(totals.output_rms),
            "unit": output_unit,
        },
        {
            "key": "input_referred_rms",
            "value": float(totals.input_referred_rms),
            "unit": input_unit,
        },
    ]
    return base


__all__ = ["build_noise_totals_payload"]
