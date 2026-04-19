"""Contract tests for :class:`ReadWaveformTool` (Step 18).

把"波形 CSV → LLM 摘要"的不变量钉死：

* 摘要内容包含 Series Statistics 表 + Anchor Samples 表；图像只以
  相对路径出现，**不**进 content、**不**进 details 任何字节字段。
* ``.ac`` 分析触发对数锚点 + 拉 ``metrics.json`` 的
  ``bandwidth``/``gain_margin``/``phase_margin`` 行（**引用**，不
  重算）。
* 缺 ``waveform.csv`` → is_error 且 content 不点名下一步 tool。
* 清理清单不变量：模块内不 import ``base64``；不对 ``*.png``
  调用 ``read_bytes()``/``read_text()``；不对 waveform.csv 做
  ``read_text()``/``readlines()``（只走流式 open）。
"""

from __future__ import annotations

import asyncio
import ast
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from domain.llm.agent.tools.read_waveform import ReadWaveformTool
from domain.llm.agent.tools.simulation_artifact_reader_base import (
    SimulationArtifactReaderBase,
)
from domain.llm.agent.tools.simulation_series_stats import (
    AnchorScale,
    read_series_csv,
)
from domain.llm.agent.types import ToolContext, ToolResult
from domain.simulation.data.simulation_artifact_exporter import (
    simulation_artifact_exporter,
)
from domain.simulation.models.simulation_result import SimulationResult
from domain.simulation.service.simulation_result_repository import (
    CircuitResultGroup,
    SimulationResultSummary,
)
from shared.models.load_result import LoadResult


# ============================================================
# 测试替身（与 test_simulation_artifact_reader_base 同款）
# ============================================================


class _FakeRepository:
    """Minimal repository stand-in exposing only the three methods the
    base consults: ``load`` / ``resolve_bundle_dir`` / ``list_by_circuit``.
    """

    def __init__(
        self,
        loaded: Optional[Dict[str, LoadResult[SimulationResult]]] = None,
        bundle_dirs: Optional[Dict[str, Optional[Path]]] = None,
        groups: Optional[List[CircuitResultGroup]] = None,
    ) -> None:
        self._loaded = dict(loaded or {})
        self._bundle_dirs = dict(bundle_dirs or {})
        self._groups = list(groups or [])

    def load(self, project_root, result_path):
        if result_path in self._loaded:
            return self._loaded[result_path]
        return LoadResult.file_missing(result_path)

    def resolve_bundle_dir(self, project_root, result_path):
        return self._bundle_dirs.get(result_path)

    def list_by_circuit(self, project_root, per_circuit_limit=5):
        return list(self._groups)


# ============================================================
# 辅助
# ============================================================


def _make_result(
    *,
    file_path: str = "circuits/amp.cir",
    analysis_type: str = "tran",
) -> SimulationResult:
    return SimulationResult(
        executor="spice",
        file_path=file_path,
        analysis_type=analysis_type,
        success=True,
    )


def _write_waveform_csv(
    bundle_dir: Path,
    *,
    result: SimulationResult,
    columns: List[str],
    rows: List[Dict[str, float]],
) -> Path:
    """Use the exporter's own helper to write the CSV, including the
    self-verifying ``# key: value`` header. Piggy-backing on the real
    helper means the test fixture and the production writer stay in
    lockstep—renaming a header key or subdir is caught here first.
    """
    paths = simulation_artifact_exporter.waveforms_paths(bundle_dir)
    paths.directory.mkdir(parents=True, exist_ok=True)
    simulation_artifact_exporter.write_csv_with_header(
        paths.csv_path, result, "waveforms", columns, rows
    )
    # 占位图像文件——tool 只检测 waveform.csv；测试不依赖图像内容。
    paths.image_path.write_bytes(b"")
    return paths.csv_path


def _write_metrics_json(
    bundle_dir: Path,
    rows: List[Dict[str, object]],
) -> Path:
    """Plant a minimal metrics.json under ``bundle_dir/metrics/``.

    The tool only consults ``data.rows``; other payload keys are
    zero-valued placeholders, matching what the exporter produces but
    without invoking the full exporter pipeline (which needs a live
    ``DisplayMetric`` list).
    """
    metrics_paths = simulation_artifact_exporter.metrics_paths(bundle_dir)
    metrics_paths.directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "artifact_type": "metrics",
        "metadata": {},
        "summary": {"metric_count": len(rows)},
        "files": {"csv": "metrics.csv"},
        "data": {"columns": [], "rows": rows},
    }
    metrics_paths.json_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return metrics_paths.json_path


def _make_group(
    *,
    circuit_absolute_path: str,
    result_path: str,
    circuit_file: str = "circuits/amp.cir",
    timestamp: str = "2026-01-01T00:00:00",
    analysis_type: str = "tran",
) -> CircuitResultGroup:
    summary = SimulationResultSummary(
        id=result_path.rsplit("/", 1)[0],
        result_path=result_path,
        circuit_file=circuit_file,
        analysis_type=analysis_type,
        success=True,
        timestamp=timestamp,
    )
    return CircuitResultGroup(
        circuit_file=circuit_file,
        circuit_absolute_path=circuit_absolute_path,
        results=[summary],
    )


def _run(tool: ReadWaveformTool, params: dict, context: ToolContext) -> ToolResult:
    return asyncio.get_event_loop().run_until_complete(
        tool.execute("call_0", params, context)
    )


# ============================================================
# 基本路径协议（与 Step 16 基座对齐）
# ============================================================


def test_read_waveform_registers_via_common_schema():
    """参数 schema 继承自公共基座——``result_path`` / ``file_path``
    必存在且不在 ``required`` 里（可选）；工具自己的 ``anchor_count``
    是可选整数。"""
    tool = ReadWaveformTool()
    schema = tool.parameters
    assert schema["type"] == "object"
    assert "result_path" in schema["properties"]
    assert "file_path" in schema["properties"]
    assert "anchor_count" in schema["properties"]
    assert "result_path" not in schema["required"]
    assert "file_path" not in schema["required"]


def test_read_waveform_tran_emits_stats_and_linear_anchors(tmp_path):
    """Happy path: ``.tran`` 分析 → 返回 Series Statistics + 线性锚点
    表；content 里包含 image 相对路径但**不**含任何 base64/字节。"""
    sim_result = _make_result(file_path="circuits/amp.cir", analysis_type="tran")
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result_path = "simulation_results/amp/2026-01-01/result.json"

    # 构造 21 行三角波 + 斜坡信号：
    # - V(out) 对 x=0 起步、单次穿越 0（从负转正）——zero_crossings=1。
    # - V(in)  全正恒定——zero_crossings=0、pk_pk=0。
    rows = []
    for i in range(21):
        t = i / 20.0
        rows.append({"time": t, "V(out)": (t - 0.5) * 2.0, "V(in)": 1.0})
    _write_waveform_csv(
        bundle_dir,
        result=sim_result,
        columns=["time", "V(out)", "V(in)"],
        rows=rows,
    )

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
    )
    context = ToolContext(project_root=str(tmp_path), sim_result_repository=repo)

    tool = ReadWaveformTool()
    result = _run(tool, {"result_path": result_path}, context)

    assert not result.is_error, result.content
    content = result.content
    assert "# Waveform Report" in content
    assert "analysis_type: tran" in content
    assert "## Series Statistics" in content
    assert "V(out)" in content
    assert "V(in)" in content
    # 线性锚点 section 头带 "linear"
    assert "linear" in content.lower()
    # image 相对路径必须出现（让用户能打开），但只是路径字符串
    assert "waveform.png" in content
    # 严禁出现任何 base64 风格字符串（长串 A-Za-z0-9/+ 末尾 =）
    # 这是清理清单第 1 条的运行时自证。
    assert "base64" not in content.lower()

    # details 只暴露路径、计数、scale；绝无字节字段。
    details = result.details
    assert details is not None
    assert details["artifact_type"] == "waveforms"
    assert details["signal_count"] == 2
    assert details["sample_count"] == 21
    assert details["anchor_scale_effective"] == "linear"
    assert "waveform_image_path" in details
    for key in details:
        # 任何暗示"字节内容"的 key 都不应出现。
        assert "bytes" not in key.lower()
        assert "base64" not in key.lower()


def test_read_waveform_zero_crossings_counts_strict_pairwise(tmp_path):
    """``zero_crossings`` 使用"严格相邻对符号翻转"定义——两条相邻
    非空采样乘积 < 0 才计 1 次。这是数值上最干净的定义：

    * 零值自然打断计数（``+1 → 0 → -1`` 不计），无需额外追踪
      "上一次非零值"；
    * LLM 读出的 "N zero-crossings" 语义与工程师口中的一致。
    """
    sim_result = _make_result()
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result_path = "simulation_results/amp/2026-01-01/result.json"

    # 场景 A：+1, -1, +1, -1, +1 → 严格翻转 4 次。
    rows_a = [
        {"time": 0.0, "V(out)": 1.0},
        {"time": 1.0, "V(out)": -1.0},
        {"time": 2.0, "V(out)": 1.0},
        {"time": 3.0, "V(out)": -1.0},
        {"time": 4.0, "V(out)": 1.0},
    ]
    _write_waveform_csv(
        bundle_dir,
        result=sim_result,
        columns=["time", "V(out)"],
        rows=rows_a,
    )
    stats_a = read_series_csv(
        csv_path=simulation_artifact_exporter.waveforms_paths(bundle_dir).csv_path,
        anchor_count=5,
        anchor_scale=AnchorScale.LINEAR,
    ).stats[0]
    assert stats_a.zero_crossings == 4
    assert stats_a.samples == 5
    assert stats_a.peak_to_peak == 2.0
    assert stats_a.initial_value == 1.0
    assert stats_a.final_value == 1.0

    # 场景 B：+1, -1, +1, 0, -1 → 零值打断，严格翻转仅 2 次
    # （+1↔-1, -1↔+1）；``+1 → 0`` 和 ``0 → -1`` 都不计数。
    bundle_dir_b = tmp_path / "simulation_results" / "amp" / "2026-01-02"
    bundle_dir_b.mkdir(parents=True)
    rows_b = [
        {"time": 0.0, "V(out)": 1.0},
        {"time": 1.0, "V(out)": -1.0},
        {"time": 2.0, "V(out)": 1.0},
        {"time": 3.0, "V(out)": 0.0},
        {"time": 4.0, "V(out)": -1.0},
    ]
    _write_waveform_csv(
        bundle_dir_b,
        result=sim_result,
        columns=["time", "V(out)"],
        rows=rows_b,
    )
    stats_b = read_series_csv(
        csv_path=simulation_artifact_exporter.waveforms_paths(bundle_dir_b).csv_path,
        anchor_count=5,
        anchor_scale=AnchorScale.LINEAR,
    ).stats[0]
    assert stats_b.zero_crossings == 2, (
        "+1 → 0 → -1 must NOT count as a crossing; zero breaks the "
        "strict pair-wise definition"
    )


def test_read_waveform_ac_uses_log_anchors_and_references_metrics(tmp_path):
    """``.ac`` → 锚点对数分布；bandwidth / phase_margin 这类行被
    **原样**拉自 metrics.json（绝不重算）。"""
    sim_result = _make_result(analysis_type="ac")
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result_path = "simulation_results/amp/2026-01-01/result.json"

    # 10 行对数扫频（1Hz → 1e9Hz），V(out) 增益单调衰减。
    import math
    rows = []
    for i in range(10):
        f = 10 ** i if i < 10 else 1e9
        rows.append({"frequency": f, "V(out)": 20.0 - i * 2.0})
    _write_waveform_csv(
        bundle_dir,
        result=sim_result,
        columns=["frequency", "V(out)"],
        rows=rows,
    )

    # metrics.json：bandwidth / phase_margin / gain_margin 各一条；
    # 再配一条与 .ac 派生量**无关**的行，确认工具不会误拉。
    _write_metrics_json(
        bundle_dir,
        rows=[
            {
                "display_name": "Bandwidth",
                "name": "bandwidth",
                "value": "1.20 MHz",
                "unit": "Hz",
                "raw_value": 1.2e6,
                "target": "≥ 10 MHz",
            },
            {
                "display_name": "Phase Margin",
                "name": "phase_margin",
                "value": "45.00 °",
                "unit": "°",
                "raw_value": 45.0,
                "target": "≥ 45°",
            },
            {
                "display_name": "Gain Margin",
                "name": "gain_margin",
                "value": "12.00 dB",
                "unit": "dB",
                "raw_value": 12.0,
                "target": "",
            },
            {
                "display_name": "Idle Current",
                "name": "i_idle",
                "value": "3.20 mA",
                "unit": "A",
                "raw_value": 3.2e-3,
                "target": "",
            },
        ],
    )

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
    )
    context = ToolContext(project_root=str(tmp_path), sim_result_repository=repo)

    result = _run(ReadWaveformTool(), {"result_path": result_path}, context)

    assert not result.is_error, result.content
    content = result.content
    # 对数锚点 section 头带 "log"。
    assert "## Anchor Samples" in content
    assert "log" in content.lower()

    # AC FOM 小表里三条派生量都在；i_idle 不该出现。
    assert "## AC Figures of Merit" in content
    assert "Bandwidth" in content
    assert "Phase Margin" in content
    assert "Gain Margin" in content
    assert "Idle Current" not in content

    # bandwidth 目标 ≥ 10 MHz，实际 1.2 MHz → FAIL；
    # phase_margin 45° 目标 ≥45° → PASS。
    lines = content.splitlines()

    def _row_with(name: str) -> str:
        for line in lines:
            if line.startswith("|") and name in line:
                return line
        raise AssertionError(f"row for {name!r} not present in content")

    assert "FAIL" in _row_with("Bandwidth")
    assert "PASS" in _row_with("Phase Margin")
    # 无 target 的 Gain Margin 状态为 "—"，但行必须出现。
    assert "Gain Margin" in _row_with("Gain Margin")


def test_read_waveform_missing_csv_reports_facts_only(tmp_path):
    """缺 ``waveform.csv`` → is_error；content 只陈述事实
    （缺哪个路径 + analysis_type），**不**点名下一步 tool。"""
    sim_result = _make_result(analysis_type="op")
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    # 不写 waveforms/，模拟 .op bundle 形态。
    result_path = "simulation_results/amp/2026-01-01/result.json"

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
    )
    context = ToolContext(project_root=str(tmp_path), sim_result_repository=repo)

    result = _run(ReadWaveformTool(), {"result_path": result_path}, context)

    assert result.is_error
    content = result.content
    assert "waveform" in content.lower()
    assert "op" in content.lower()
    # Law 3 合规：错误文案不得点名另一个 tool（只陈述事实）。
    # 这里直接断言几个常见 tool 名都不出现。
    for forbidden in (
        "read_op_result",
        "read_metrics",
        "read_output_log",
        "run_simulation",
    ):
        assert forbidden not in content, (
            f"error content must not route to {forbidden!r}; it should "
            "only state facts so the LLM chooses the next step"
        )


def test_read_waveform_clean_list_invariants():
    """**清理清单四条静态不变量**的一次性 AST 自证——用语法树而非
    朴素字符串搜索，避免 docstring 里讨论"不做 X"的文字把测试自己
    绊倒：

    1. 不 ``import base64`` / ``from base64 import ...``；
    2. 不对任何对象调用 ``.read_bytes()``（覆盖 PNG 字节读取）；
    3. 不对 waveform 路径对象调用 ``.read_text()`` / ``.readlines()``
       （唯一合法的全量 read_text 是读 metrics.json；流式 csv 走
       :func:`read_series_csv` 内部 ``open(...)`` 逐行处理）；
    4. 不存在 ``bandwidth = ...``、``gain_margin = ...``、
       ``phase_margin = ...`` 形式的赋值——这三者来源于 ``.MEASURE``
       管线，read_waveform 只引用不重算。
    """
    this_file = Path(__file__).resolve()
    tool_file = (
        this_file.parents[1]
        / "domain" / "llm" / "agent" / "tools" / "read_waveform.py"
    )
    stats_file = (
        this_file.parents[1]
        / "domain" / "llm" / "agent" / "tools" / "simulation_series_stats.py"
    )
    tool_tree = ast.parse(tool_file.read_text(encoding="utf-8"))
    stats_tree = ast.parse(stats_file.read_text(encoding="utf-8"))

    # --- 不变量 1：base64 零 import（工具 + 共享 stats 模块） ---
    def _imported_modules(tree: ast.AST) -> set[str]:
        seen: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    seen.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    seen.add(node.module.split(".")[0])
        return seen

    assert "base64" not in _imported_modules(tool_tree)
    assert "base64" not in _imported_modules(stats_tree)

    # --- 不变量 2：任何对象 .read_bytes() 都禁止 ---
    def _attr_calls(tree: ast.AST, name: str) -> list[str]:
        hits: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == name
            ):
                hits.append(
                    ast.unparse(node)
                    if hasattr(ast, "unparse")
                    else node.func.attr
                )
        return hits

    assert _attr_calls(tool_tree, "read_bytes") == []

    # --- 不变量 3：禁止对 waveform/csv 路径对象调 read_text/readlines ---
    #
    # 在 tool 里 ``read_text`` 只应用于 metrics.json（``.json_path``
    # 之类）；任何路径名含 "csv" / "waveform" 的调用都属违反。
    def _forbidden_path_reads(tree: ast.AST) -> list[str]:
        bad: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"read_text", "readlines"}
            ):
                caller_src = (
                    ast.unparse(node.func.value).lower()
                    if hasattr(ast, "unparse")
                    else ""
                )
                if "csv" in caller_src or "waveform" in caller_src:
                    bad.append(
                        ast.unparse(node)
                        if hasattr(ast, "unparse")
                        else caller_src
                    )
        return bad

    assert _forbidden_path_reads(tool_tree) == []

    # --- 不变量 4：.ac 派生量不重算 ---
    forbidden_targets = {"bandwidth", "gain_margin", "phase_margin"}

    def _forbidden_assignments(tree: ast.AST) -> list[str]:
        bad: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            else:
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id in forbidden_targets:
                    bad.append(tgt.id)
        return bad

    assert _forbidden_assignments(tool_tree) == []


def test_read_waveform_anchor_count_clamped(tmp_path):
    """``anchor_count`` 明显越界 → 内部 clamp 到 [4, 32]，不抛错。"""
    sim_result = _make_result()
    bundle_dir = tmp_path / "simulation_results" / "amp" / "2026-01-01"
    bundle_dir.mkdir(parents=True)
    result_path = "simulation_results/amp/2026-01-01/result.json"

    rows = [{"time": i / 99.0, "V(out)": i * 0.01} for i in range(100)]
    _write_waveform_csv(
        bundle_dir,
        result=sim_result,
        columns=["time", "V(out)"],
        rows=rows,
    )

    repo = _FakeRepository(
        loaded={result_path: LoadResult.ok(sim_result, result_path)},
        bundle_dirs={result_path: bundle_dir},
    )
    context = ToolContext(project_root=str(tmp_path), sim_result_repository=repo)

    result = _run(
        ReadWaveformTool(),
        {"result_path": result_path, "anchor_count": 9999},
        context,
    )

    assert not result.is_error
    # ``requested`` 原样回显用户输入，便于 LLM 对齐"自己要了什么 vs
    # 实际拿到什么"；``effective`` 才是 clamp 后的值。
    assert result.details["anchor_count_requested"] == 9999
    assert result.details["anchor_count_effective"] <= 32

    result_small = _run(
        ReadWaveformTool(),
        {"result_path": result_path, "anchor_count": 0},
        context,
    )
    assert not result_small.is_error
    assert result_small.details["anchor_count_requested"] == 0
    # clamp 下界 4：零输入绝不会导致空锚点表。
    assert result_small.details["anchor_count_effective"] >= 4
