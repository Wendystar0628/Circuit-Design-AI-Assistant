# ReadSignalsTool - 仿真信号统一阅读工具（Step 19）
"""给 LLM 一个单一入口去读仿真 bundle 里的信号 CSV。

**核心架构原则**：agent 的信号阅读面**只**取决于仿真器产出的数据，
**不**受 UI 勾选状态影响。

    一次仿真 bundle 里有两类信号 CSV 对 agent 可见：

    - ``raw_data/raw_data.csv`` —— 仿真器**全量转储**。
      :class:`SimulationArtifactPersistence` 在每一次仿真（不论 UI
      或 agent 触发）都**无条件**写出，只取决于 ``SimulationResult``，
      **完全不查询 UI 状态**。这是 agent 的权威、默认信号源。

    - ``charts/{idx:02d}_{type}.csv`` —— UI 图表的**预计算视图**
      （Bode / DC sweep / noise / waveform_time）。每张 chart 带自己
      的 ``log_x`` 旁字段和 ``chart_type`` 语义；Bode chart 尤其和
      ``metrics.json`` 里 ``.MEASURE`` 写好的 bandwidth / GM / PM
      FOM 表强相关。可选工件，仅当用户在 UI 导出图表时存在。
      agent 把它当成"有 FOM 上下文的特化视图"，**不是**全量信号通道。

**刻意不属于 agent 信号源的一类**：

    ``waveforms/waveform.csv`` 是 UI 波形 widget 的 overlay 导出——
    它的列严格由用户在 UI 上的勾选决定（``WaveformWidget.
    get_displayed_signal_names``）。从数据层面看，它永远是
    ``raw_data`` 的列子集经 UI 过滤后的产物。

    Agent 如果想看一组指定信号，用 ``source='raw' + signal_filter=
    [...]`` 语义更明确、且完全复刻 overlay 的效果。所以本工具
    **不枚举**、**不暴露**、**不路由到** ``waveforms/``——UI 勾选状
    态是用户自己的查看行为，不是 agent 的决策输入。

三份 CSV（raw / chart）的表结构**完全同构**（由同一个
:meth:`SimulationArtifactExporter.write_csv_with_header` 写出）：顶部
6 行 ``# key: value`` 自证 header + 空行 + 列头行（第 0 列为 x 轴，
其余列为信号）+ 数据行。所有"读数值"的算法都复用同一份
:mod:`domain.llm.agent.tools.simulation_series_stats`——禁止两份实现。

本工具做三件事，所有路径解析都锚定在
:class:`SimulationArtifactExporter` 的 ``*_paths(export_root)`` 类型化
helper 上，不允许字符串拼 ``"raw_data" / "raw_data.csv"``：

1. **路由**：把 ``source`` 参数映射到一份具体的 CSV。``auto`` =
   始终选 ``raw``（agent-canonical）。``chart`` 需要 ``chart_index``
   佐证。``overlay`` 在 enum 里不存在——拒绝任何把 agent 绑到 UI
   勾选状态的入口。
2. **读取**：调用 :func:`read_series_csv` 拿到每条信号的
   ``samples / min / max / mean / initial / final / zero_crossings /
   peak_to_peak`` + 一张锚点小表。``anchor_scale="auto"`` 会按
   ``analysis_type``（raw）或 chart 的 ``log_x`` 旁字段（chart）
   自动选 LINEAR / LOG。
3. **自陈可走的下一步**：无论选中哪个源，回显 ``sources_available``
   —— raw 是否在、charts.json 里有哪几条 chart。LLM 因此无需额外
   调用就能计划下一次精读（"我现在看到的是 raw，bundle 还有一张
   Bode chart，下一轮窄读它拿 FOM 上下文"）。

永不违反的不变量（静态 AST 测试固化）：

- 模块内绝不 ``import base64``，绝不对任何 ``*.png`` 调 ``read_bytes()``
  —— PNG 路径只在 content 里出现字符串形态。
- ``.ac`` 的 bandwidth / gain_margin / phase_margin 永远**引用**
  ``metrics.json.data.rows`` 里 ``.MEASURE`` 管线写好的值，绝不用
  波形采样重算。
- 任何 CSV 都走 :func:`read_series_csv` 的双遍流式 open；绝不对
  CSV 路径调 ``read_text()`` / ``readlines()``。
- 绝不 ``import`` 或调用 ``simulation_artifact_exporter.
  waveforms_paths`` —— waveforms/ 和 agent 的信号决策面永久隔离。
"""

from __future__ import annotations

import enum
import json
import math
from dataclasses import dataclass
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


#: markdown content 行数硬上限；超了尾部截断并指向源 CSV 绝对路径。
_MAX_CONTENT_LINES = 600

#: 默认锚点数。:mod:`simulation_series_stats` 内部 clamp 到 [4, 32]。
_DEFAULT_ANCHOR_COUNT = 14

#: ``.ac`` FOM 在 metrics.json 里的关键词（substring 匹配，只读用途）。
#: 与清理清单第 4 条的 grep 自证对象（**表达式** ``bandwidth = ...``
#: 之类）是互不相干的两件事——这里是常量字符串，不是计算。
_AC_FOM_KEYWORDS: Tuple[str, ...] = (
    "bandwidth",
    "gbw",
    "bw",
    "gain_margin",
    "phase_margin",
    "gain margin",
    "phase margin",
    "pm",
    "gm",
)

#: Bode 图专属的 chart_type 串——chart 源触发 FOM 引用的充要条件。
_BODE_CHART_TYPE = "bode_overlay"

#: TargetStatus → 展示用小旗，与 read_metrics 口径一致。
_STATUS_CELL: Dict[TargetStatus, str] = {
    TargetStatus.PASS: "PASS",
    TargetStatus.FAIL: "FAIL",
    TargetStatus.NO_TARGET: "—",
    TargetStatus.UNPARSEABLE: "UNPARSEABLE",
}


# ============================================================
# 源类型 + 描述符
# ============================================================


class SourceKind(str, enum.Enum):
    """Agent 可路由的信号源（UI-agnostic）。

    Notes:
        字符串枚举——参数 schema 的 ``enum`` 直接用 ``.value`` 列出；
        ``details["source"]`` 也是同款字符串，和 LLM 见到的参数名
        对齐。

        故意不包含 ``OVERLAY``：``waveforms/waveform.csv`` 是 UI
        勾选过滤后的产物，保留在枚举里会把 agent 绑到用户的 UI
        交互状态上。需要看"某组信号"用 ``RAW`` + ``signal_filter``
        达到语义更明确的同等效果。
    """

    RAW = "raw"
    CHART = "chart"


@dataclass(frozen=True)
class _SourceDescriptor:
    """一个可读信号源的路径 + 旁字段快照。

    ``discover_sources`` 返回 raw 一条（若在）+ 每张 chart 一条，
    供 ``_pick_source`` 做路由选择，并进入 discovery 回显。
    """

    kind: SourceKind
    csv_path: Path
    image_path: Optional[Path]
    """chart 对应的 PNG；raw 没有画面。"""

    chart_index: Optional[int]
    chart_type: Optional[str]
    chart_title: Optional[str]
    log_x_hint: Optional[bool]
    """仅 chart 来自 sidecar JSON 的 ``log_x``；raw 为 None。"""

    series_count_hint: Optional[int]
    """discovery 展示用；来自 manifest/sidecar，可能 None。"""


# ============================================================
# Tool
# ============================================================


class ReadSignalsTool(BaseTool):
    """Unified reader over a simulation bundle's three signal CSV sources."""

    @property
    def name(self) -> str:
        return "read_signals"

    @property
    def label(self) -> str:
        return "Read Signals"

    @property
    def description(self) -> str:
        return (
            "Summarise a simulation bundle's signal CSV as compact "
            "series statistics (samples/min/max/mean/initial/final/"
            "zero_crossings/peak_to_peak) plus a handful of anchor "
            "samples. Two sources are visible to the agent: 'raw' "
            "(always present — the simulator's full dump under "
            "raw_data/, written unconditionally by every simulation "
            "and independent of any UI selection state) and 'chart' "
            "(a specific exported UI chart under charts/ — e.g. Bode, "
            "DC sweep, noise — addressed by chart_index; carries "
            "chart-type-specific context such as log_x axis and, for "
            "Bode charts, a reference to the bandwidth/GM/PM figures "
            "of merit in metrics.json). Default source='auto' always "
            "resolves to 'raw' — agents read the full simulation "
            "output by default and are never gated by what the user "
            "happens to have checked in the waveform panel. Image "
            "files are referenced by relative path only — this tool "
            "never returns image bytes. Every successful response "
            "echoes sources_available so further calls can target "
            "the right one."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return SimulationArtifactReaderBase.build_parameters_schema(
            extra_properties={
                "source": {
                    "type": "string",
                    "enum": [
                        "auto",
                        SourceKind.RAW.value,
                        SourceKind.CHART.value,
                    ],
                    "description": (
                        "Which CSV inside the bundle to read. 'auto' "
                        "(default) always resolves to 'raw' — the "
                        "simulator's full dump, independent of any UI "
                        "selection. 'chart' additionally requires "
                        "chart_index."
                    ),
                },
                "chart_index": {
                    "type": "integer",
                    "description": (
                        "1-based chart index as reported by "
                        "sources_available (or the bundle's "
                        "charts.json manifest). Required when "
                        "source='chart'; ignored otherwise."
                    ),
                },
                "signal_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of exact series names to keep "
                        "(e.g. ['V(out)', 'V(in)']). When omitted, all "
                        "series are reported. Names that match no "
                        "series are echoed back as a warning; they do "
                        "not fail the call."
                    ),
                },
                "anchor_count": {
                    "type": "integer",
                    "description": (
                        "Number of anchor samples across the sweep. "
                        "Default 14; values are clamped to [4, 32]."
                    ),
                },
                "anchor_scale": {
                    "type": "string",
                    "enum": ["auto", "linear", "log"],
                    "description": (
                        "Distribution of anchor x-values. 'auto' "
                        "(default) picks log for .ac/.noise analyses "
                        "on raw, or honours the chart's log_x flag "
                        "on chart sources."
                    ),
                },
            },
        )

    @property
    def prompt_snippet(self) -> Optional[str]:
        return (
            "Read a simulation bundle's signals (raw dump or a specific "
            "chart) as numerical statistics plus anchor samples; images "
            "are referenced by path only"
        )

    @property
    def prompt_guidelines(self) -> Optional[List[str]]:
        # 继承跨-read-工具的参数卫生 + 三条本工具自有的能力边界。
        return [
            *READ_TOOL_SHARED_GUIDELINES,
            (
                "read_signals never returns image bytes or base64. "
                "The chart PNG paths reported in the summary are for "
                "the user to open separately; base your analysis on "
                "the numerical statistics and anchor table."
            ),
            (
                "The first call on a bundle can safely omit 'source' — "
                "'auto' resolves to 'raw' (the simulator's full dump) "
                "and the response lists every other source available "
                "in this bundle (chart indices) so a targeted "
                "follow-up call can drill in."
            ),
            (
                "Your signal access is independent of what the user "
                "has displayed in the UI. Do not assume the user's "
                "waveform-panel selection constrains which signals "
                "you can read: 'raw' contains every simulated signal, "
                "and signal_filter is how you narrow down to a "
                "specific subset if you need to."
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
        return self._format_signals(resolved, params)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def _format_signals(
        self,
        bundle: ResolvedSimulationBundle,
        params: Dict[str, Any],
    ) -> ToolResult:
        sources = self._discover_sources(bundle.bundle_dir)

        picked_or_error = self._pick_source(params, sources, bundle)
        if isinstance(picked_or_error, ToolResult):
            return picked_or_error
        target: _SourceDescriptor = picked_or_error

        requested_scale = self._resolve_anchor_scale(params, target, bundle)
        anchor_count = self._resolve_anchor_count(params.get("anchor_count"))

        try:
            read_result = read_series_csv(
                csv_path=target.csv_path,
                anchor_count=anchor_count,
                anchor_scale=requested_scale,
            )
        except OSError as exc:
            return ToolResult(
                content=(
                    f"Error: failed to read signals csv "
                    f"'{target.csv_path.as_posix()}': {exc}"
                ),
                is_error=True,
            )
        except ValueError as exc:
            return ToolResult(
                content=(
                    f"Error: signals csv at "
                    f"'{target.csv_path.as_posix()}' is malformed: "
                    f"{exc}. The bundle on disk may be corrupted or "
                    "have been hand-edited."
                ),
                is_error=True,
            )

        filter_list = self._normalize_filter(params.get("signal_filter"))
        matched_names, unmatched_names = self._split_filter(
            read_result.signal_column_names, filter_list
        )
        filtered_read = self._subset_series(read_result, matched_names)

        # AC FOM 引用：两种条件成立才触发，任意源都不重算。
        ac_rows: List[Dict[str, Any]] = []
        if self._should_link_ac_fom(target, bundle):
            ac_rows = self._load_ac_fom_rows(bundle.bundle_dir)

        lines = self._build_markdown(
            bundle=bundle,
            target=target,
            read_result=filtered_read,
            full_signal_names=read_result.signal_column_names,
            matched_names=matched_names,
            unmatched_names=unmatched_names,
            anchor_count_requested=anchor_count,
            ac_rows=ac_rows,
            sources=sources,
        )
        lines = self._apply_line_cap(lines, target.csv_path)

        details: Dict[str, Any] = {
            "result_path": bundle.result_path,
            "used_fallback": bundle.used_fallback,
            "source": target.kind.value,
            "source_csv_path": str(target.csv_path),
            "source_image_path": (
                str(target.image_path) if target.image_path else None
            ),
            "chart_index": target.chart_index,
            "chart_type": target.chart_type,
            "signal_count": len(filtered_read.signal_column_names),
            "signal_count_total": len(read_result.signal_column_names),
            "sample_count": read_result.total_rows,
            "anchor_count_requested": anchor_count,
            "anchor_count_effective": len(filtered_read.anchors),
            "anchor_scale_requested": filtered_read.anchor_scale_requested.value,
            "anchor_scale_effective": filtered_read.anchor_scale_effective.value,
            "unmatched_filter_names": list(unmatched_names),
            "ac_fom_count": len(ac_rows),
            "sources_available": [
                self._descriptor_to_details(src) for src in sources
            ],
        }
        return ToolResult(content="\n".join(lines), details=details)

    # ------------------------------------------------------------------
    # Source discovery
    # ------------------------------------------------------------------

    def _discover_sources(self, bundle_dir: Path) -> List[_SourceDescriptor]:
        """枚举 bundle 里对 agent 可见的信号源。

        顺序：raw → chart(1..N)。chart 条目按 manifest 里的
        ``chart_index`` 升序，保持与 UI 展示顺序一致。

        刻意**不**枚举 ``waveforms/waveform.csv``——它的列由用户 UI
        勾选过滤，属于用户查看行为的产物，不该进入 agent 的决策面。
        """
        out: List[_SourceDescriptor] = []

        raw_paths = simulation_artifact_exporter.raw_data_paths(bundle_dir)
        if raw_paths.csv_path.is_file():
            out.append(
                _SourceDescriptor(
                    kind=SourceKind.RAW,
                    csv_path=raw_paths.csv_path,
                    image_path=None,
                    chart_index=None,
                    chart_type=None,
                    chart_title=None,
                    log_x_hint=None,
                    series_count_hint=_read_json_signal_count(
                        raw_paths.json_path
                    ),
                )
            )

        out.extend(self._discover_chart_sources(bundle_dir))
        return out

    def _discover_chart_sources(self, bundle_dir: Path) -> List[_SourceDescriptor]:
        """解析 ``charts/charts.json`` manifest 列出每张 chart。

        找不到 manifest（UI 没 export chart）返回空列表；任何解析
        错误也静默返回空——chart 本来就是可选工件，不是错误。
        """
        charts_paths = simulation_artifact_exporter.charts_paths(bundle_dir)
        manifest = charts_paths.manifest_json_path
        if not manifest.is_file():
            return []
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        data = payload.get("data") if isinstance(payload, dict) else None
        chart_entries = data.get("charts") if isinstance(data, dict) else None
        if not isinstance(chart_entries, list):
            return []

        out: List[_SourceDescriptor] = []
        for entry in chart_entries:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("chart_index")
            ctype = str(entry.get("chart_type") or "")
            if not isinstance(idx, int) or not ctype:
                continue
            files = entry.get("files")
            files = files if isinstance(files, dict) else {}
            csv_name = str(files.get("csv") or "")
            png_name = str(files.get("image") or "")
            sidecar_name = str(files.get("json") or "")
            if not csv_name:
                continue
            csv_path = charts_paths.directory / csv_name
            if not csv_path.is_file():
                # manifest 里有但文件没落盘——静默跳过这条，其它
                # 图表仍然可读；discovery 不因一张坏图阻断整条链。
                continue
            image_path = (
                charts_paths.directory / png_name if png_name else None
            )
            log_x, series_count = self._read_chart_sidecar(
                charts_paths.directory / sidecar_name if sidecar_name else None
            )
            out.append(
                _SourceDescriptor(
                    kind=SourceKind.CHART,
                    csv_path=csv_path,
                    image_path=image_path,
                    chart_index=idx,
                    chart_type=ctype,
                    chart_title=str(entry.get("title") or ""),
                    log_x_hint=log_x,
                    series_count_hint=series_count,
                )
            )
        out.sort(key=lambda d: d.chart_index or 0)
        return out

    @staticmethod
    def _read_chart_sidecar(
        sidecar: Optional[Path],
    ) -> Tuple[Optional[bool], Optional[int]]:
        if sidecar is None or not sidecar.is_file():
            return None, None
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None, None
        log_x = data.get("log_x")
        log_x = bool(log_x) if isinstance(log_x, bool) else None
        series = data.get("series")
        series_count = len(series) if isinstance(series, list) else None
        return log_x, series_count

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------

    def _pick_source(
        self,
        params: Dict[str, Any],
        sources: List[_SourceDescriptor],
        bundle: ResolvedSimulationBundle,
    ) -> Any:  # _SourceDescriptor | ToolResult
        requested = str(params.get("source") or "auto").strip().lower()
        chart_index_raw = params.get("chart_index")

        if requested == "auto":
            # auto 永远解析到 raw——agent 的默认视角是仿真器全量输出，
            # 与 UI 勾选无关。没有 raw = bundle 残缺，报错让 LLM 看到
            # 事实而非静默回退到一张 chart（chart 是特化视图，不是
            # 全量信号通道的替身）。
            found = self._first_of_kind(sources, SourceKind.RAW)
            if found is None:
                return self._no_sources_error(bundle, sources)
            return found

        if requested == SourceKind.RAW.value:
            found = self._first_of_kind(sources, SourceKind.RAW)
            if found is None:
                return self._missing_source_error(
                    requested, bundle, sources,
                    hint=(
                        "raw_data/ is written by every headless "
                        "persistence; its absence indicates a broken "
                        "or partial bundle."
                    ),
                )
            return found

        if requested == SourceKind.CHART.value:
            # ``bool`` is a subclass of ``int`` — reject it explicitly so
            # ``chart_index=True`` does not silently match chart #1.
            if (
                not isinstance(chart_index_raw, int)
                or isinstance(chart_index_raw, bool)
            ):
                return ToolResult(
                    content=(
                        "Error: source='chart' requires an integer "
                        "chart_index. Call this tool first with "
                        "source='auto' (or without source) to see the "
                        "available chart indices in sources_available."
                    ),
                    is_error=True,
                )
            for src in sources:
                if (
                    src.kind == SourceKind.CHART
                    and src.chart_index == chart_index_raw
                ):
                    return src
            return self._missing_chart_error(
                chart_index_raw, bundle, sources
            )

        return ToolResult(
            content=(
                f"Error: unknown source {requested!r}. Valid values "
                "are 'auto', 'raw', 'chart'."
            ),
            is_error=True,
        )

    @staticmethod
    def _first_of_kind(
        sources: List[_SourceDescriptor], kind: SourceKind
    ) -> Optional[_SourceDescriptor]:
        for src in sources:
            if src.kind == kind:
                return src
        return None

    def _no_sources_error(
        self,
        bundle: ResolvedSimulationBundle,
        sources: List[_SourceDescriptor],
    ) -> ToolResult:
        return ToolResult(
            content=(
                f"Error: no signal CSVs were found under "
                f"'{bundle.bundle_dir.as_posix()}'. This bundle has "
                "neither raw_data/raw_data.csv nor an exported "
                "charts/ entry. Result metadata: "
                f"analysis_type='{bundle.result.analysis_type or 'unknown'}'. "
                "Typical causes: .op analyses (no sweep to record), a "
                "simulation that failed before persistence, or a "
                "partially cleaned bundle."
            ),
            is_error=True,
        )

    def _missing_source_error(
        self,
        requested: str,
        bundle: ResolvedSimulationBundle,
        sources: List[_SourceDescriptor],
        *,
        hint: str,
    ) -> ToolResult:
        available = ", ".join(
            sorted({src.kind.value for src in sources})
        ) or "none"
        return ToolResult(
            content=(
                f"Error: source='{requested}' is not available in "
                f"bundle '{bundle.result_path}'. {hint} "
                f"Available sources here: {available}."
            ),
            is_error=True,
        )

    def _missing_chart_error(
        self,
        requested_index: int,
        bundle: ResolvedSimulationBundle,
        sources: List[_SourceDescriptor],
    ) -> ToolResult:
        chart_descriptions = [
            f"{src.chart_index}={src.chart_type}"
            for src in sources
            if src.kind == SourceKind.CHART
        ]
        listing = (
            ", ".join(chart_descriptions)
            if chart_descriptions
            else "no charts have been exported for this bundle"
        )
        return ToolResult(
            content=(
                f"Error: chart_index={requested_index} was not found "
                f"in bundle '{bundle.result_path}'. Available chart "
                f"indices: {listing}."
            ),
            is_error=True,
        )

    # ------------------------------------------------------------------
    # Anchor scale / count resolution
    # ------------------------------------------------------------------

    def _resolve_anchor_scale(
        self,
        params: Dict[str, Any],
        target: _SourceDescriptor,
        bundle: ResolvedSimulationBundle,
    ) -> AnchorScale:
        raw = str(params.get("anchor_scale") or "auto").strip().lower()
        if raw == AnchorScale.LINEAR.value:
            return AnchorScale.LINEAR
        if raw == AnchorScale.LOG.value:
            return AnchorScale.LOG
        # auto: chart sidecar 的 log_x 优先（它是"这张图自己怎么画的"
        # 的最权威信号），否则回退到按 analysis_type 推断（.ac / .noise
        # 走 LOG，其余 LINEAR）。
        if target.kind == SourceKind.CHART and target.log_x_hint is not None:
            return AnchorScale.LOG if target.log_x_hint else AnchorScale.LINEAR
        if _is_log_x_analysis(bundle.result.analysis_type):
            return AnchorScale.LOG
        return AnchorScale.LINEAR

    @staticmethod
    def _resolve_anchor_count(raw: Any) -> int:
        if isinstance(raw, bool):
            return _DEFAULT_ANCHOR_COUNT
        if isinstance(raw, (int, float)):
            return int(raw)
        return _DEFAULT_ANCHOR_COUNT

    # ------------------------------------------------------------------
    # Signal filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_filter(raw: Any) -> List[str]:
        if not isinstance(raw, (list, tuple)):
            return []
        out: List[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    @staticmethod
    def _split_filter(
        names: Tuple[str, ...],
        filter_list: List[str],
    ) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        if not filter_list:
            return names, ()
        name_set = set(names)
        filter_set = set(filter_list)
        # Preserve CSV column order for matches; preserve caller order
        # (and any duplicates) in the unmatched echo so the LLM sees
        # exactly which entries it supplied that didn't resolve.
        matched_in_order = tuple(n for n in names if n in filter_set)
        unmatched = tuple(n for n in filter_list if n not in name_set)
        return matched_in_order, unmatched

    @staticmethod
    def _subset_series(
        result: SeriesReadResult,
        matched_names: Tuple[str, ...],
    ) -> SeriesReadResult:
        if tuple(matched_names) == result.signal_column_names:
            return result
        keep_indices = [
            i
            for i, name in enumerate(result.signal_column_names)
            if name in set(matched_names)
        ]
        return SeriesReadResult(
            header_entries=result.header_entries,
            x_column_name=result.x_column_name,
            signal_column_names=tuple(
                result.signal_column_names[i] for i in keep_indices
            ),
            total_rows=result.total_rows,
            x_range=result.x_range,
            stats=tuple(result.stats[i] for i in keep_indices),
            anchors=tuple(
                AnchorRow(
                    x=anchor.x,
                    values=tuple(anchor.values[i] for i in keep_indices),
                )
                for anchor in result.anchors
            ),
            anchor_scale_requested=result.anchor_scale_requested,
            anchor_scale_effective=result.anchor_scale_effective,
        )

    # ------------------------------------------------------------------
    # AC FOM 引用（不重算！）
    # ------------------------------------------------------------------

    def _should_link_ac_fom(
        self,
        target: _SourceDescriptor,
        bundle: ResolvedSimulationBundle,
    ) -> bool:
        """两种充要情形：
        1. target == raw + ``analysis_type == .ac``
        2. target == chart + ``chart_type == bode_overlay``
        其余一律不链 metrics.json，避免在 .tran / DC sweep 等场景
        误引 FOM 表。
        """
        if target.kind == SourceKind.CHART:
            return (target.chart_type or "") == _BODE_CHART_TYPE
        return _is_ac_analysis(bundle.result.analysis_type)

    def _load_ac_fom_rows(self, bundle_dir: Path) -> List[Dict[str, Any]]:
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
        matched.sort(
            key=lambda r: (
                0 if r["status"] == TargetStatus.FAIL else 1,
                r["display_name"].lower(),
            )
        )
        return matched

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def _build_markdown(
        self,
        *,
        bundle: ResolvedSimulationBundle,
        target: _SourceDescriptor,
        read_result: SeriesReadResult,
        full_signal_names: Tuple[str, ...],
        matched_names: Tuple[str, ...],
        unmatched_names: Tuple[str, ...],
        anchor_count_requested: int,
        ac_rows: List[Dict[str, Any]],
        sources: List[_SourceDescriptor],
    ) -> List[str]:
        result = bundle.result
        header_tag = self._source_header_tag(target)
        lines: List[str] = [
            f"# Signals Report ({header_tag})",
            "",
            f"- source: {target.kind.value}",
            f"- source_csv: {target.csv_path.as_posix()}",
        ]
        if target.image_path is not None:
            lines.append(f"- source_image: {target.image_path.as_posix()}")
            lines.append(
                "  _(image is for the user to open manually; shape "
                "conclusions should come from the numerical tables "
                "below)_"
            )
        if target.kind == SourceKind.CHART:
            lines.append(
                f"- chart_index: {target.chart_index}  "
                f"chart_type: {target.chart_type}  "
                f"title: {target.chart_title or ''}"
            )

        lines.extend(
            [
                f"- circuit_file: {bundle.circuit_file}",
                f"- analysis_type: {result.analysis_type or 'unknown'}",
                f"- executor: {result.executor or 'unknown'}",
                f"- timestamp: {result.timestamp or ''}",
                f"- result_path: {bundle.result_path}",
            ]
        )
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
                f"- signal_count: {len(read_result.signal_column_names)}"
                + (
                    f" (filtered from {len(full_signal_names)})"
                    if len(read_result.signal_column_names)
                    != len(full_signal_names)
                    else ""
                ),
                f"- sample_count: {read_result.total_rows}",
                f"- x_range: [{_fmt(read_result.x_range[0])}, "
                f"{_fmt(read_result.x_range[1])}]",
                (
                    f"- anchor_scale: "
                    f"{read_result.anchor_scale_effective.value}"
                    + (
                        f" (requested "
                        f"{read_result.anchor_scale_requested.value}; "
                        "data forced linear because x_min <= 0)"
                        if read_result.anchor_scale_effective
                        != read_result.anchor_scale_requested
                        else ""
                    )
                ),
            ]
        )

        if unmatched_names:
            lines.append("")
            lines.append(
                f"_Warning: signal_filter entries not present in "
                f"source: {', '.join(unmatched_names)}. Available "
                f"signals: {', '.join(full_signal_names)}._"
            )

        if read_result.total_rows == 0:
            lines.extend(
                [
                    "",
                    "_Signals csv was readable but had no numeric "
                    "data rows. The bundle likely encountered a "
                    "simulation error before samples were written._",
                ]
            )
            self._append_sources_available(lines, target, sources)
            return lines

        if len(read_result.signal_column_names) == 0:
            lines.extend(
                [
                    "",
                    "_No signals remained after applying signal_filter. "
                    "Re-run this tool without signal_filter (or with a "
                    "corrected list from 'Available signals' above) "
                    "to see the full series table._",
                ]
            )
            self._append_sources_available(lines, target, sources)
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

        # ---- AC FOM ----
        if ac_rows:
            lines.extend(
                [
                    "",
                    "## AC Figures of Merit",
                    "",
                    (
                        "_Pulled verbatim from metrics.json (computed "
                        "by the .MEASURE pipeline); this tool does "
                        "not re-derive these values from signal "
                        "samples._"
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

        self._append_sources_available(lines, target, sources)
        return lines

    @staticmethod
    def _source_header_tag(target: _SourceDescriptor) -> str:
        if target.kind == SourceKind.CHART:
            return (
                f"chart #{target.chart_index} "
                f"— {target.chart_type or 'chart'}"
            )
        return target.kind.value

    def _append_sources_available(
        self,
        lines: List[str],
        target: _SourceDescriptor,
        sources: List[_SourceDescriptor],
    ) -> None:
        """把"本 bundle 还有哪些源可读"以小列表形式附在文末。

        discovery 每次必挂——哪怕此刻只有一个源，也让 LLM 看到这
        条事实（"除此之外没别的了"），避免它去想 "也许还有其它
        chart 我漏了"。
        """
        lines.extend(["", "## Sources Available In This Bundle", ""])
        for src in sources:
            lines.append("- " + self._describe_source_entry(src, target))

    def _describe_source_entry(
        self,
        src: _SourceDescriptor,
        target: _SourceDescriptor,
    ) -> str:
        marker = " (current)" if src is target else ""
        if src.kind == SourceKind.CHART:
            series_hint = (
                f" — {src.series_count_hint} series"
                if src.series_count_hint is not None
                else ""
            )
            return (
                f"chart #{src.chart_index} ({src.chart_type}): "
                f"{src.chart_title or ''}{series_hint} → "
                f"{src.csv_path.as_posix()}{marker}"
            )
        series_hint = (
            f" — {src.series_count_hint} signals"
            if src.series_count_hint is not None
            else ""
        )
        return (
            f"{src.kind.value}{series_hint} → "
            f"{src.csv_path.as_posix()}{marker}"
        )

    def _descriptor_to_details(
        self, src: _SourceDescriptor
    ) -> Dict[str, Any]:
        return {
            "source": src.kind.value,
            "csv_path": str(src.csv_path),
            "image_path": str(src.image_path) if src.image_path else None,
            "chart_index": src.chart_index,
            "chart_type": src.chart_type,
            "chart_title": src.chart_title,
            "log_x_hint": src.log_x_hint,
            "series_count_hint": src.series_count_hint,
        }

    # ------------------------------------------------------------------
    # Line cap
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
    return _strip_analysis(analysis_type) == "ac"


def _is_log_x_analysis(analysis_type: Optional[str]) -> bool:
    """auto anchor_scale 在 raw 分支的判定：.ac / .noise 用 LOG。"""
    return _strip_analysis(analysis_type) in {"ac", "noise"}


def _strip_analysis(analysis_type: Optional[str]) -> str:
    return (analysis_type or "").strip().lstrip(".").lower()


def _matches_ac_keyword(text: str) -> bool:
    if not text:
        return False
    needle = text.strip().lower()
    for keyword in _AC_FOM_KEYWORDS:
        if keyword in needle:
            return True
    return False


def _read_json_signal_count(json_path: Path) -> Optional[int]:
    """``raw_data.json`` 在 ``summary.signal_count`` 暴露信号数。"""
    if not json_path.is_file():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if isinstance(summary, dict):
        value = summary.get("signal_count")
        if isinstance(value, int):
            return value
    return None


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
    """紧凑浮点格式化（与 read_metrics 一致）。"""
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


__all__ = ["ReadSignalsTool", "SourceKind"]
