import asyncio
from pathlib import Path

import numpy as np

from domain.llm.agent.tools.read_metrics import ReadMetricsTool
from domain.llm.agent.tools.read_output_log import ReadOutputLogTool
from domain.llm.agent.tools.read_signals import ReadSignalsTool
from domain.llm.agent.types import ToolContext
from domain.simulation.data.simulation_artifact_persistence import (
    simulation_artifact_persistence,
)
from domain.simulation.models.simulation_result import SimulationData, SimulationResult
from domain.simulation.service.simulation_result_repository import (
    simulation_result_repository,
)
from domain.simulation.spice.source_closure import collect_spice_source_closure


def test_newly_persisted_bundle_round_trips_through_all_general_read_tools(
    tmp_path: Path,
):
    circuit = tmp_path / "circuits" / "amp.cir"
    circuit.parent.mkdir()
    circuit.write_text("V1 in 0 1\n.tran 1n 10n\n.end\n", encoding="utf-8")
    result = SimulationResult(
        executor="spice",
        file_path=str(circuit),
        analysis_type="tran",
        analysis_command=".tran 1n 10n",
        success=True,
        source_digest=collect_spice_source_closure(circuit).digest,
        timestamp="2026-08-23T10:00:00+08:00",
        duration_seconds=0.1,
        raw_output="Circuit: amp\nSimulation completed",
        data=SimulationData(
            time=np.array([0.0, 1e-9, 10e-9]),
            signals={"V(out)": np.array([0.0, 0.5, 1.0])},
            signal_types={"V(out)": "voltage"},
        ),
    )
    persisted = simulation_artifact_persistence.persist_bundle(str(tmp_path), result)
    context = ToolContext(
        project_root=str(tmp_path),
        sim_result_repository=simulation_result_repository,
    )
    params = {"result_path": persisted.result_path}

    signal_result = asyncio.run(
        ReadSignalsTool().execute("signals", params, context)
    )
    metrics_result = asyncio.run(
        ReadMetricsTool().execute("metrics", params, context)
    )
    log_result = asyncio.run(
        ReadOutputLogTool().execute("log", params, context)
    )

    assert signal_result.is_error is False
    assert metrics_result.is_error is False
    assert log_result.is_error is False
    assert signal_result.details["result_path"] == persisted.result_path
    assert metrics_result.details["result_path"] == persisted.result_path
    assert log_result.details["result_path"] == persisted.result_path
    assert "circuits/amp.cir" in signal_result.content
    assert "Simulation completed" in log_result.content
