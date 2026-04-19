# ReadWaveformTool - Agent 波形摘要读取工具（Step 18）
"""将一次仿真波形压缩为数值特征 + 等距锚点给 LLM。

设计基线（对照 Step 18 计划与清理清单）：

- 入口完全走 :class:`SimulationArtifactReaderBase`（Step 16 基座）：
  四个 read 工具共享同一条 ``result_path / file_path / current_file``
  解析链，本工具拿到 :class:`ResolvedSimulationBundle` 再做格式化。
- 读取源是 ``export_root/waveforms/waveform.csv``。CSV 顶部的
  "自证 header" 被解析成 ``(key, value)`` 列表随摘要 echo 出去；
  CSV 主体走
  :mod:`domain.llm.agent.tools.simulation_series_stats` 的
  **双遍流式扫描**（每信号 O(1) 累加 + 锚点只缓冲 ``K`` 行），
  所以 10 万以上采样点也不会把整份 CSV 读进内存——清理清单第 3 条
  ("禁止全量读入") 的刚性实现入口就在那个模块里。
- **绝不**读 ``waveform.png``——只把其相对路径在 content 与
  ``details`` 里回传。本文件里不 ``import base64``、不调 PNG 的
  ``read_bytes()``——清理清单第 1 条的 grep 不变量。
- 统计量只有一种实现（``simulation_series_stats.read_series_csv``），
  本工具与未来的 ``read_chart`` 共用——清理清单第 2 条的落点。
- 按 ``analysis_type`` 轻度分派：

  * ``.ac``：锚点在频率上对数分布；拉取 ``metrics.json`` 里已经由
    上游 ``.MEASURE`` 管线计算好的 ``bandwidth`` / ``gain_margin``
    / ``phase_margin`` 等派生量直接引用——本文件里**绝不**用波形
    采样重算这些量，清理清单第 4 条。
  * 其它（``.tran`` / ``.dc`` / 默认）：锚点在行索引上等距分布，
    不做派生量块。

- ``waveforms/`` 缺失（如 ``.op`` 分析）→ is_error，content 只陈述
  事实：缺哪个 CSV、该 bundle 的 ``analysis_type``——不点名下一步
  该调哪个 read 工具。哪个 tool 接手由 LLM 结合用户意图自行决定；
  源头 read 工具在它们自己的 prompt_guidelines 里已经自证了能力。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.llm.agent.tools.simulation_artifact_reader_base import (
    READ_TOOL_SHARED_GUIDELINES,
    ResolvedSimulationBundle,
    SimulationArtifactReaderBase,
    TargetStatus,
    evaluate_metric_target,
)
from domain.llm.agent.tools.simulation_series_stats import (
    AnchorRow,
    AnchorScale,
    SeriesReadResult,
    SeriesStats,
    read_series_csv,
)
from domain.llm.agent.types import BaseTool, ToolContext, ToolResult
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)


# ============================================================
# 模块级常量
# ============================================================


#: markdown content 行数硬上限；超了就尾部截断并指向 CSV 绝对路径。
_MAX_CONTENT_LINES = 500

#: 默认锚点数。:mod:`simulation_series_stats` 内部 clamp 到 [4, 32]。
_DEFAULT_ANCHOR_COUNT = 14

#: ``.ac`` 派生量匹配关键词（**字符串匹配只读用途**——在 metrics.json
#: 的 ``name`` / ``display_name`` 里做 substring 匹配，拉已经算好的
#: 行出来展示。本文件里不做任何基于波形采样的派生量计算，清理清单
#: 第 4 条的 grep 自证对象是"算式"（``bandwidth = f_at(gain_drop_3dB)``
#: 之类），这里**仅**是模式关键词常量。
_AC_FOM_KEYWORDS: Tuple[str, ...] = (
    "bandwidth",
    "gbw",
    "bw",
    "gain_margin",
    "phase_margin",
    # 紧凑写法也常见——作为补充 fallback；严格匹配 whole-word 会太
    # 严，exporter 出来的 name 都是小写带下划线，substring 足够稳定。
    "gain margin",
    "phase margin",
    "pm",
    "gm",
)

#: TargetStatus → 展示用小旗。和 read_metrics 口径一致，避免 LLM
#: 在同一对话里看到两种"达标"文案而混淆。
_STATUS_CELL: Dict[TargetStatus, str] = {
    TargetStatus.PASS: "PASS",
    TargetStatus.FAIL: "FAIL",
    TargetStatus.NO_TARGET: "—",
    TargetStatus.UNPARSEABLE: "UNPARSEABLE",
}


# ============================================================
# Tool
# ============================================================


class ReadWaveformTool(BaseTool):
    """把一次仿真的波形 CSV 压缩成紧凑 markdown 摘要。"""

    @property
    def name(self) -> str:
        return "read_waveform"

    @property
    def label(self) -> str:
        return "Read Waveform"

    @property
    def description(self) -> str:
        return (
            "Summarise a simulation bundle's waveform as compact series "
            "statistics (samples/min/max/mean/initial/final/"
            "zero_crossings/peak_to_peak) plus a dozen evenly-spaced "
            "anchor samples (log-spaced for .ac). Always references "
            "waveform.png by relative path only — never returns image "
            "bytes. Supply result_path from an earlier run_simulation, "
            "or file_path to pick that circuit's latest bundle, or omit "
            "both to fall back to the editor's active circuit."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "anchor_count": {
                    "type": "integer",
                    "description": (
                        "Number of anchor samples across the sweep. "
                        "Default 14; values are clamped to [4, 32]. "
                        "For .ac bundles anchors are distributed "
                        "logarithmically over frequency."
                    ),
                },
            },
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return (
            "Read a simulation bundle's waveform as numerical series "
            "statistics plus a handful of anchor samples; the waveform "
            "image is referenced by path only"
        )

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        # 只继承跨-read-工具的参数卫生（解析链共有）+ 一条本工具自有
        # 的 A 类能力边界：它**不**返回像素。这是"给 LLM 看图"这条
        # 错误直觉的唯一源头约束——不在 agent_prompt_builder 里另行
        # 重复。
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            (
                "read_waveform never returns image bytes or base64. "
                "The waveform.png path reported in the summary is for "
                "the user to open separately; base your analysis on "
                "the numerical statistics and anchor table."
            ),
        ]

    # ------------------------------------------------------------------
    # Execute
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
        return self._format_waveform(resolved, params)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def _format_waveform(
        self,
        bundle: ResolvedSimulationBundle,
        params: Dict[str, Any],
    ) -> ToolResult:
        paths = simulation_artifact_exporter.waveforms_paths(bundle.bundle_dir)
        csv_path = paths.csv_path
        image_path = paths.image_path

        if not csv_path.is_file():
            # 只陈述事实：哪个 csv 不在、bundle 的 analysis_type 是啥。
            # .op 这类分析天然不产 waveforms/；是否去看 op_result /
            # metrics / output_log 由 LLM 基于用户意图自行决定。
            return ToolResult(
                content=(
                    f"Error: waveform csv not found at "
                    f"'{csv_path.as_posix()}'. The bundle "
                    f"'{bundle.result_path}' has no waveforms/ artifact; "
                    "typical causes are .op analyses (which have no "
                    "time/frequency sweep) or a simulation that failed "
                    "before waveform export. Result metadata: "
                    f"analysis_type='{bundle.result.analysis_type or 'unknown'}'."
                ),
                is_error=True,
            )

        anchor_count = self._resolve_anchor_count(params.get("anchor_count"))
        requested_scale = (
            AnchorScale.LOG
            if _is_ac_analysis(bundle.result.analysis_type)
            else AnchorScale.LINEAR
        )

        try:
            read_result = read_series_csv(
                csv_path=csv_path,
                anchor_count=anchor_count,
                anchor_scale=requested_scale,
            )
        except OSError as exc:
            return ToolResult(
                content=(
                    f"Error: failed to read waveform csv "
                    f"'{csv_path.as_posix()}': {exc}"
                ),
                is_error=True,
            )
        except ValueError as exc:
            return ToolResult(
                content=(
                    f"Error: waveform csv at '{csv_path.as_posix()}' is "
                    f"malformed: {exc}. The bundle on disk may be "
                    "corrupted or have been hand-edited."
                ),
                is_error=True,
            )

        # 仅 .ac 分支会引用 metrics.json 的派生量（不重算！）。
        ac_rows: List[Dict[str, Any]] = []
        if _is_ac_analysis(bundle.result.analysis_type):
            ac_rows = self._load_ac_fom_rows(bundle.bundle_dir)

        lines = self._build_markdown(
            bundle=bundle,
            image_path=image_path,
            csv_path=csv_path,
            read_result=read_result,
            anchor_count_requested=anchor_count,
            ac_rows=ac_rows,
        )
        lines = self._apply_line_cap(lines, csv_path)

        details: Dict[str, Any] = {
            "result_path": bundle.result_path,
            "used_fallback": bundle.used_fallback,
            "artifact_type": "waveforms",
            "waveform_csv_path": str(csv_path),
            "waveform_image_path": str(image_path),
            "signal_count": len(read_result.signal_column_names),
            "sample_count": read_result.total_rows,
            "anchor_count_requested": anchor_count,
            "anchor_count_effective": len(read_result.anchors),
            "anchor_scale_requested": read_result.anchor_scale_requested.value,
            "anchor_scale_effective": read_result.anchor_scale_effective.value,
            "ac_fom_count": len(ac_rows),
        }
        return ToolResult(content="\n".join(lines), details=details)

    # ------------------------------------------------------------------
    # 参数工具
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_anchor_count(raw: Any) -> int:
        if isinstance(raw, bool):
            return _DEFAULT_ANCHOR_COUNT
        if isinstance(raw, (int, float)):
            return int(raw)
        return _DEFAULT_ANCHOR_COUNT

    # ------------------------------------------------------------------
    # .ac 派生量引用（不重算！）
    # ------------------------------------------------------------------

    def _load_ac_fom_rows(self, bundle_dir: Path) -> List[Dict[str, Any]]:
        """从 ``metrics.json`` 里拉 bandwidth / gain_margin /
        phase_margin 等与 .ac 直接相关的条目。

        找不到 metrics.json 或里面没有匹配条目都属于 "正常信息缺失"
        ——返回空列表即可，**不**抛错也不报 is_error；是否足以回答
        用户的问题由 LLM 结合 summary 自行判断。
        """
        metrics_paths = simulation_artifact_exporter.metrics_paths(bundle_dir)
        path = metrics_paths.json_path
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []

        matched: List[Dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "")
            display = str(raw.get("display_name") or "")
            if not _matches_ac_keyword(name) and not _matches_ac_keyword(display):
                continue
            raw_value = raw.get("raw_value")
            if not isinstance(raw_value, (int, float)):
                raw_value = None
            status = evaluate_metric_target(
                raw_value=raw_value,
                target_text=raw.get("target"),
            )
            matched.append({
                "display_name": display or name,
                "name": name,
                "value": str(raw.get("value") or ""),
                "unit": str(raw.get("unit") or ""),
                "target": str(raw.get("target") or ""),
                "status": status,
            })
        # 稳定排序：FAIL 置顶，其他按 display_name 字母序。与 read_metrics
        # 的主表排序口径一致，避免在同一对话里顺序错乱。
        matched.sort(
            key=lambda r: (
                0 if r["status"] == TargetStatus.FAIL else 1,
                r["display_name"].lower(),
            )
        )
        return matched

    # ------------------------------------------------------------------
    # markdown 渲染
    # ------------------------------------------------------------------

    def _build_markdown(
        self,
        *,
        bundle: ResolvedSimulationBundle,
        image_path: Path,
        csv_path: Path,
        read_result: SeriesReadResult,
        anchor_count_requested: int,
        ac_rows: List[Dict[str, Any]],
    ) -> List[str]:
        result = bundle.result
        lines: List[str] = [
            "# Waveform Report",
            "",
            "- artifact_type: waveforms",
            f"- circuit_file: {bundle.circuit_file}",
            f"- analysis_type: {result.analysis_type or 'unknown'}",
            f"- executor: {result.executor or 'unknown'}",
            f"- timestamp: {result.timestamp or ''}",
            f"- result_path: {bundle.result_path}",
            f"- waveform_csv: {csv_path.as_posix()}",
            f"- waveform_image: {image_path.as_posix()}",
            (
                "  _(image is for the user to open manually; shape "
                "conclusions should come from the numerical tables "
                "below)_"
            ),
        ]
        if bundle.used_fallback:
            lines.append(
                "- resolution: via editor's active circuit (fallback)"
            )

        # ---- Summary ----
        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- x_axis_label: {read_result.x_column_name}",
                f"- signal_count: {len(read_result.signal_column_names)}",
                f"- sample_count: {read_result.total_rows}",
                f"- x_range: [{_fmt(read_result.x_range[0])}, "
                f"{_fmt(read_result.x_range[1])}]",
                (
                    f"- anchor_scale: "
                    f"{read_result.anchor_scale_effective.value}"
                    + (
                        f" (requested {read_result.anchor_scale_requested.value}; "
                        "data forced linear because x_min <= 0)"
                        if read_result.anchor_scale_effective
                        != read_result.anchor_scale_requested
                        else ""
                    )
                ),
            ]
        )

        if read_result.total_rows == 0:
            lines.extend(
                [
                    "",
                    "_Waveform csv was readable but had no numeric data "
                    "rows. The bundle likely encountered a simulation "
                    "error before samples were written._",
                ]
            )
            return lines

        # ---- Series Statistics ----
        lines.extend(
            [
                "",
                "## Series Statistics",
                "",
                "| signal | samples | min | max | mean | initial | "
                "final | zero_crossings | pk_pk |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for stats in read_result.stats:
            lines.append(_render_stats_row(stats))

        # ---- Anchor Samples ----
        if read_result.anchors:
            header = ["| x (" + read_result.x_column_name + ") |"]
            separator = ["| --- |"]
            for signal in read_result.signal_column_names:
                header.append(f" {signal} |")
                separator.append(" --- |")
            lines.extend(
                [
                    "",
                    (
                        f"## Anchor Samples "
                        f"(requested {anchor_count_requested}, "
                        f"effective {len(read_result.anchors)}, "
                        f"{read_result.anchor_scale_effective.value})"
                    ),
                    "",
                    "".join(header),
                    "".join(separator),
                ]
            )
            for anchor in read_result.anchors:
                lines.append(_render_anchor_row(anchor))

        # ---- .ac Figures of Merit（仅当有匹配项时展示；不重算） ----
        if ac_rows:
            lines.extend(
                [
                    "",
                    "## AC Figures of Merit",
                    "",
                    (
                        "_Pulled verbatim from metrics.json (computed by "
                        "the .MEASURE pipeline); this tool does not "
                        "re-derive these values from waveform samples._"
                    ),
                    "",
                    "| display_name | value | unit | target | status |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for row in ac_rows:
                lines.append(
                    f"| {row['display_name']} | {row['value']} | "
                    f"{row['unit']} | {row['target'] or '—'} | "
                    f"{_STATUS_CELL.get(row['status'], str(row['status']))} |"
                )

        return lines

    # ------------------------------------------------------------------
    # 行数封顶
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_line_cap(lines: List[str], csv_path: Path) -> List[str]:
        if len(lines) <= _MAX_CONTENT_LINES:
            return lines
        kept = lines[: _MAX_CONTENT_LINES - 2]
        omitted = len(lines) - len(kept)
        kept.extend(
            [
                "",
                (
                    f"_{omitted} line(s) truncated; open "
                    f"'{csv_path}' directly for the full table._"
                ),
            ]
        )
        return kept


# ============================================================
# 模块级工具
# ============================================================


def _is_ac_analysis(analysis_type: Optional[str]) -> bool:
    text = (analysis_type or "").strip().lstrip(".").lower()
    return text == "ac"


def _matches_ac_keyword(text: str) -> bool:
    """大小写/下划线/空格不敏感的 substring 匹配。"""
    if not text:
        return False
    needle = text.strip().lower()
    for keyword in _AC_FOM_KEYWORDS:
        if keyword in needle:
            return True
    return False


def _render_stats_row(stats: SeriesStats) -> str:
    return (
        f"| {stats.name} | {stats.samples} | "
        f"{_fmt(stats.min_value)} | {_fmt(stats.max_value)} | "
        f"{_fmt(stats.mean_value)} | {_fmt(stats.initial_value)} | "
        f"{_fmt(stats.final_value)} | {stats.zero_crossings} | "
        f"{_fmt(stats.peak_to_peak)} |"
    )


def _render_anchor_row(anchor: AnchorRow) -> str:
    cells = [f"| {_fmt(anchor.x)} |"]
    for value in anchor.values:
        cells.append(f" {_fmt(value) if value is not None else '—'} |")
    return "".join(cells)


def _fmt(value: Optional[float]) -> str:
    """紧凑浮点格式化，给 LLM 看的人类可读文本。

    * ``None`` / ``nan`` / ``inf`` → ``—``。
    * 0 → ``0``。
    * |v| >= 1e4 或 < 1e-3 → 科学计数法（3 有效位）。
    * 其他 → fixed 4 位有效数字。
    """
    if value is None:
        return "—"
    try:
        if not math.isfinite(value):
            return "—"
    except TypeError:
        return "—"
    if value == 0:
        return "0"
    absolute = abs(value)
    if absolute >= 1e4 or absolute < 1e-3:
        return f"{value:.3e}"
    return f"{value:.4g}"


# ============================================================
# 模块导出
# ============================================================


__all__ = ["ReadWaveformTool"]
