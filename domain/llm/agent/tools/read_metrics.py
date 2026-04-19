# ReadMetricsTool - Agent 指标读取工具（Step 17）
"""读取单次仿真的全部 ``.MEASURE`` 指标及其达标状态。

- 入口完全走 :class:`SimulationArtifactReaderBase`（Step 16）：四个
  read 工具共享同一解析链，避免每个工具各写一套"怎么找到 bundle"的
  分支。
- 读取顺序权威：``export_root/metrics/metrics.json``（结构化、一次
  拿全 ``data.rows``）；缺失 → is_error，文案只陈述事实（哪个文件
  不存在、典型原因），**不**暗示 LLM 下一步要调哪个工具——是否去
  看日志 / 重跑仿真，由 LLM 基于用户意图自行决定。**不**回落到
  现场扫描 ``result.json`` 的 ``measurements`` 字段——那是 exporter
  的输入而不是我们的二次数据源，两条平行路径并存会在 UI 改 target
  之后出现"metrics.json 已更新、tool 还在读老数据"的漂移。
- 达标判定：唯一权威 util
  :func:`simulation_artifact_reader_base.evaluate_metric_target`
  （同文件里的 ``TargetStatus`` 枚举）；**禁止**在本文件里写任何
  ``raw_value > target`` / ``raw_value < target`` 这类手写比较。
- 输出严格不带 ``raw_value`` 浮点原值给 LLM：``value`` 字段本来就是
  经过 ``DisplayMetricBuilder._format_with_unit`` 格式化好的字符串，
  LLM 视角这已是人类可读形态，再带原值只是 token 膨胀。
- 500 行 markdown 上限：触达就尾部截断，content 末尾明确附
  ``metrics.csv`` 的**绝对路径**，方便 LLM 追加 ``read_file`` 跟进。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
    TargetStatus,
    evaluate_metric_target,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)


# Content 行数上限；触达即尾部截断 + 追加 metrics.csv 绝对路径指引。
_MAX_CONTENT_LINES = 500


# TargetStatus → 表格里展示的 UTF-8 友好文案。集中在这个字典里让措
# 辞有唯一出处；测试断言也指着它。
_STATUS_CELL: Dict[TargetStatus, str] = {
    TargetStatus.PASS: "PASS",
    TargetStatus.FAIL: "FAIL",
    TargetStatus.NO_TARGET: "—",
    TargetStatus.UNPARSEABLE: "UNPARSEABLE",
}


class ReadMetricsTool(BaseTool):
    """读取单次仿真 bundle 的指标表并渲染为 markdown。"""

    @property
    def name(self) -> str:
        return "read_metrics"

    @property
    def label(self) -> str:
        return "Read Metrics"

    @property
    def description(self) -> str:
        return (
            "Read the full .MEASURE metric table of one simulation bundle "
            "and annotate each row with its pass/fail status against the "
            "user-authored target (if any). Supply result_path from an "
            "earlier run_simulation for an exact handle; supply file_path "
            "to pick that circuit's most recent bundle; omit both to fall "
            "back to the editor's active circuit. Optional metric_name "
            "filters the output to a single row."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "metric_name": {
                    "type": "string",
                    "description": (
                        "Optional case-insensitive exact match on the "
                        "metric's name or display_name. Omit to return "
                        "all metrics of the bundle."
                    ),
                },
            },
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return (
            "Read the .MEASURE metric table of a simulation bundle with "
            "per-row target pass/fail annotation"
        )

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        # 刻意只继承跨-read-工具的参数卫生约束；**不**追加任何
        # "你应该在 run_simulation 之后优先调本工具"之类的工作流
        # 暗示——工具间的调用时机由 LLM 基于用户意图与上下文自行
        # 判断，这里强行耦合只会把决策权从模型手里抢走。
        return list(READ_TOOL_SHARED_GUIDELINES)

    # ------------------------------------------------------------------
    # Execute —— 解析 → 读 metrics.json → 格式化
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_call_id: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        resolved = SimulationArtifactReaderBase.resolve(params, context)
        if isinstance(resolved, ToolResult):
            return resolved

        return self._format_metrics(resolved, params)

    # ------------------------------------------------------------------
    # metrics.json 读取 + markdown 渲染
    # ------------------------------------------------------------------

    def _format_metrics(
        self,
        bundle: ResolvedSimulationBundle,
        params: Dict[str, Any],
    ) -> ToolResult:
        paths = simulation_artifact_exporter.metrics_paths(bundle.bundle_dir)
        json_path = paths.json_path

        if not json_path.is_file():
            return ToolResult(
                content=(
                    f"Error: metrics artifact not found at "
                    f"'{json_path.as_posix()}'. The simulation bundle "
                    f"'{bundle.result_path}' contains no .MEASURE output "
                    "— typical causes are that the simulation failed "
                    "before metrics were computed, or the circuit defines "
                    "no .MEASURE directives."
                ),
                is_error=True,
            )

        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ToolResult(
                content=(
                    f"Error: metrics artifact at '{json_path.as_posix()}' "
                    f"could not be parsed as JSON: {exc}. The bundle on "
                    "disk may be corrupted."
                ),
                is_error=True,
            )

        data = payload.get("data") or {}
        rows = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            rows = []

        filter_text = str(params.get("metric_name") or "").strip()
        if filter_text:
            selected = self._filter_rows(rows, filter_text)
            if not selected:
                available = ", ".join(
                    sorted(
                        {
                            str(row.get("name") or row.get("display_name") or "")
                            for row in rows
                            if isinstance(row, dict)
                        }
                        - {""}
                    )
                ) or "<none>"
                return ToolResult(
                    content=(
                        f"Error: no metric named '{filter_text}' in bundle "
                        f"'{bundle.result_path}'. Available: {available}."
                    ),
                    is_error=True,
                )
            rows = selected

        annotated = [self._annotate_row(row) for row in rows]
        # 未达标置顶 → 已达标 / 无目标 / 无法解析按 display_name 稳定排序
        annotated.sort(key=self._row_sort_key)

        lines = self._build_markdown(
            bundle=bundle,
            annotated=annotated,
            metrics_csv_path=paths.csv_path,
            filter_text=filter_text,
        )

        details: Dict[str, Any] = {
            "result_path": bundle.result_path,
            "used_fallback": bundle.used_fallback,
            "metric_count": len(annotated),
            "metrics_json_path": str(json_path),
            "metrics_csv_path": str(paths.csv_path),
        }
        return ToolResult(content="\n".join(lines), details=details)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_rows(
        rows: List[Any],
        filter_text: str,
    ) -> List[Dict[str, Any]]:
        needle = filter_text.strip().lower()
        selected: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip().lower()
            display = str(row.get("display_name") or "").strip().lower()
            if name == needle or display == needle:
                selected.append(row)
        return selected

    @staticmethod
    def _annotate_row(row: Any) -> Dict[str, Any]:
        if not isinstance(row, dict):
            row = {}
        raw_value = row.get("raw_value")
        if not isinstance(raw_value, (int, float)):
            raw_value = None
        status = evaluate_metric_target(
            raw_value=raw_value,
            target_text=row.get("target"),
        )
        return {
            "display_name": str(row.get("display_name") or "") or str(row.get("name") or ""),
            "name": str(row.get("name") or ""),
            "value": str(row.get("value") or ""),
            "unit": str(row.get("unit") or ""),
            "target": str(row.get("target") or ""),
            "status": status,
        }

    @staticmethod
    def _row_sort_key(row: Dict[str, Any]):
        # 未达标 = 0（最上），其它 = 1，方便 LLM 一眼看到要修什么。
        status: TargetStatus = row["status"]
        bucket = 0 if status == TargetStatus.FAIL else 1
        display = row.get("display_name") or row.get("name") or ""
        return (bucket, display.lower())

    def _build_markdown(
        self,
        *,
        bundle: ResolvedSimulationBundle,
        annotated: List[Dict[str, Any]],
        metrics_csv_path: Path,
        filter_text: str,
    ) -> List[str]:
        result = bundle.result
        header: List[str] = [
            "# Metrics Report",
            "",
            f"- artifact_type: metrics",
            f"- circuit_file: {bundle.circuit_file}",
            f"- analysis_type: {result.analysis_type or 'unknown'}",
            f"- executor: {result.executor or 'unknown'}",
            f"- timestamp: {result.timestamp or ''}",
            f"- result_path: {bundle.result_path}",
        ]
        if filter_text:
            header.append(f"- filter: metric_name == '{filter_text}'")
        if bundle.used_fallback:
            header.append(
                "- resolution: via editor's active circuit (fallback)"
            )

        # 摘要
        total = len(annotated)
        with_target = sum(
            1 for row in annotated if row["status"] != TargetStatus.NO_TARGET
        )
        passed = sum(1 for row in annotated if row["status"] == TargetStatus.PASS)
        failed = sum(1 for row in annotated if row["status"] == TargetStatus.FAIL)
        unparseable = sum(
            1 for row in annotated if row["status"] == TargetStatus.UNPARSEABLE
        )
        summary = [
            "",
            "## Summary",
            "",
            f"- total: {total}",
            f"- with_target: {with_target}",
            f"- passed: {passed}",
            f"- failed: {failed}",
        ]
        if unparseable:
            summary.append(f"- unparseable_targets: {unparseable}")

        # 主表 vs 无目标段落
        targeted = [
            row for row in annotated if row["status"] != TargetStatus.NO_TARGET
        ]
        no_target = [
            row for row in annotated if row["status"] == TargetStatus.NO_TARGET
        ]

        body: List[str] = []
        if targeted:
            body.extend(
                [
                    "",
                    "## Metrics with Target",
                    "",
                    "| display_name | value | unit | target | status |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for row in targeted:
                body.append(self._render_row(row))

        if no_target:
            body.extend(
                [
                    "",
                    "## Metrics without Target",
                    "",
                    "| display_name | value | unit |",
                    "| --- | --- | --- |",
                ]
            )
            for row in no_target:
                body.append(
                    f"| {row['display_name']} | {row['value']} | {row['unit']} |"
                )

        if not annotated:
            body.extend(
                [
                    "",
                    "_Bundle contains no .MEASURE metrics._",
                ]
            )

        lines = [*header, *summary, *body]
        return self._apply_line_cap(lines, metrics_csv_path)

    @staticmethod
    def _render_row(row: Dict[str, Any]) -> str:
        status_cell = _STATUS_CELL.get(row["status"], str(row["status"]))
        target_cell = row["target"] or "—"
        return (
            f"| {row['display_name']} | {row['value']} | {row['unit']} "
            f"| {target_cell} | {status_cell} |"
        )

    @staticmethod
    def _apply_line_cap(
        lines: List[str],
        metrics_csv_path: Path,
    ) -> List[str]:
        if len(lines) <= _MAX_CONTENT_LINES:
            return lines
        # 保留前 cap-2 行 + 截断提示 + csv 绝对路径指引。
        kept = lines[: _MAX_CONTENT_LINES - 2]
        omitted = len(lines) - len(kept)
        kept.extend(
            [
                "",
                (
                    f"_{omitted} line(s) truncated; open "
                    f"'{metrics_csv_path}' directly for the full table._"
                ),
            ]
        )
        return kept


__all__ = ["ReadMetricsTool"]
