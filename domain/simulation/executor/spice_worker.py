"""Private one-shot solver entry point shared by source and packaged runtimes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform

from domain.simulation.executor.process_spice_executor import WORKER_PROTOCOL_VERSION


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Circuit AI isolated SPICE worker")
    parser.add_argument("request_path", type=Path)
    parser.add_argument("response_path", type=Path)
    args = parser.parse_args(argv)
    request = json.loads(args.request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or set(request) != {
        "protocol_version", "file_path", "timeout_seconds", "experiment",
        "source_snapshot",
    }:
        raise ValueError("Invalid simulation worker request envelope")
    if (
        type(request["protocol_version"]) is not int
        or request["protocol_version"] != WORKER_PROTOCOL_VERSION
    ):
        raise ValueError("Unsupported simulation worker protocol version")

    # These imports and construction stay in the worker. The parent never
    # initializes a DLL, starts its background thread, or reuses its globals.
    from domain.simulation.executor.spice_executor import SpiceExecutor
    from domain.simulation.models.experiment import ExperimentSpec
    from infrastructure.utils.ngspice_config import configure_ngspice

    experiment = (
        ExperimentSpec.from_dict(request["experiment"])
        if request["experiment"] is not None else None
    )
    configure_ngspice()
    executor = SpiceExecutor(timeout_seconds=request["timeout_seconds"])
    result = executor.execute(
        request["file_path"],
        experiment=experiment,
        source_snapshot=request["source_snapshot"],
    )
    if result.provenance is not None:
        result.provenance["engine"] = {
            "name": "ngspice",
            "version": (
                executor._ngspice.engine_version
                if executor._ngspice is not None else None
            ),
            "platform": platform.platform(),
            "execution_mode": "isolated_process",
        }
    args.response_path.write_text(
        json.dumps(
            {
                "protocol_version": WORKER_PROTOCOL_VERSION,
                "result": result.to_dict(),
                "provenance": getattr(result, "provenance", None),
            },
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
