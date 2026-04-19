# RunSimulationTool - Agent 通用仿真发起工具
"""Agent 通用仿真发起工具。

职责：
- 允许 agent 对**项目内任意**电路文件发起一次仿真
- 通过 ``SimulationJobManager`` 统一通道提交 ``origin=AGENT_TOOL`` 的 job
- 等待 job 终结，用紧凑 markdown 告诉 LLM 结果，同时把
  ``result_path`` / ``export_root`` / ``job_id`` 放进 ``details`` 供后续
  ``read_*`` tool 稳定寻址

与 UI 的解耦姿态：
- 本 tool 不 import 任何 ``presentation/*`` 模块
- 不调用 ``SimulationCommandController`` / 不触碰 ``SimulationTab``
- 不 emit 任何 UI 信号——UI 侧按 Step 9 的 EventBus 订阅自然跟随 job
  的 ``EVENT_SIM_*`` 事件刷新

与取消协议的对齐：
- 等待期间用户若取消 agent，``asyncio.CancelledError`` 会从最深
  ``await`` 点抛出，沿栈抵达本 tool 的 ``except`` 分支；此时 tool 登记
  cancel 意图给 manager 再 ``raise``，让上层 ``AgentLoop`` / ``LLMExecutor``
  按既有 ``OUTCOME_STOPPED`` 路径处理。tool 自己**不**吞 ``CancelledError``。

MVP 语义上的克制：
- 不暴露 ``analysis_config`` 参数——让 LLM 只跑电路文件自带的 analysis
  指令，避免 LLM 误写复杂 NgSpice 语法造成的细碎失败
- 返回给 LLM 的 ``content`` 绝不塞大体量 artifact（raw_data / 波形
  csv / 完整日志 / chart 图像编码）；这些交由后续 ``read_*`` tool 按需
  按 ``result_path`` 获取
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.llm.agent.utils.path_utils import validate_file_path
from domain.simulation.measure.measure_result import MeasureResult
from domain.simulation.models.simulation_job import JobOrigin, JobStatus
from shared.workspace_file_types import (
    SIMULATABLE_CIRCUIT_EXTENSIONS,
    is_simulatable_circuit_extension,
)


# 紧凑 summary 里最多渲染的 measurement 行数，防止超长 .MEASURE 把 LLM
# 上下文打爆。超过上限后只保留前 N 条并在表格末尾提示"还有 M 条被截断"。
_MEASUREMENT_DISPLAY_LIMIT = 20


def _same_circuit_path(a: str, b: str) -> bool:
    """Windows 下对两条可能同一文件的路径做大小写/分隔符不敏感比较。

    ``SimulationJob.circuit_file`` 既可能是 UI 侧直接传入的绝对反斜杠
    路径，也可能是 agent 侧归一化过的路径；并发守护需要用 OS 级别的等
    价比较而不是字面字符串比较。
    """
    if not a or not b:
        return False
    try:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
            os.path.normpath(b)
        )
    except Exception:
        return a == b


class RunSimulationTool(BaseTool):
    """通用仿真发起工具。

    对应计划第 14 步：agent 的"修改电路 → 验证仿真"闭环入口。
    """

    @property
    def name(self) -> str:
        return "run_simulation"

    @property
    def label(self) -> str:
        return "Run Simulation"

    @property
    def description(self) -> str:
        return (
            "Run a simulation on a circuit file in the current project. "
            "If file_path is omitted, falls back to the editor's currently "
            "active circuit file. The tool submits a headless job through "
            "SimulationJobManager, waits for it to complete, and returns a "
            "compact summary plus a result_path for follow-up read tools. "
            "Only the analysis directives embedded in the circuit file are "
            "executed — this tool does not accept an analysis configuration."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Circuit file to simulate. Relative to project root "
                        "or absolute, but must resolve inside the project. "
                        "Supported extensions: "
                        + ", ".join(sorted(SIMULATABLE_CIRCUIT_EXTENSIONS))
                        + ". Optional: omit to run the editor's currently "
                        "active circuit file."
                    ),
                },
            },
            "required": [],
        }

    @property
    def prompt_snippet(self) -> Optional[str]:
        return (
            "Run one simulation on a project circuit file and get a compact "
            "result summary with a stable result_path for follow-up reads"
        )

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        return [
            "After editing a circuit file, call run_simulation to verify the "
            "change before replying.",
            "Do NOT call run_simulation again on the same circuit before the "
            "full 'run → read results' loop of the previous call has "
            "finished — finish reading its artifacts first.",
            "run_simulation is decoupled from the editor: it can target any "
            "circuit file inside the project, not just the one currently "
            "open in the editor tab.",
            "When run_simulation reports failure, call read_output_log with "
            "the returned result_path first to diagnose before retrying the "
            "simulation.",
            "run_simulation never embeds raw waveforms, full logs, or "
            "measurement tables beyond a short preview — use the dedicated "
            "read_* tools against the returned result_path when you need the "
            "full data.",
        ]

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """五阶段：路径解析 → 校验 → 并发守护 → 提交与等待 → 结果分派。"""
        manager = context.sim_job_manager
        if manager is None:
            return ToolResult(
                content=(
                    "Error: SimulationJobManager is not provided by the "
                    "caller via ToolContext; run_simulation cannot submit a "
                    "job without it."
                ),
                is_error=True,
            )

        # SimulationResultRepository 也必须由 context 提供——结果分
        # 派阶段需要它把 result.json 反序列化成紧凑 summary。注入缺
        # 失时直接 is_error，拒绝"fallback 到模块级 singleton"的双
        # 路径，把"agent 的外部依赖入口只有 ToolContext"这一契约守
        # 严；这也是 Step 16 read-tool 基座继承的同一姿态。
        repository = context.sim_result_repository
        if repository is None:
            return ToolResult(
                content=(
                    "Error: SimulationResultRepository is not provided by "
                    "the caller via ToolContext; run_simulation cannot "
                    "summarize the result bundle without it."
                ),
                is_error=True,
            )

        project_root = context.project_root
        if not project_root:
            return ToolResult(
                content=(
                    "Error: no project is open; run_simulation requires a "
                    "project root so artifact bundles can be persisted "
                    "under simulation_results/."
                ),
                is_error=True,
            )

        # ---- 阶段 1: 路径解析（显式参数 → 编辑器活动电路 → 报错） ----
        explicit_path = str(params.get("file_path") or "").strip()
        fallback_path = context.current_file or ""
        raw_path = explicit_path or fallback_path
        if not raw_path:
            return ToolResult(
                content=(
                    "Error: no file_path was provided and no circuit file is "
                    "currently active in the editor. Supply a file_path "
                    "relative to the project root."
                ),
                is_error=True,
            )

        # ---- 阶段 2: 校验（安全边界 + 存在 + 可仿真扩展名） ----
        abs_path, error = validate_file_path(
            raw_path, project_root, must_exist=True
        )
        if error:
            return ToolResult(content=f"Error: {error}", is_error=True)

        assert abs_path is not None  # validate_file_path contract
        if not is_simulatable_circuit_extension(abs_path):
            return ToolResult(
                content=(
                    f"Error: '{raw_path}' is not a simulatable circuit file. "
                    f"Supported extensions: "
                    + ", ".join(sorted(SIMULATABLE_CIRCUIT_EXTENSIONS))
                ),
                is_error=True,
            )

        # ---- 阶段 3: 并发守护（同电路只允许一个 AGENT_TOOL job） ----
        # 仅拦截 agent 自身并发——UI 对同一电路并跑是允许的，由 manager
        # 侧的时间戳唯一性保证 bundle 不冲突。
        active_agent_jobs = manager.list(
            origin=JobOrigin.AGENT_TOOL,
            include_terminal=False,
        )
        for existing in active_agent_jobs:
            if _same_circuit_path(existing.circuit_file, abs_path):
                return ToolResult(
                    content=(
                        f"Error: another agent simulation on "
                        f"'{existing.circuit_file}' is already running "
                        f"(job_id={existing.job_id}, status="
                        f"{existing.status.value}). Wait for it to finish "
                        "or pick a different task; run_simulation does not "
                        "queue concurrent runs of the same circuit."
                    ),
                    is_error=True,
                )

        # ---- 阶段 4: 提交 + 等待 + 取消协议对齐 ----
        job = manager.submit(
            circuit_file=abs_path,
            origin=JobOrigin.AGENT_TOOL,
            project_root=project_root,
        )

        try:
            final_job = await manager.await_completion_async(job.job_id)
        except asyncio.CancelledError:
            # 用户通过 LLMExecutor.request_stop() 取消了 agent——让
            # manager 登记取消意图（PENDING 立刻终结；RUNNING 等 worker
            # 返回后自然完成状态切换），然后 re-raise 让 asyncio 的取
            # 消传播继续走 AgentLoop → LLMExecutor 的既有 OUTCOME_STOPPED
            # 分支。tool 本身不返回 ToolResult。
            manager.request_cancel(job.job_id)
            raise

        # ---- 阶段 5: 结果分派 ----
        return self._format_result(final_job, project_root, repository)

    # ------------------------------------------------------------------
    # 结果分派
    # ------------------------------------------------------------------

    def _format_result(self, job, project_root: str, repository) -> ToolResult:
        details: Dict[str, Any] = {
            "job_id": job.job_id,
            "circuit_file": job.circuit_file,
            "status": job.status.value,
            "result_path": job.result_path or "",
            "export_root": job.export_root or "",
        }

        if job.status is JobStatus.COMPLETED:
            return self._format_completed(job, project_root, details, repository)
        if job.status is JobStatus.FAILED:
            return self._format_failed(job, details)
        if job.status is JobStatus.CANCELLED:
            # 正常情况下 CancelledError 在 await 阶段就 raise 了；这
            # 里只覆盖"其它来源把 job 标成 CANCELLED"的边角——比如
            # 另一个 UI 发来的 request_cancel。仍然按 is_error 处理，
            # content 明确区分"取消"而不是"失败"。
            return ToolResult(
                content=(
                    f"Simulation was cancelled before completion "
                    f"(job_id={job.job_id})."
                ),
                is_error=True,
                details=details,
            )
        # 理论不可达：await_completion_async 只在终结状态返回。
        return ToolResult(
            content=(
                f"Error: simulation job {job.job_id} returned in unexpected "
                f"status '{job.status.value}'."
            ),
            is_error=True,
            details=details,
        )

    def _format_completed(
        self,
        job,
        project_root: str,
        details: Dict[str, Any],
        repository,
    ) -> ToolResult:
        """成功分派：从 result.json 取紧凑 summary，**显式跳过** raw_data /
        raw_output / waveform 字段；只渲染 analysis_type / duration /
        measurements 表格。
        """
        load = repository.load(project_root, job.result_path or "")
        if not load.success or load.data is None:
            # Bundle 上了磁盘但 JSON 反序列化失败——返回"成功但摘要
            # 缺失"的告警 ToolResult（非 is_error，因为仿真本身成功；
            # LLM 仍可以用 result_path 让后续 read_* 去读）。
            err_text = load.error_message or "unknown error"
            content = (
                f"Simulation completed (job_id={job.job_id}), but the "
                f"result bundle summary could not be parsed: {err_text}.\n"
                f"- result_path: {job.result_path}\n"
                f"- export_root: {job.export_root}\n"
                "Use read_output_log or other read_* tools against "
                "result_path for diagnostics."
            )
            details["summary_error"] = err_text
            return ToolResult(content=content, details=details)

        result = load.data
        analysis_type = result.analysis_type or "unknown"
        duration_s = float(result.duration_seconds or 0.0)
        details["analysis_type"] = analysis_type
        details["duration_seconds"] = duration_s

        lines: List[str] = [
            f"Simulation completed (job_id={job.job_id}).",
            f"- Analysis: {analysis_type}",
            f"- Duration: {duration_s:.3f}s",
            f"- result_path: {job.result_path}",
            f"- export_root: {job.export_root}",
        ]

        metrics_section = self._format_measurements(result.measurements)
        if metrics_section:
            lines.append("")
            lines.extend(metrics_section)

        lines.append("")
        lines.append(
            "Pass the result_path above verbatim to any read_* tool you "
            "call next in this turn — do not rely on editor-state fallback."
        )
        return ToolResult(content="\n".join(lines), details=details)

    def _format_failed(self, job, details: Dict[str, Any]) -> ToolResult:
        err_msg = job.error_message or "unknown error"
        bundle_hint = (
            f" The failure bundle was still persisted at {job.result_path}; "
            "call read_output_log with that result_path to diagnose."
            if job.result_path
            else ""
        )
        return ToolResult(
            content=(
                f"Simulation FAILED (job_id={job.job_id}): {err_msg}.{bundle_hint}"
            ),
            is_error=True,
            details=details,
        )

    def _format_measurements(
        self,
        measurements: Optional[List[Any]],
    ) -> List[str]:
        if not measurements:
            return []
        rendered_rows: List[str] = []
        truncated = 0
        for idx, item in enumerate(measurements):
            if idx >= _MEASUREMENT_DISPLAY_LIMIT:
                truncated = len(measurements) - _MEASUREMENT_DISPLAY_LIMIT
                break
            measure = self._coerce_measure(item)
            if measure is None:
                continue
            rendered_rows.append(
                f"| {measure.name} | {measure.display_value} | "
                f"{measure.status.value} |"
            )
        if not rendered_rows:
            return []
        lines = [
            "| Metric | Value | Status |",
            "| --- | --- | --- |",
            *rendered_rows,
        ]
        if truncated > 0:
            lines.append(
                f"_{truncated} additional measurement(s) omitted; use "
                "a dedicated read tool against result_path for the full set._"
            )
        return lines

    @staticmethod
    def _coerce_measure(item: Any) -> Optional[MeasureResult]:
        """SimulationResult.measurements 经 __post_init__ 归一化后一般是
        MeasureResult 对象；但 from_dict 的分支下也可能遗留为 dict，这
        里统一兜底。
        """
        if isinstance(item, MeasureResult):
            return item
        if isinstance(item, dict):
            try:
                return MeasureResult.from_dict(item)
            except Exception:
                return None
        return None


__all__ = ["RunSimulationTool"]
